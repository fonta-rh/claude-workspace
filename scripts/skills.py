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
    skill_dir = find_skill_dir(root, repo, name)
    if skill_dir is None:
        fail(f"No skill with frontmatter name '{name}' found in "
             f"repos/{repo}/.claude/skills/")

    skills_dir = ws_skills_dir(root)
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
    else:
        fail(f"Unknown subcommand: {command}")
        return  # unreachable; keeps type-checkers happy

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
