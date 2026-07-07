# Surface Repo Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface skills shipped inside cloned repos (`$WS/repos/<repo>/.claude/skills/`) in workspace-root autocomplete by flat-symlinking them into `$WS/.claude/skills/`, with the lifecycle bound to `/workspace:new`, `/workspace:resume`, and `/workspace:close`.

**Architecture:** A new plugin script `scripts/skills.py` (subcommands `scan` / `link` / `verify` / `unlink-check`, JSON to stdout) does all discovery, symlinking, verification, and cross-project refcounting. The three project skills call it and present results; project frontmatter (`skills:` list) is the durable record. `setup.sh` pre-creates `$WS/.claude/skills/` so Claude Code's filesystem watcher (which only monitors dirs that exist at session start) picks up symlinks live.

**Tech Stack:** Python 3.9+ (stdlib + PyYAML), bash 3.2 (setup.sh), Claude Code plugin skills (markdown).

**Spec:** `docs/superpowers/specs/2026-07-07-repo-skills-surfacing-design.md` — read it before starting.

## Global Constraints

- Base branch: `issue-1-skill-surfacing` (already branched from PR #3's head).
- Python scripts: `from __future__ import annotations`; python 3.9 compatible (macOS system python); PyYAML import guarded with a self-describing JSON error (copy the pattern from `scripts/resume-project.py:23-31`).
- All script JSON output has top-level `"status": "ok" | "error"`. Fatal errors print `{"status": "error", "error": "..."}` and **exit 0** (calling skills always get parseable JSON) — identical to `resume-project.py`.
- Workspace resolution only via `workspace_lib.resolve_workspace_root()`. Never from `__file__`.
- Symlinks: always **relative**, always named after the skill's frontmatter `name:`, always targeting the main checkout (`repos/<repo>/`, never `.worktrees/`).
- Never modify or remove anything under `$WS/.claude/skills/` that is not a symlink (exception: a *dangling* symlink may be replaced/removed).
- setup.sh must stay bash-3.2 portable (no `declare -A`, no `${var,,}`, etc.).
- Skill markdown: reference the script as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/skills.py" ...` and workspace paths as `$WS/...`, matching the conventions already used in `skills/new/SKILL.md`.
- Commit after every task (messages given per task).

---

### Task 1: `skills.py` skeleton + `scan` subcommand

**Files:**
- Create: `scripts/skills.py`
- Create: `tests/test_skills.py`

**Interfaces:**
- Consumes: `workspace_lib.resolve_workspace_root() -> Path | None` (existing).
- Produces (used by every later task):
  - `parse_frontmatter(path: Path) -> dict[str, Any]`
  - `ws_skills_dir(root: Path) -> Path` → `$WS/.claude/skills`
  - `repo_skills_dir(root: Path, repo: str) -> Path` → `$WS/repos/<repo>/.claude/skills`
  - `find_skill_dir(root: Path, repo: str, name: str) -> Path | None` — repo skill dir whose frontmatter `name:` == name
  - `classify_existing(entry: Path, target: Path) -> str` — `"absent" | "same_source" | "dangling" | "collision"`
  - `cmd_scan(root: Path, repos: list[str]) -> dict`
  - CLI: `skills.py scan <repo> [<repo>...]`
- Test helpers produced for later tasks (in `tests/test_skills.py`):
  - `run_skills(ws: Path, *args: str) -> dict` — runs the script with `WORKSPACE_ROOT=ws`, asserts exit 0, returns parsed JSON
  - `SkillsFixture` base `unittest.TestCase` with `make_workspace()`, `make_repo_skill(repo, dirname, name, description)`, `make_project(name, status, skills)`

- [ ] **Step 1: Write the test file with fixtures and scan tests**

Create `tests/test_skills.py`:

```python
#!/usr/bin/env python3
"""Tests for scripts/skills.py.

Standalone: python3 tests/test_skills.py
Requires PyYAML (as does the script under test).

Each test builds a throwaway workspace (dev-env.yaml + repos/ + projects/)
in a temp dir and drives skills.py as a subprocess with WORKSPACE_ROOT set,
mirroring how tests/test_setup.sh isolates setup.sh.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "skills.py"


def run_skills(ws: Path, *args: str) -> dict:
    """Run skills.py against workspace ws; assert exit 0; return parsed JSON."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True,
        env={**os.environ, "WORKSPACE_ROOT": str(ws)},
    )
    assert result.returncode == 0, (
        f"skills.py exited {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return json.loads(result.stdout)


class SkillsFixture(unittest.TestCase):
    """Temp workspace with helpers to plant repo skills and projects."""

    def setUp(self):
        # resolve(): on macOS mkdtemp returns /var/... which is a symlink to
        # /private/var/... — path-equality assertions need the real path.
        self.tmp = Path(tempfile.mkdtemp(prefix="skills-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ws = self.tmp / "ws"
        (self.ws / "repos").mkdir(parents=True)
        (self.ws / "projects").mkdir()
        (self.ws / "dev-env.yaml").write_text("repos: []\n")

    def make_repo_skill(self, repo: str, dirname: str, name: str,
                        description: str = "A test skill") -> Path:
        """Create repos/<repo>/.claude/skills/<dirname>/SKILL.md; return the dir."""
        skill_dir = self.ws / "repos" / repo / ".claude" / "skills" / dirname
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"
        )
        return skill_dir

    def make_project(self, name: str, status: str = "active",
                     skills: list[dict] | None = None) -> Path:
        """Create projects/<name>/CLAUDE.md with frontmatter; return the dir."""
        project_dir = self.ws / "projects" / name
        project_dir.mkdir(parents=True)
        lines = ["---", f"project: {name}", "type: feature",
                 f"status: {status}"]
        if skills:
            lines.append("skills:")
            for s in skills:
                lines.append(f"  - name: {s['name']}")
                lines.append(f"    source: {s['source']}")
        lines += ["---", "", f"# {name}", ""]
        (project_dir / "CLAUDE.md").write_text("\n".join(lines))
        return project_dir

    def ws_entry(self, name: str) -> Path:
        return self.ws / ".claude" / "skills" / name

    def link(self, name: str, repo: str) -> dict:
        return run_skills(self.ws, "link", name, repo)


class TestScan(SkillsFixture):

    def test_scan_two_repos_no_conflict(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review", "Vet a change")
        self.make_repo_skill("repo-b", "critique", "critique", "Critique docs")
        out = run_skills(self.ws, "scan", "repo-a", "repo-b")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["errors"], [])
        by_name = {s["name"]: s for s in out["skills"]}
        self.assertEqual(set(by_name), {"vet-review", "critique"})
        self.assertFalse(by_name["vet-review"]["conflict"])
        self.assertEqual(by_name["vet-review"]["repo"], "repo-a")
        self.assertEqual(by_name["vet-review"]["dir"], "vet-review")
        self.assertEqual(
            by_name["vet-review"]["path"],
            str(self.ws / "repos" / "repo-a" / ".claude" / "skills" / "vet-review"),
        )
        self.assertIsNone(by_name["vet-review"]["already_present"])

    def test_scan_name_uses_frontmatter_not_dirname(self):
        self.make_repo_skill("repo-a", "some-dir", "real-name")
        out = run_skills(self.ws, "scan", "repo-a")
        self.assertEqual(out["skills"][0]["name"], "real-name")
        self.assertEqual(out["skills"][0]["dir"], "some-dir")

    def test_scan_conflict_same_name_two_repos(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        self.make_repo_skill("repo-b", "vet-review", "vet-review")
        out = run_skills(self.ws, "scan", "repo-a", "repo-b")
        self.assertEqual(len(out["skills"]), 2)
        self.assertTrue(all(s["conflict"] for s in out["skills"]))

    def test_scan_already_present_same_source(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        self.link("vet-review", "repo-a")
        out = run_skills(self.ws, "scan", "repo-a")
        self.assertEqual(out["skills"][0]["already_present"],
                         {"status": "same_source"})

    def test_scan_already_present_collision_real_dir(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        real = self.ws_entry("vet-review")
        real.mkdir(parents=True)
        out = run_skills(self.ws, "scan", "repo-a")
        ap = out["skills"][0]["already_present"]
        self.assertEqual(ap["status"], "collision")
        self.assertEqual(ap["target"], str(real))

    def test_scan_already_present_collision_foreign_symlink(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        other = self.make_repo_skill("repo-b", "other-skill", "other-skill")
        entry = self.ws_entry("vet-review")
        entry.parent.mkdir(parents=True)
        entry.symlink_to(other)
        out = run_skills(self.ws, "scan", "repo-a")
        ap = out["skills"][0]["already_present"]
        self.assertEqual(ap["status"], "collision")
        self.assertEqual(ap["target"], str(other.resolve()))

    def test_scan_already_present_dangling(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        entry = self.ws_entry("vet-review")
        entry.parent.mkdir(parents=True)
        entry.symlink_to(self.tmp / "gone")
        out = run_skills(self.ws, "scan", "repo-a")
        self.assertEqual(out["skills"][0]["already_present"],
                         {"status": "dangling"})

    def test_scan_repo_without_skills_dir_is_silent(self):
        (self.ws / "repos" / "repo-a").mkdir()
        out = run_skills(self.ws, "scan", "repo-a")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["skills"], [])
        self.assertEqual(out["errors"], [])

    def test_scan_uncloned_repo_reports_error(self):
        out = run_skills(self.ws, "scan", "no-such-repo")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["skills"], [])
        self.assertEqual(len(out["errors"]), 1)
        self.assertIn("no-such-repo", out["errors"][0])

    def test_scan_skill_without_name_reports_error(self):
        skill_dir = self.ws / "repos" / "repo-a" / ".claude" / "skills" / "anon"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\ndescription: nameless\n---\n")
        out = run_skills(self.ws, "scan", "repo-a")
        self.assertEqual(out["skills"], [])
        self.assertEqual(len(out["errors"]), 1)
        self.assertIn("anon", out["errors"][0])

    def test_scan_no_args_is_error(self):
        out = run_skills(self.ws, "scan")
        self.assertEqual(out["status"], "error")


class TestWorkspaceResolution(unittest.TestCase):

    def test_unresolvable_workspace_is_json_error(self):
        empty = Path(tempfile.mkdtemp(prefix="skills-nows-"))
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        env = {k: v for k, v in os.environ.items()
               if k not in ("WORKSPACE_ROOT", "CLAUDE_PROJECT_DIR")}
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "scan", "repo-a"],
            capture_output=True, text=True, cwd=str(empty), env=env,
        )
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)
        self.assertEqual(out["status"], "error")
        self.assertIn("workspace", out["error"].lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_skills.py`
Expected: every test ERRORs (the `run_skills` assertion fails — `scripts/skills.py` does not exist, so the subprocess exits 2).

- [ ] **Step 3: Implement the skeleton and `scan`**

Create `scripts/skills.py`:

```python
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
    except OSError:
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
    else:
        fail(f"Unknown subcommand: {command}")
        return  # unreachable; keeps type-checkers happy

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
```

Note for the collision `target` value: for a real (non-symlink) directory, `entry.resolve()` returns the entry's own absolute path; for a foreign symlink it returns the resolved target — both are what the tests assert.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_skills.py`
Expected: all `TestScan` and `TestWorkspaceResolution` tests PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/skills.py tests/test_skills.py
git commit -m "Add skills.py with scan subcommand for repo skill discovery"
```

---

### Task 2: `link` subcommand

**Files:**
- Modify: `scripts/skills.py` (add `cmd_link`, dispatch)
- Modify: `tests/test_skills.py` (add `TestLink`)

**Interfaces:**
- Consumes: `find_skill_dir`, `classify_existing`, `ws_skills_dir`, `fail` from Task 1.
- Produces: `cmd_link(root: Path, name: str, repo: str) -> dict`; CLI `skills.py link <name> <repo>`. Success output:
  `{"status": "ok", "linked": {"name", "repo", "path", "target"}, "existed": bool, "created_dir": bool}` where `path` is the absolute entry path and `target` the relative symlink text.

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_skills.py` (before the `if __name__ == "__main__":` block):

```python
class TestLink(SkillsFixture):

    def test_link_creates_relative_symlink_named_after_frontmatter(self):
        skill = self.make_repo_skill("repo-a", "some-dir", "real-name")
        out = self.link("real-name", "repo-a")
        self.assertEqual(out["status"], "ok")
        self.assertFalse(out["existed"])
        entry = self.ws_entry("real-name")
        self.assertTrue(entry.is_symlink())
        self.assertFalse(os.readlink(entry).startswith("/"))
        self.assertEqual(entry.resolve(), skill.resolve())
        self.assertEqual(out["linked"]["path"], str(entry))
        self.assertEqual(out["linked"]["target"], os.readlink(entry))

    def test_link_is_idempotent(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        self.link("vet-review", "repo-a")
        out = self.link("vet-review", "repo-a")
        self.assertEqual(out["status"], "ok")
        self.assertTrue(out["existed"])

    def test_link_reports_created_dir(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        self.assertFalse((self.ws / ".claude" / "skills").exists())
        first = self.link("vet-review", "repo-a")
        self.assertTrue(first["created_dir"])
        self.make_repo_skill("repo-a", "critique", "critique")
        second = self.link("critique", "repo-a")
        self.assertFalse(second["created_dir"])

    def test_link_refuses_real_directory(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        self.ws_entry("vet-review").mkdir(parents=True)
        out = self.link("vet-review", "repo-a")
        self.assertEqual(out["status"], "error")
        self.assertTrue(self.ws_entry("vet-review").is_dir())

    def test_link_refuses_foreign_symlink(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        other = self.make_repo_skill("repo-b", "other-skill", "other-skill")
        entry = self.ws_entry("vet-review")
        entry.parent.mkdir(parents=True)
        entry.symlink_to(other)
        out = self.link("vet-review", "repo-a")
        self.assertEqual(out["status"], "error")
        self.assertEqual(entry.resolve(), other.resolve())

    def test_link_replaces_dangling_symlink(self):
        skill = self.make_repo_skill("repo-a", "vet-review", "vet-review")
        entry = self.ws_entry("vet-review")
        entry.parent.mkdir(parents=True)
        entry.symlink_to(self.tmp / "gone")
        out = self.link("vet-review", "repo-a")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(entry.resolve(), skill.resolve())

    def test_link_unknown_skill_name_is_error(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        out = self.link("nope", "repo-a")
        self.assertEqual(out["status"], "error")
        self.assertIn("nope", out["error"])
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python3 tests/test_skills.py`
Expected: all `TestLink` tests FAIL (`status` is `"error"` — "Unknown subcommand: link"); Task 1 tests still PASS.

- [ ] **Step 3: Implement `cmd_link`**

Add to `scripts/skills.py` after `cmd_scan`:

```python
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
```

In `main()`, extend the dispatch:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_skills.py`
Expected: all tests PASS (19 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/skills.py tests/test_skills.py
git commit -m "Add skills.py link subcommand"
```

---

### Task 3: `verify` subcommand

**Files:**
- Modify: `scripts/skills.py` (add `read_project_skills`, `cmd_verify`, dispatch)
- Modify: `tests/test_skills.py` (add `TestVerify`)

**Interfaces:**
- Consumes: `parse_frontmatter`, `find_skill_dir`, `ws_skills_dir` from Task 1; `link` CLI from Task 2 (in tests).
- Produces:
  - `read_project_skills(root: Path, project: str) -> list[dict]` — normalized `[{name, source}]` from project frontmatter; calls `fail()` if the project has no CLAUDE.md. Reused by Task 4.
  - `cmd_verify(root: Path, project: str) -> dict`; CLI `skills.py verify <project>`. Output: `{"status": "ok", "skills": [{"name", "source", "state", "detail"?}]}` with `state` ∈ `ok | missing | broken | source_gone`; `detail: "points_elsewhere"` only on non-repairable `broken`.

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_skills.py`:

```python
class TestVerify(SkillsFixture):

    def verify_one(self, project: str) -> dict:
        out = run_skills(self.ws, "verify", project)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(len(out["skills"]), 1)
        return out["skills"][0]

    def test_verify_ok(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        self.link("vet-review", "repo-a")
        self.make_project("proj", skills=[
            {"name": "vet-review", "source": "repo-a"}])
        entry = self.verify_one("proj")
        self.assertEqual(entry["state"], "ok")
        self.assertEqual(entry["source"], "repo-a")

    def test_verify_missing(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        self.make_project("proj", skills=[
            {"name": "vet-review", "source": "repo-a"}])
        self.assertEqual(self.verify_one("proj")["state"], "missing")

    def test_verify_broken_dangling(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        self.link("vet-review", "repo-a")
        shutil.rmtree(self.ws / "repos" / "repo-a" / ".claude" / "skills"
                      / "vet-review")
        self.make_repo_skill("repo-a", "vet-review-2", "vet-review")
        self.make_project("proj", skills=[
            {"name": "vet-review", "source": "repo-a"}])
        entry = self.verify_one("proj")
        self.assertEqual(entry["state"], "broken")
        self.assertNotIn("detail", entry)

    def test_verify_broken_points_elsewhere(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        other = self.make_repo_skill("repo-b", "other-skill", "other-skill")
        entry_path = self.ws_entry("vet-review")
        entry_path.parent.mkdir(parents=True)
        entry_path.symlink_to(other)
        self.make_project("proj", skills=[
            {"name": "vet-review", "source": "repo-a"}])
        entry = self.verify_one("proj")
        self.assertEqual(entry["state"], "broken")
        self.assertEqual(entry["detail"], "points_elsewhere")

    def test_verify_real_dir_is_points_elsewhere(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        self.ws_entry("vet-review").mkdir(parents=True)
        self.make_project("proj", skills=[
            {"name": "vet-review", "source": "repo-a"}])
        entry = self.verify_one("proj")
        self.assertEqual(entry["state"], "broken")
        self.assertEqual(entry["detail"], "points_elsewhere")

    def test_verify_source_gone(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        self.link("vet-review", "repo-a")
        shutil.rmtree(self.ws / "repos" / "repo-a" / ".claude" / "skills"
                      / "vet-review")
        self.make_project("proj", skills=[
            {"name": "vet-review", "source": "repo-a"}])
        self.assertEqual(self.verify_one("proj")["state"], "source_gone")

    def test_verify_project_without_skills(self):
        self.make_project("proj")
        out = run_skills(self.ws, "verify", "proj")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["skills"], [])

    def test_verify_unknown_project_is_error(self):
        out = run_skills(self.ws, "verify", "nope")
        self.assertEqual(out["status"], "error")
```

Note `test_verify_broken_dangling`: after deleting the linked dir, `vet-review-2/` still provides frontmatter name `vet-review`, so the source exists (`source_gone` doesn't apply) while the old symlink dangles → plain repairable `broken`. In `test_verify_source_gone` nothing re-provides the name.

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python3 tests/test_skills.py`
Expected: all `TestVerify` tests FAIL ("Unknown subcommand: verify"); previous tests PASS.

- [ ] **Step 3: Implement `cmd_verify`**

Add to `scripts/skills.py`:

```python
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
```

Extend the dispatch in `main()`:

```python
    elif command == "verify":
        if len(rest) != 1:
            fail("Usage: skills.py verify <project>")
        result = cmd_verify(root, rest[0])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_skills.py`
Expected: all tests PASS (27 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/skills.py tests/test_skills.py
git commit -m "Add skills.py verify subcommand"
```

---

### Task 4: `unlink-check` subcommand

**Files:**
- Modify: `scripts/skills.py` (add `cmd_unlink_check`, dispatch)
- Modify: `tests/test_skills.py` (add `TestUnlinkCheck`)

**Interfaces:**
- Consumes: `read_project_skills`, `parse_frontmatter`, `ws_skills_dir` from earlier tasks.
- Produces: `cmd_unlink_check(root: Path, project: str) -> dict`; CLI `skills.py unlink-check <project>`. Output:
  `{"status": "ok", "skills": [{"name", "source", "missing": bool, "is_symlink": bool, "removable": bool, "used_by": [str]}]}`.
  `removable` ⇔ entry exists ∧ is a symlink ∧ `used_by` empty. `used_by` = other projects with frontmatter `status` ≠ `done` referencing the same skill `name`.

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_skills.py`:

```python
class TestUnlinkCheck(SkillsFixture):

    def check_one(self, project: str) -> dict:
        out = run_skills(self.ws, "unlink-check", project)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(len(out["skills"]), 1)
        return out["skills"][0]

    def _linked_project(self, project: str = "closing") -> None:
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        self.link("vet-review", "repo-a")
        self.make_project(project, skills=[
            {"name": "vet-review", "source": "repo-a"}])

    def test_exclusive_skill_is_removable(self):
        self._linked_project()
        entry = self.check_one("closing")
        self.assertTrue(entry["removable"])
        self.assertTrue(entry["is_symlink"])
        self.assertFalse(entry["missing"])
        self.assertEqual(entry["used_by"], [])

    def test_shared_with_active_project_is_kept(self):
        self._linked_project()
        self.make_project("other", status="active", skills=[
            {"name": "vet-review", "source": "repo-a"}])
        entry = self.check_one("closing")
        self.assertFalse(entry["removable"])
        self.assertEqual(entry["used_by"], ["other"])

    def test_shared_only_with_done_project_is_removable(self):
        self._linked_project()
        self.make_project("finished", status="done", skills=[
            {"name": "vet-review", "source": "repo-a"}])
        entry = self.check_one("closing")
        self.assertTrue(entry["removable"])
        self.assertEqual(entry["used_by"], [])

    def test_real_dir_is_not_removable(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        self.ws_entry("vet-review").parent.mkdir(parents=True, exist_ok=True)
        self.ws_entry("vet-review").mkdir()
        self.make_project("closing", skills=[
            {"name": "vet-review", "source": "repo-a"}])
        entry = self.check_one("closing")
        self.assertFalse(entry["removable"])
        self.assertFalse(entry["is_symlink"])

    def test_absent_entry_is_missing_not_removable(self):
        self.make_project("closing", skills=[
            {"name": "vet-review", "source": "repo-a"}])
        entry = self.check_one("closing")
        self.assertTrue(entry["missing"])
        self.assertFalse(entry["removable"])
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python3 tests/test_skills.py`
Expected: all `TestUnlinkCheck` tests FAIL ("Unknown subcommand: unlink-check"); previous tests PASS.

- [ ] **Step 3: Implement `cmd_unlink_check`**

Add to `scripts/skills.py`:

```python
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
```

Extend the dispatch in `main()`:

```python
    elif command == "unlink-check":
        if len(rest) != 1:
            fail("Usage: skills.py unlink-check <project>")
        result = cmd_unlink_check(root, rest[0])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_skills.py`
Expected: all tests PASS (32 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/skills.py tests/test_skills.py
git commit -m "Add skills.py unlink-check subcommand"
```

---

### Task 5: `setup.sh` creates `$WS/.claude/skills/`

**Files:**
- Modify: `scripts/setup.sh` (function `apply_settings_template` ~line 696, and `main()`'s `clone` case ~line 907)
- Modify: `tests/test_setup.sh` (add assertions to the existing init group)

**Interfaces:**
- Consumes: `WORKSPACE_ROOT_RESOLVED` (set by `resolve_workspace_root`), `log_success` (existing setup.sh helpers).
- Produces: new bash function `ensure_skills_dir` (no args, uses `WORKSPACE_ROOT_RESOLVED`), called from the `init` and `clone` paths. This is the watcher precondition: `.claude/skills/` must exist at session start for live symlink pickup.

- [ ] **Step 1: Add failing test assertions**

In `tests/test_setup.sh`, two exact anchors:

1. Init group: directly after the line
   `assert_not_contains "settings template has no hooks block"   "$ws/.claude/settings.local.json" "SessionStart"`
   add:

```bash
assert_dir       ".claude/skills dir created by init"        "$ws/.claude/skills"
```

2. Clone group (`# ── 8. Active-domain scoping in clone_repo`): this group builds a bare workspace via `new_workspace` (init never runs), writes `dev-env.yaml` by hand, and runs `run_setup "$PLUGIN" "$ws" clone`. Directly after the line
   `assert_not_contains "context is NOT from BETA"            "$ws/repos/sharedrepo/DOMAIN-CONTEXT.md" "BETA"`
   add:

```bash
assert_dir       ".claude/skills dir created by clone"       "$ws/.claude/skills"
```

- [ ] **Step 2: Run the suite to verify the new assertions fail**

Run: `bash tests/test_setup.sh`
Expected: the two new assertions FAIL (`missing dir: .../.claude/skills`); the pre-existing 50 pass.

- [ ] **Step 3: Implement `ensure_skills_dir`**

In `scripts/setup.sh`, directly after the `apply_settings_template()` function definition, add:

```bash
# Pre-create the workspace's .claude/skills/ so Claude Code's filesystem
# watcher (which only monitors directories that exist at session start)
# picks up skill symlinks live. Used by /workspace:new skill linking.
ensure_skills_dir() {
    local skills_dir="$WORKSPACE_ROOT_RESOLVED/.claude/skills"
    if [[ ! -d "$skills_dir" ]]; then
        mkdir -p "$skills_dir"
        log_success "Created .claude/skills/ (skill symlink dir)"
    fi
}
```

Call it from both entry paths in `main()`'s `case` statement:

```bash
        init)
            resolve_workspace_root create
            init_domain "$target"
            ensure_skills_dir
            ;;
```

```bash
        clone)
            resolve_workspace_root require
            ensure_skills_dir
            detect_repo_source
            if [[ -n "$target" ]]; then
                handle_specific_repo "clone" "$target"
            else
                clone_all
            fi
            ;;
```

(`init_domain` has early `exit 0` paths — e.g. listing domains with no argument — so for `init`, `ensure_skills_dir` only runs on full success; that's fine, `clone` covers the rest.)

- [ ] **Step 4: Run the suite to verify everything passes**

Run: `bash tests/test_setup.sh`
Expected: all assertions pass, including the two new ones (52 total).

- [ ] **Step 5: Commit**

```bash
git add scripts/setup.sh tests/test_setup.sh
git commit -m "Pre-create workspace .claude/skills dir in setup.sh init/clone"
```

---

### Task 6: `/workspace:new` — Step 1g (skill linking)

**Files:**
- Modify: `skills/new/SKILL.md` (insert Step 1g after Step 1f, ~line 157; extend Common Frontmatter ~line 272; extend Step 4 summary ~line 236)

**Interfaces:**
- Consumes: `skills.py scan` / `link` CLI and JSON shapes from Tasks 1-2.
- Produces: the frontmatter `skills:` format consumed by Tasks 7-8:
  ```yaml
  skills:
    - name: vet-review
      source: two-node-toolbox
  ```

- [ ] **Step 1: Insert Step 1g**

In `skills/new/SKILL.md`, immediately before the `## Step 2: Generate Folder Name` heading, insert:

````markdown
**1g. Repo Skill Linking (optional)**

Repos may ship their own Claude Code skills in `.claude/skills/`. Surface
them in workspace autocomplete by symlinking. Skip this step entirely
(silently, no question) if no repos were selected in Step 1d.

1. Run via Bash:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/skills.py" scan <repo1> <repo2> ...
   ```

   with the repos selected in Step 1d. If the output has
   `status: "error"` or an empty `skills` array, skip this step silently
   (mention any `errors` entries briefly, but never block project
   creation).

2. Partition the scanned skills:
   - `already_present.status == "same_source"` → already linked (by
     another project). Do NOT ask about these; record them in the
     `skills:` frontmatter (step 5 below) and mention the reuse in the
     Step 4 summary.
   - `already_present.status == "collision"` → not linkable (the name is
     taken by something else at the workspace root). Exclude, and note
     in the summary: "skill `<name>` skipped — name already in use".
   - `already_present.status == "dangling"` or `null` → offer to link
     (a dangling leftover symlink is replaced automatically).
   - `conflict: true` → same skill name from multiple selected repos;
     handle in step 4 below.

3. If any offerable non-conflicted skills remain, present ONE
   AskUserQuestion with multiSelect=true: label = skill `name`,
   description = "`<description>` (from `<repo>`)". Nothing selected →
   continue without linking.

4. For each conflicted name, ask a separate single-select
   AskUserQuestion: "Skill `<name>` is provided by multiple repos —
   which one should be linked?" with one option per source repo plus
   "Skip this skill". (Only one can own the name: symlinks can't rename
   a skill, so the others stay unlinked.)

5. For each chosen skill, run via Bash:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/skills.py" link <name> <repo>
   ```

   - On `status: "error"`: report it and continue with the remaining
     skills — never abort project creation.
   - If any success output has `created_dir: true`, note for the Step 4
     summary that a session restart is needed before these skills appear
     in autocomplete (the watcher only monitors dirs that existed at
     session start).

6. Record every linked or reused skill for the frontmatter (Step 3b):

   ```yaml
   skills:
     - name: <name>
       source: <repo>
   ```
````

- [ ] **Step 2: Extend the Common Frontmatter template**

In the `### Common Frontmatter` yaml block, after the `# Omit both if no worktrees were created (ci-testing, analysis non-PR)` comment line, add:

```yaml
skills:
  - name: <skill-name>
    source: <repo that provides it>
# skills: repo skills linked into $WS/.claude/skills/ (from Step 1g)
# Omit if no skills were linked
```

- [ ] **Step 3: Extend the Step 4 summary**

In `## Step 4: Suggest Skills and Next Steps`, after item 2 (the worktrees listing), insert a new item (renumber the following items):

```markdown
3. If skills were linked in Step 1g, list them:
   > **Skills linked:**
   > - `/<name>` (from `<repo>`)
   >
   > These are available in autocomplete now — no restart needed.

   If `link` reported `created_dir: true`, say instead: "Restart the
   session to pick up the new skills (the `.claude/skills/` directory
   was just created)."
```

- [ ] **Step 4: Validate**

Run: `claude plugin validate . --strict`
Expected: passes.

Re-read the modified sections and check: Step 1g sits between 1f and Step 2; numbering in Step 4's list is sequential; the frontmatter block is valid YAML.

- [ ] **Step 5: Commit**

```bash
git add skills/new/SKILL.md
git commit -m "Link repo skills into the workspace during /workspace:new"
```

---

### Task 7: `/workspace:resume` — verify and repair skill links

**Files:**
- Modify: `skills/resume/SKILL.md` (insert into `## Step 3: Present Summary`, after the worktree-status block that ends "instead of the main checkout." ~line 88)

**Interfaces:**
- Consumes: `skills.py verify` / `link` CLI and JSON from Tasks 2-3; frontmatter `skills:` format from Task 6.

- [ ] **Step 1: Insert the skill verification block**

In `skills/resume/SKILL.md`, in `## Step 3: Present Summary`, after the paragraph ending `instead of the main checkout."` and before `**If P.has_reference_files:**`, insert:

````markdown
**If `P.frontmatter.skills` is non-empty:**
Verify the project's linked skills:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/skills.py" verify <P.name>
```

If the output has `status: "error"`, mention it briefly and move on.
Otherwise act per skill `state`:

- `ok` → nothing; say nothing when all skills are `ok`.
- `missing` or `broken` WITHOUT `detail` → repair automatically:
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/skills.py" link <name> <source>`
  then report: "Relinked skill `<name>` (from `<source>`)."
- `broken` with `detail: "points_elsewhere"` → do NOT touch the entry
  (another project or the user owns that name now). Warn: "Skill
  `<name>` no longer points at `<source>` — leaving it alone."
- `source_gone` → the skill no longer exists in the source repo. Warn,
  and ask (AskUserQuestion) whether to remove the entry from this
  project's `skills:` frontmatter (Edit tool) or keep it for reference.

Repairs never block the resume flow — report and continue.
````

- [ ] **Step 2: Validate**

Run: `claude plugin validate . --strict`
Expected: passes.

Re-read the section: the inserted block must not break the existing `**If ... :**` pattern of Step 3, and the fenced bash block inside the markdown quote renders correctly (keep it at the same indent level as the surrounding text, matching how Step 3 already embeds code spans).

- [ ] **Step 3: Commit**

```bash
git add skills/resume/SKILL.md
git commit -m "Verify and repair skill symlinks on /workspace:resume"
```

---

### Task 8: `/workspace:close` — refcounted skill unlinking

**Files:**
- Modify: `skills/close/SKILL.md` (retitle Step 2.5 ~line 60; add substep 2.5e after 2.5d ~line 135; extend Step 3b ~line 143)

**Interfaces:**
- Consumes: `skills.py unlink-check` CLI and JSON from Task 4; frontmatter `skills:` format from Task 6.

- [ ] **Step 1: Retitle Step 2.5 and add substep 2.5e**

Change the heading `## Step 2.5: Worktree Cleanup` to
`## Step 2.5: Worktree & Skill Cleanup`.

Also update its opening condition line from:

```markdown
If `P.worktree_status` (from Step 1's resume-project.py output) is
non-empty:
```

to:

```markdown
Substeps 2.5a-2.5d apply if `P.worktree_status` (from Step 1's
resume-project.py output) is non-empty; substep 2.5e applies if
`P.frontmatter.skills` is non-empty. If neither, skip to Step 3.
```

After substep **2.5d** (which ends with the "Worktrees preserved" note), add:

````markdown
**2.5e. Remove skill symlinks**

If `P.frontmatter.skills` is non-empty, check which linked skills are
still needed by other active projects:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/skills.py" unlink-check <P.name>
```

If the output has `status: "error"`, mention it and continue to Step 3.
Otherwise, for each entry in `skills`:

- `removable: true` → remove the symlink (plain `rm` — the target is a
  symlink, never use `rm -r`):

  ```bash
  rm "<workspace>/.claude/skills/<name>"
  ```

- `removable: false` with non-empty `used_by` → keep it; report:
  "Skill `<name>` kept — still used by `<used_by>`."
- `missing: true` → nothing to remove; skip silently.
- `removable: false` with `is_symlink: false` → not ours to delete;
  report: "`.claude/skills/<name>` is not a symlink — left in place."

Skills are unlinked even when the user chose to keep worktrees in 2.5b —
symlinks surface autocomplete entries and have nothing to do with
branches. The `skills:` frontmatter is cleared in Step 3b regardless of
what was removable.
````

- [ ] **Step 2: Extend Step 3b**

In `**3b. Update frontmatter fields**`, after item 3 (the `worktrees: []` item), add:

```markdown
4. If the project had a `skills:` list, change it to `skills: []`
   (the symlinks were handled in Step 2.5e; the cleared list records
   that this project no longer holds any skill references).
```

- [ ] **Step 3: Validate**

Run: `claude plugin validate . --strict`
Expected: passes.

Re-read Step 2.5 top-to-bottom: condition line mentions both worktrees and skills; 2.5e reads correctly after 2.5d; Step 3b numbering is sequential (1-4).

- [ ] **Step 4: Commit**

```bash
git add skills/close/SKILL.md
git commit -m "Remove unreferenced skill symlinks on /workspace:close"
```

---

### Task 9: Full verification pass

**Files:**
- Modify: none expected (fix regressions if any step fails)

- [ ] **Step 1: Run the python suite**

Run: `python3 tests/test_skills.py`
Expected: 32 tests, all PASS.

- [ ] **Step 2: Run the bash suite**

Run: `bash tests/test_setup.sh`
Expected: 52 assertions, 0 failed.

- [ ] **Step 3: Validate the plugin**

Run: `claude plugin validate . --strict`
Expected: passes.

- [ ] **Step 4: End-to-end smoke test of the script against a scratch workspace**

```bash
WS=$(mktemp -d)/ws
mkdir -p "$WS/repos/demo/.claude/skills/hello" "$WS/projects"
printf -- '---\nname: hello\ndescription: Say hello\n---\n' > "$WS/repos/demo/.claude/skills/hello/SKILL.md"
printf -- 'repos: []\n' > "$WS/dev-env.yaml"
export WORKSPACE_ROOT="$WS"
python3 scripts/skills.py scan demo
python3 scripts/skills.py link hello demo
ls -l "$WS/.claude/skills/"
mkdir -p "$WS/projects/p1"
printf -- '---\nproject: p1\nstatus: active\nskills:\n  - name: hello\n    source: demo\n---\n' > "$WS/projects/p1/CLAUDE.md"
python3 scripts/skills.py verify p1
python3 scripts/skills.py unlink-check p1
unset WORKSPACE_ROOT
```

Expected: scan lists `hello`; link creates `.claude/skills/hello -> ../../repos/demo/.claude/skills/hello`; verify reports `state: "ok"`; unlink-check reports `removable: true`.

- [ ] **Step 5: Commit any fixes; otherwise no-op**

If Steps 1-4 required fixes, commit them with messages describing the fix. Then the branch is ready for `superpowers:finishing-a-development-branch`.
