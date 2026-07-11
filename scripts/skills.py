#!/usr/bin/env python3
"""Manage workspace symlinks that surface repo-shipped skills.

Skills living in repos (repos/<repo>/.claude/skills/) are only discovered
by Claude Code inside that repo's directory. Flat-symlinking them into the
workspace's .claude/skills/ makes them visible in autocomplete at the
workspace root. This script owns discovery, symlinking, verification, and
the cross-project refcount used at close time.

Usage:
  skills.py scan <repo> [<repo>...]
  skills.py link <name> <repo>
  skills.py verify <project>
  skills.py unlink-check <project>

Output: JSON to stdout. Always {"status": "ok" | "error", ...}; fatal
problems report status "error" and still exit 0 so calling skills can
parse the message.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Plugins cannot declare python dependencies. PyYAML is required to parse
# skill and project frontmatter — emit a self-describing JSON error (that
# the calling skill can relay) instead of a raw ImportError traceback.
try:
    import yaml
except ImportError:
    print(json.dumps({
        "status": "error",
        "error": "PyYAML is required by skills.py (skill frontmatter is "
                 "YAML). Install with: pip3 install pyyaml",
    }))
    sys.exit(0)

import workspace_lib


def fail(message: str) -> None:
    print(json.dumps({"status": "error", "error": message}))
    sys.exit(0)


def is_safe_name(name: str) -> bool:
    """True if `name` is safe to use as a single path component under
    .claude/skills/ — i.e. it cannot escape that directory.

    A repo controls its skills' frontmatter `name:`, so this must reject
    anything containing a path separator or a dot-segment ("." or "..")
    before it is ever joined onto a filesystem path.
    """
    if not name or not isinstance(name, str):
        return False
    if name in (".", ".."):
        return False
    return Path(name).name == name


def parse_frontmatter(path: Path) -> dict[str, Any]:
    """Extract YAML frontmatter between --- delimiters."""
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return {}

    if not lines or lines[0].strip() != "---":
        return {}

    fm_lines: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        fm_lines.append(line)
    else:
        return {}

    try:
        result = yaml.safe_load("\n".join(fm_lines))
    except yaml.YAMLError:
        return {}
    return result if isinstance(result, dict) else {}


def ws_skills_dir(root: Path) -> Path:
    return root / ".claude" / "skills"


def repo_skills_dir(root: Path, repo: str) -> Path:
    return root / "repos" / repo / ".claude" / "skills"


def iter_repo_skills(root: Path, repo: str):
    """Yield (skill_dir, frontmatter) for every SKILL.md dir in the repo."""
    skills_dir = repo_skills_dir(root, repo)
    if not skills_dir.is_dir():
        return
    for child in sorted(skills_dir.iterdir()):
        skill_md = child / "SKILL.md"
        if child.is_dir() and skill_md.is_file():
            yield child, parse_frontmatter(skill_md)


def find_skill_dir(root: Path, repo: str, name: str) -> Path | None:
    """Repo skill dir whose frontmatter name equals `name`."""
    for skill_dir, fm in iter_repo_skills(root, repo):
        if fm.get("name") == name:
            return skill_dir
    return None


def classify_existing(entry: Path, target: Path) -> str:
    """How does the workspace entry relate to the intended target?

    Returns "absent", "same_source", "dangling", or "collision".
    """
    if not os.path.lexists(entry):
        return "absent"
    if entry.is_symlink():
        if not os.path.exists(entry):
            return "dangling"
        if entry.resolve() == target.resolve():
            return "same_source"
    return "collision"


def cmd_scan(root: Path, repos: list[str]) -> dict:
    skills: list[dict] = []
    errors: list[str] = []

    for repo in repos:
        if not (root / "repos" / repo).is_dir():
            errors.append(f"repo '{repo}' is not cloned under repos/")
            continue
        for skill_dir, fm in iter_repo_skills(root, repo):
            name = fm.get("name")
            if not name or not isinstance(name, str):
                errors.append(
                    f"{repo}: skill dir '{skill_dir.name}' has no usable "
                    f"frontmatter name: — skipped")
                continue
            if not is_safe_name(name):
                errors.append(
                    f"{repo}: skill dir '{skill_dir.name}' has an unsafe "
                    f"frontmatter name '{name}' — skipped")
                continue
            skills.append({
                "name": name,
                "description": str(fm.get("description", "")),
                "repo": repo,
                "dir": skill_dir.name,
                "path": str(skill_dir),
                "conflict": False,
                "already_present": None,
            })

    name_counts: dict[str, int] = {}
    for s in skills:
        name_counts[s["name"]] = name_counts.get(s["name"], 0) + 1
    for s in skills:
        s["conflict"] = name_counts[s["name"]] > 1

    for s in skills:
        entry = ws_skills_dir(root) / s["name"]
        state = classify_existing(entry, Path(s["path"]))
        if state == "same_source":
            s["already_present"] = {"status": "same_source"}
        elif state == "dangling":
            s["already_present"] = {"status": "dangling"}
        elif state == "collision":
            target = str(entry.resolve()) if os.path.exists(entry) else str(entry)
            s["already_present"] = {"status": "collision", "target": target}

    return {"status": "ok", "workspace": str(root),
            "skills": skills, "errors": errors}


def cmd_link(root: Path, name: str, repo: str) -> dict:
    if not is_safe_name(name):
        fail(f"skill name '{name}' is not a valid skill name")

    skill_dir = find_skill_dir(root, repo, name)
    if skill_dir is None:
        fail(f"No skill with frontmatter name '{name}' found in "
             f"repos/{repo}/.claude/skills/")

    skills_dir = ws_skills_dir(root)
    if skills_dir.exists() and not skills_dir.is_dir():
        fail(f"{skills_dir} exists and is not a directory — refusing to link")
    created_dir = not skills_dir.is_dir()
    skills_dir.mkdir(parents=True, exist_ok=True)

    entry = skills_dir / name
    state = classify_existing(entry, skill_dir)
    if state == "collision":
        fail(f"{entry} already exists and is not a symlink to this skill "
             f"— refusing to touch it")
    existed = state == "same_source"
    if state == "dangling":
        entry.unlink()

    target = os.path.relpath(skill_dir, skills_dir)
    if not existed:
        os.symlink(target, entry)

    return {
        "status": "ok",
        "linked": {"name": name, "repo": repo,
                   "path": str(entry), "target": os.readlink(entry)},
        "existed": existed,
        "created_dir": created_dir,
    }


def read_project_skills(root: Path, project: str) -> list[dict]:
    """Normalized [{name, source}] from a project's frontmatter skills: list."""
    claude_md = root / "projects" / project / "CLAUDE.md"
    if not claude_md.is_file():
        fail(f"Project '{project}' not found (no {claude_md})")
    raw = parse_frontmatter(claude_md).get("skills") or []
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if isinstance(item, dict) and item.get("name"):
            result.append({"name": str(item["name"]),
                           "source": str(item.get("source", ""))})
    return result


def cmd_verify(root: Path, project: str) -> dict:
    results = []
    for skill in read_project_skills(root, project):
        name, source = skill["name"], skill["source"]
        source_dir = find_skill_dir(root, source, name)
        entry = ws_skills_dir(root) / name

        record = {"name": name, "source": source}
        if source_dir is None:
            record["state"] = "source_gone"
        else:
            state = classify_existing(entry, source_dir)
            if state == "absent":
                record["state"] = "missing"
            elif state == "same_source":
                record["state"] = "ok"
            elif state == "dangling":
                record["state"] = "broken"
            else:  # collision: real dir or symlink to a different skill
                record["state"] = "broken"
                record["detail"] = "points_elsewhere"
        results.append(record)

    return {"status": "ok", "skills": results}


def cmd_unlink_check(root: Path, project: str) -> dict:
    own_skills = read_project_skills(root, project)

    # Skill name -> other active (status != done) projects referencing it.
    used_by: dict[str, list[str]] = {}
    projects_dir = root / "projects"
    if projects_dir.is_dir():
        for other_dir in sorted(projects_dir.iterdir()):
            if not other_dir.is_dir() or other_dir.name == project:
                continue
            claude_md = other_dir / "CLAUDE.md"
            if not claude_md.is_file():
                continue
            fm = parse_frontmatter(claude_md)
            if fm.get("status") == "done":
                continue
            raw = fm.get("skills") or []
            if not isinstance(raw, list):
                continue
            for item in raw:
                if isinstance(item, dict) and item.get("name"):
                    used_by.setdefault(str(item["name"]), []).append(
                        other_dir.name)

    results = []
    for skill in own_skills:
        name = skill["name"]
        entry = ws_skills_dir(root) / name
        missing = not os.path.lexists(entry)
        is_symlink = entry.is_symlink()
        users = used_by.get(name, [])
        results.append({
            "name": name,
            "source": skill["source"],
            "missing": missing,
            "is_symlink": is_symlink,
            "removable": not missing and is_symlink and not users,
            "used_by": users,
        })

    return {"status": "ok", "skills": results}


def main():
    root = workspace_lib.resolve_workspace_root()
    if root is None:
        fail("Could not determine the workspace root. Set WORKSPACE_ROOT "
             "or run inside a workspace (a directory containing dev-env.yaml).")

    args = sys.argv[1:]
    if not args:
        fail("Usage: skills.py <scan|link|verify|unlink-check> ...")
    command, rest = args[0], args[1:]

    if command == "scan":
        if not rest:
            fail("scan requires at least one repo name")
        result = cmd_scan(root, rest)
    elif command == "link":
        if len(rest) != 2:
            fail("Usage: skills.py link <name> <repo>")
        result = cmd_link(root, rest[0], rest[1])
    elif command == "verify":
        if len(rest) != 1:
            fail("Usage: skills.py verify <project>")
        result = cmd_verify(root, rest[0])
    elif command == "unlink-check":
        if len(rest) != 1:
            fail("Usage: skills.py unlink-check <project>")
        result = cmd_unlink_check(root, rest[0])
    else:
        fail(f"Unknown subcommand: {command}")
        return  # unreachable; keeps type-checkers happy

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
