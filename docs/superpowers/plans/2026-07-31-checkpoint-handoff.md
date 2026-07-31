# Checkpoint Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the `update-project` → `/clear` → `resume-project` sequence into `/workspace:checkpoint` → `/clear`, by handing a single-use marker across the clear boundary and having a SessionStart hook resume the project automatically.

**Architecture:** `/workspace:checkpoint` delegates all document writing to the existing `update-project` skill, then writes `<workspace>/.claude/handoff.json`. A new SessionStart hook bound to the `clear` matcher runs `handoff.py read`, which either consumes a fresh marker and emits a resume directive as `additionalContext`, or hands off to `recent-projects.py` so a normal `/clear` behaves exactly as it does today.

**Tech Stack:** python3.9+ (stdlib only), bash, Claude Code plugin skills and hooks.

Spec: `docs/superpowers/specs/2026-07-31-checkpoint-handoff-design.md`

## Global Constraints

- Python targets **python3.9+** (macOS system python). Every new `.py` file starts with `from __future__ import annotations` so `X | None` hints work there.
- `scripts/handoff.py` is **yaml-free**. Permitted imports: `argparse`, `json`, `os`, `sys`, `datetime`, `pathlib`, `workspace_lib`. Plugins cannot declare python dependencies and this script runs from a SessionStart hook.
- **Hook scripts always exit 0.** A non-zero exit or traceback from `handoff.py read` degrades a session start. Errors are reported as JSON on stdout with `"status": "error"`, never as exceptions.
- **Never derive the workspace root from `__file__`.** Use `workspace_lib.resolve_workspace_root()`, which returns `None` when it cannot be determined.
- Skills reference plugin files as `"${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py"`.
- Marker path is exactly `<workspace_root>/.claude/handoff.json`. `handoff.py write` and `handoff.py read` must resolve it through the same helper — a divergence makes the handoff silently never fire.
- Marker TTL is **3600 seconds**. Marker schema version is **1**.
- Branch: `checkpoint-handoff` (already created off `origin/main`). Per the repo's fork model, push to the personal fork and open a PR to `fonta-rh/multi-repo-dev-env`.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `scripts/handoff.py` | **new** — owns the marker: writing it, and consuming it at session start. Two subcommands, one shared path helper. |
| `tests/test_handoff.py` | **new** — subprocess-driven tests against throwaway workspaces, mirroring `tests/test_skills.py`. |
| `hooks/hooks.json` | **modify** — split SessionStart into two matcher-scoped entries. |
| `skills/checkpoint/SKILL.md` | **new** — thin orchestration; delegates document writing to `update-project`. |
| `skills/resume-project/SKILL.md` | **modify** — one branch at the top of Step 4. |
| `CLAUDE.md`, `README.md` | **modify** — skill tables, layout, conventions. |

Task 1 builds `write`, Tasks 2 and 3 build `read` (happy path, then degradation). Tasks 4–6 wire it into the harness. Task 7 documents it.

---

### Task 1: Marker writing

**Files:**
- Create: `scripts/handoff.py`
- Create: `tests/test_handoff.py`

**Interfaces:**
- Consumes: `workspace_lib.resolve_workspace_root() -> Path | None`
- Produces:
  - `marker_path(root: Path) -> Path` — returns `root / ".claude" / "handoff.json"`
  - `MARKER_VERSION: int = 1`, `TTL_SECONDS: int = 3600`
  - CLI: `handoff.py write --project NAME --next-task TEXT [--load-files a.md,b.md]`, printing `{"status":"ok","path":...}` or `{"status":"error","message":...}`, always exit 0

- [ ] **Step 1: Write the failing tests**

Create `tests/test_handoff.py`:

```python
#!/usr/bin/env python3
"""Tests for scripts/handoff.py.

Standalone: python3 tests/test_handoff.py
Requires no third-party modules (nor does the script under test).

Each test builds a throwaway workspace (dev-env.yaml + projects/) in a temp
dir and drives handoff.py as a subprocess with WORKSPACE_ROOT set, mirroring
how tests/test_skills.py isolates skills.py.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "handoff.py"
RECENT = Path(__file__).resolve().parent.parent / "scripts" / "recent-projects.py"


def run_handoff(ws: Path, *args: str) -> subprocess.CompletedProcess:
    """Run handoff.py against workspace ws; assert exit 0; return the result."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True,
        env={**os.environ, "WORKSPACE_ROOT": str(ws)},
    )
    assert result.returncode == 0, (
        f"handoff.py exited {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return result


def run_recent(ws: Path) -> subprocess.CompletedProcess:
    """Run recent-projects.py directly, for passthrough comparisons."""
    return subprocess.run(
        [sys.executable, str(RECENT)],
        capture_output=True, text=True,
        env={**os.environ, "WORKSPACE_ROOT": str(ws)},
    )


def iso(offset_minutes: int = 0) -> str:
    """A local-timezone ISO timestamp, offset from now."""
    stamp = datetime.now().astimezone() + timedelta(minutes=offset_minutes)
    return stamp.isoformat(timespec="seconds")


class HandoffFixture(unittest.TestCase):
    """Temp workspace with helpers to plant projects and markers."""

    def setUp(self):
        # resolve(): on macOS mkdtemp returns /var/... which is a symlink to
        # /private/var/... — path-equality assertions need the real path.
        self.tmp = Path(tempfile.mkdtemp(prefix="handoff-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ws = self.tmp / "ws"
        (self.ws / "projects").mkdir(parents=True)
        (self.ws / "dev-env.yaml").write_text("repos: []\n")

    def make_project(self, name: str, status: str = "active") -> Path:
        """Create projects/<name>/CLAUDE.md with frontmatter; return the dir."""
        project_dir = self.ws / "projects" / name
        project_dir.mkdir(parents=True)
        (project_dir / "CLAUDE.md").write_text(
            f"---\nproject: {name}\ntype: bug\nstatus: {status}\n---\n\n# {name}\n"
        )
        return project_dir

    def marker(self) -> Path:
        return self.ws / ".claude" / "handoff.json"

    def write_marker(self, **overrides) -> Path:
        """Plant a marker file directly, bypassing the write subcommand."""
        payload = {
            "version": 1,
            "project": "demo",
            "written_at": iso(),
            "next_task": "reproduce with restic disabled",
            "load_files": ["investigation.md"],
        }
        payload.update(overrides)
        path = self.marker()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
        return path


class TestWrite(HandoffFixture):

    def test_write_creates_marker(self):
        self.make_project("demo")
        out = json.loads(run_handoff(
            self.ws, "write",
            "--project", "demo",
            "--next-task", "reproduce with restic disabled",
            "--load-files", "investigation.md,test-results.md",
        ).stdout)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["path"], str(self.marker()))

        data = json.loads(self.marker().read_text())
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["project"], "demo")
        self.assertEqual(data["next_task"], "reproduce with restic disabled")
        self.assertEqual(data["load_files"],
                         ["investigation.md", "test-results.md"])
        self.assertTrue(data["written_at"])

    def test_write_unknown_project_errors_and_writes_nothing(self):
        out = json.loads(run_handoff(
            self.ws, "write", "--project", "nope", "--next-task", "x").stdout)
        self.assertEqual(out["status"], "error")
        self.assertIn("nope", out["message"])
        self.assertFalse(self.marker().exists())

    def test_write_without_load_files_yields_empty_list(self):
        self.make_project("demo")
        run_handoff(self.ws, "write", "--project", "demo", "--next-task", "x")
        data = json.loads(self.marker().read_text())
        self.assertEqual(data["load_files"], [])

    def test_write_strips_whitespace_in_load_files(self):
        self.make_project("demo")
        run_handoff(self.ws, "write", "--project", "demo", "--next-task", "x",
                    "--load-files", " a.md , b.md ")
        data = json.loads(self.marker().read_text())
        self.assertEqual(data["load_files"], ["a.md", "b.md"])

    def test_write_overwrites_an_existing_marker(self):
        self.make_project("demo")
        self.write_marker(project="demo", next_task="stale task")
        run_handoff(self.ws, "write", "--project", "demo",
                    "--next-task", "fresh task")
        data = json.loads(self.marker().read_text())
        self.assertEqual(data["next_task"], "fresh task")


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_handoff.py`
Expected: every `TestWrite` test errors, because `scripts/handoff.py` does not exist — the subprocess exits non-zero and the assertion in `run_handoff` fires with `can't open file .../scripts/handoff.py`.

- [ ] **Step 3: Write the minimal implementation**

Create `scripts/handoff.py`:

```python
#!/usr/bin/env python3
"""Arm and consume the checkpoint handoff marker.

`/workspace:checkpoint` writes a marker after updating a project's docs; the
SessionStart hook bound to the `clear` matcher consumes it and tells Claude to
resume that project. The marker is the only state that crosses a /clear.

Deliberately yaml-free: `read` runs on every /clear and plugins cannot declare
python dependencies, so this must never import a third-party module.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import workspace_lib

MARKER_VERSION = 1
TTL_SECONDS = 3600


def marker_path(root: Path) -> Path:
    """The single source of truth for where the marker lives.

    Both subcommands go through this. A divergence here would make the
    handoff silently never fire.
    """
    return root / ".claude" / "handoff.json"


def emit(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


def cmd_write(args: argparse.Namespace) -> int:
    root = workspace_lib.resolve_workspace_root()
    if root is None:
        emit({
            "status": "error",
            "message": "Could not determine the workspace root. Set WORKSPACE_ROOT "
                       "or run inside a workspace (a directory containing dev-env.yaml).",
        })
        return 0

    project_dir = root / "projects" / args.project
    if not project_dir.is_dir():
        emit({
            "status": "error",
            "message": f"No such project: {args.project} (expected {project_dir})",
        })
        return 0

    load_files = [f.strip() for f in (args.load_files or "").split(",") if f.strip()]

    payload = {
        "version": MARKER_VERSION,
        "project": args.project,
        "written_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "next_task": args.next_task,
        "load_files": load_files,
    }

    path = marker_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n")
    except OSError as exc:
        emit({"status": "error", "message": f"Could not write {path}: {exc}"})
        return 0

    emit({"status": "ok", "path": str(path)})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    write = sub.add_parser("write", help="Arm a handoff for the next /clear")
    write.add_argument("--project", required=True)
    write.add_argument("--next-task", required=True)
    write.add_argument("--load-files", default="",
                       help="Comma-separated detail files, relative to the project dir")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "write":
        return cmd_write(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_handoff.py`
Expected: PASS, 5 tests in `TestWrite`.

- [ ] **Step 5: Commit**

```bash
git add scripts/handoff.py tests/test_handoff.py
git commit -m "Add handoff.py marker writing for checkpoint handoff"
```

---

### Task 2: Consuming a fresh marker

**Files:**
- Modify: `scripts/handoff.py`
- Modify: `tests/test_handoff.py`

**Interfaces:**
- Consumes: `marker_path()`, `MARKER_VERSION`, `TTL_SECONDS` from Task 1
- Produces:
  - `load_marker(path: Path) -> dict | None` — returns the marker dict with an added `_age_seconds: float` key, or `None` if absent/invalid/stale. **Always deletes the file when it existed**, so consumption is single-use.
  - `humanize_age(seconds: float) -> str`
  - `build_directive(marker: dict) -> str`
  - CLI: `handoff.py read` printing a SessionStart payload when a fresh marker is found

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_handoff.py`, before the `if __name__ == "__main__":` block:

```python
class TestReadFresh(HandoffFixture):

    def test_fresh_marker_emits_directive(self):
        self.make_project("demo")
        self.write_marker(project="demo")
        out = json.loads(run_handoff(self.ws, "read").stdout)

        hook_out = out["hookSpecificOutput"]
        self.assertEqual(hook_out["hookEventName"], "SessionStart")
        ctx = hook_out["additionalContext"]
        self.assertIn("Checkpoint handoff pending", ctx)
        self.assertIn("demo", ctx)
        self.assertIn("reproduce with restic disabled", ctx)
        self.assertIn("investigation.md", ctx)
        self.assertIn("workspace:resume-project", ctx)
        self.assertIn("demo", out["systemMessage"])

    def test_fresh_marker_is_consumed(self):
        self.make_project("demo")
        self.write_marker(project="demo")
        run_handoff(self.ws, "read")
        self.assertFalse(self.marker().exists())

    def test_second_read_does_not_refire(self):
        self.make_project("demo")
        self.write_marker(project="demo")
        run_handoff(self.ws, "read")
        second = run_handoff(self.ws, "read").stdout
        self.assertNotIn("Checkpoint handoff pending", second)

    def test_future_timestamp_is_treated_as_fresh(self):
        self.make_project("demo")
        self.write_marker(project="demo", written_at=iso(5))
        out = run_handoff(self.ws, "read").stdout
        self.assertIn("Checkpoint handoff pending", out)

    def test_empty_load_files_renders_placeholder(self):
        self.make_project("demo")
        self.write_marker(project="demo", load_files=[])
        out = json.loads(run_handoff(self.ws, "read").stdout)
        self.assertIn("none recorded",
                      out["hookSpecificOutput"]["additionalContext"])

    def test_write_then_read_round_trip(self):
        self.make_project("demo")
        run_handoff(self.ws, "write", "--project", "demo",
                    "--next-task", "check velero CSI logs",
                    "--load-files", "investigation.md")
        out = json.loads(run_handoff(self.ws, "read").stdout)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("check velero CSI logs", ctx)
        self.assertIn("investigation.md", ctx)
        self.assertFalse(self.marker().exists())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_handoff.py -k TestReadFresh`
Expected: FAIL — `argparse` rejects `read` with `invalid choice: 'read'`, so the subprocess exits 2 and the assertion in `run_handoff` fires.

- [ ] **Step 3: Write the minimal implementation**

In `scripts/handoff.py`, add `timezone` to the datetime import:

```python
from datetime import datetime, timezone
```

Add these functions after `emit()`:

```python
def unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def parse_timestamp(raw: object) -> datetime | None:
    """Parse an ISO timestamp into an aware UTC datetime, or None."""
    if not isinstance(raw, str):
        return None
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.astimezone()
    return stamp.astimezone(timezone.utc)


def load_marker(path: Path) -> dict | None:
    """Consume the marker: return it if fresh and valid, else None.

    The file is deleted whenever it existed, whatever its state. Consumption
    is single-use by construction, so a repeated /clear cannot re-fire.
    Never raises: a bad marker must not disturb a session start.
    """
    if not path.is_file():
        return None
    try:
        raw = path.read_text()
    except OSError:
        unlink_quietly(path)
        return None

    unlink_quietly(path)

    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("version") != MARKER_VERSION:
        return None
    if not data.get("project") or not data.get("next_task"):
        return None

    written = parse_timestamp(data.get("written_at"))
    if written is None:
        return None

    age = (datetime.now(timezone.utc) - written).total_seconds()
    if age > TTL_SECONDS:
        return None

    # A negative age means clock skew, not a marker from the future.
    data["_age_seconds"] = max(age, 0.0)
    if not isinstance(data.get("load_files"), list):
        data["load_files"] = []
    return data


def humanize_age(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "just now"
    if minutes == 1:
        return "1 minute ago"
    if minutes < 60:
        return f"{minutes} minutes ago"
    hours = minutes // 60
    return "1 hour ago" if hours == 1 else f"{hours} hours ago"


def build_directive(marker: dict) -> str:
    files = ", ".join(marker["load_files"]) or "none recorded"
    return (
        f"Checkpoint handoff pending (saved {humanize_age(marker['_age_seconds'])}).\n\n"
        f"Project: {marker['project']}\n"
        f"Next task: {marker['next_task']}\n"
        f"Detail files: {files}\n\n"
        f"Invoke the workspace:resume-project skill with argument\n"
        f"`{marker['project']}`. In Step 4, skip the task menu: read the detail\n"
        f"files listed above and report readiness with the next task."
    )


def cmd_read(args: argparse.Namespace) -> int:
    root = workspace_lib.resolve_workspace_root()
    if root is None:
        return 0

    marker = load_marker(marker_path(root))
    if marker is None:
        return 0

    emit({
        "systemMessage": (
            f"Resuming {marker['project']} from checkpoint "
            f"({humanize_age(marker['_age_seconds'])})."
        ),
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": build_directive(marker),
        },
    })
    return 0
```

Register the subcommand in `build_parser()`, before `return parser`:

```python
    sub.add_parser("read", help="Consume a handoff at session start (hook mode)")
```

Dispatch it in `main()`:

```python
def main() -> int:
    args = build_parser().parse_args()
    if args.command == "write":
        return cmd_write(args)
    if args.command == "read":
        return cmd_read(args)
    return 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_handoff.py`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/handoff.py tests/test_handoff.py
git commit -m "Consume fresh handoff markers in handoff.py read"
```

---

### Task 3: Degradation and passthrough

A `/clear` with no armed handoff must behave exactly as it does today, which means falling through to `recent-projects.py`. `os.execv` replaces the process, so its stdout becomes ours with no duplication of the banner rendering.

**Files:**
- Modify: `scripts/handoff.py`
- Modify: `tests/test_handoff.py`

**Interfaces:**
- Consumes: `load_marker()`, `cmd_read()` from Task 2
- Produces: `passthrough() -> None` — `os.execv`s into `recent-projects.py`; returns only if the exec fails

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_handoff.py`, before the `if __name__ == "__main__":` block:

```python
class TestReadDegradation(HandoffFixture):

    def test_absent_marker_matches_recent_projects_exactly(self):
        self.make_project("demo")
        got = run_handoff(self.ws, "read").stdout
        self.assertEqual(got, run_recent(self.ws).stdout)
        self.assertIn("Recent projects", got)

    def test_stale_marker_passes_through_and_is_deleted(self):
        self.make_project("demo")
        self.write_marker(project="demo", written_at=iso(-61))
        got = run_handoff(self.ws, "read").stdout
        self.assertNotIn("Checkpoint handoff pending", got)
        self.assertEqual(got, run_recent(self.ws).stdout)
        self.assertFalse(self.marker().exists())

    def test_corrupt_marker_passes_through_and_is_deleted(self):
        self.make_project("demo")
        path = self.marker()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json")
        got = run_handoff(self.ws, "read").stdout
        self.assertEqual(got, run_recent(self.ws).stdout)
        self.assertFalse(path.exists())

    def test_wrong_version_passes_through_and_is_deleted(self):
        self.make_project("demo")
        self.write_marker(project="demo", version=99)
        got = run_handoff(self.ws, "read").stdout
        self.assertNotIn("Checkpoint handoff pending", got)
        self.assertFalse(self.marker().exists())

    def test_missing_next_task_passes_through(self):
        self.make_project("demo")
        self.write_marker(project="demo", next_task="")
        got = run_handoff(self.ws, "read").stdout
        self.assertNotIn("Checkpoint handoff pending", got)
        self.assertFalse(self.marker().exists())

    def test_no_projects_dir_is_silent(self):
        # recent-projects.py exits 0 with no output when there is nothing to
        # show; the passthrough must preserve that.
        shutil.rmtree(self.ws / "projects")
        self.assertEqual(run_handoff(self.ws, "read").stdout, "")

    def test_no_workspace_root_is_silent(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("WORKSPACE_ROOT", "CLAUDE_PROJECT_DIR")}
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "read"],
            capture_output=True, text=True, cwd=str(self.tmp), env=env,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_handoff.py -k TestReadDegradation`
Expected: FAIL — `test_absent_marker_matches_recent_projects_exactly`, `test_stale_...`, `test_corrupt_...` compare `""` against the banner, because `cmd_read` currently returns 0 silently when there is no usable marker.

- [ ] **Step 3: Write the minimal implementation**

In `scripts/handoff.py`, add `os` to the imports:

```python
import os
```

Add `passthrough()` after `unlink_quietly()`:

```python
def passthrough() -> None:
    """Hand the session start to recent-projects.py, preserving its behavior.

    execv replaces this process, so recent-projects.py's stdout becomes ours
    and its banner rendering is never duplicated here. Returns only if the
    exec itself fails, in which case staying silent is the safe outcome.
    """
    script = Path(__file__).resolve().parent / "recent-projects.py"
    try:
        os.execv(sys.executable, [sys.executable, str(script)])
    except OSError:
        return
```

Change the two early returns in `cmd_read()` so only the unresolvable-root case stays silent:

```python
def cmd_read(args: argparse.Namespace) -> int:
    root = workspace_lib.resolve_workspace_root()
    if root is None:
        # Not inside a workspace: stay silent, matching recent-projects.py.
        return 0

    marker = load_marker(marker_path(root))
    if marker is None:
        passthrough()
        return 0
```

Guard `main()` so a hook can never crash a session start:

```python
def main() -> int:
    args = build_parser().parse_args()
    if args.command == "write":
        return cmd_write(args)
    if args.command == "read":
        try:
            return cmd_read(args)
        except Exception:
            # A SessionStart hook must never fail loudly. load_marker already
            # swallows bad markers, so reaching here means something
            # unexpected; silence beats a traceback in the user's context.
            return 0
    return 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_handoff.py`
Expected: PASS, 18 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/handoff.py tests/test_handoff.py
git commit -m "Fall through to recent-projects.py when no handoff is armed"
```

---

### Task 4: Wire the SessionStart hooks

Today `recent-projects.py` is registered with no matcher, so it fires on every source including `clear`. It gets scoped to everything *except* `clear`, and `handoff.py read` takes ownership of `clear` entirely.

Matchers containing only letters, digits, `_`, `-`, spaces, `,` and `|` are treated as exact-string lists rather than regex, so `startup|resume|fork|compact` matches those four sources exactly. Those four plus `clear` are the complete set of SessionStart sources.

**Files:**
- Modify: `hooks/hooks.json`

**Interfaces:**
- Consumes: `handoff.py read` from Task 3

- [ ] **Step 1: Replace the hooks file**

Write `hooks/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|fork|compact",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/recent-projects.py\""
          }
        ]
      },
      {
        "matcher": "clear",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/handoff.py\" read"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2: Validate the manifests**

Run: `claude plugin validate . --strict`
Expected: passes with no errors.

- [ ] **Step 3: Verify the JSON parses and both scripts are reachable**

Run:

```bash
python3 -c "
import json, pathlib
h = json.loads(pathlib.Path('hooks/hooks.json').read_text())
entries = h['hooks']['SessionStart']
assert len(entries) == 2, entries
matchers = {e['matcher'] for e in entries}
assert matchers == {'startup|resume|fork|compact', 'clear'}, matchers
for e in entries:
    cmd = e['hooks'][0]['command']
    name = cmd.split('/scripts/')[1].split('\"')[0]
    assert (pathlib.Path('scripts') / name).is_file(), name
print('ok')
"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add hooks/hooks.json
git commit -m "Route the clear session source to handoff.py"
```

---

### Task 5: The `/workspace:checkpoint` skill

**Files:**
- Create: `skills/checkpoint/SKILL.md`

**Interfaces:**
- Consumes: `handoff.py write` from Task 1; the existing `workspace:update-project` skill

`disable-model-invocation: true` follows the documented guidance for side-effecting commands like `/commit` and `/deploy` — Claude should never arm a handoff on its own.

- [ ] **Step 1: Write the skill**

Create `skills/checkpoint/SKILL.md`:

```markdown
---
name: checkpoint
description: Save session progress to the project docs and arm a handoff for the next /clear
argument-hint: [name-or-number]
disable-model-invocation: true
---

# Checkpoint a Session

Record what this session accomplished, then arm a handoff so the next
session — after you press `/clear` — resumes the project automatically.

This is the command to run at a natural breaking point. It replaces the
`/workspace:update-project` → `/clear` → `/workspace:resume-project`
sequence with `/workspace:checkpoint` → `/clear`.

## Step 1: Resolve Project

Use the project already loaded in this conversation (from
`/workspace:resume-project` or any earlier project interaction). If
`$ARGUMENTS` has a token, use that as the project name instead.

If no project is in context and no argument was given, ask which project.

**Do not run `resume-project.py` here.** This session is the one being wound
down; loading its JSON merely to learn a name spends the context this
command exists to save.

## Step 2: Update the Documentation

Invoke the `workspace:update-project` skill with the resolved project name.

All document writing happens there, under its existing scope rules — including
its prohibition on touching `status:` frontmatter, memory files, and repo
source. Do not duplicate or second-guess that work here.

If update-project reports it had nothing to update, continue anyway: a
handoff is still worth arming.

## Step 3: Decide the Handoff

From the documentation you just wrote, decide two things:

1. **`next_task`** — the single next action, in a short phrase. This is your
   judgment about what should happen next, not merely the first unchecked
   checklist item. It is the thing that would otherwise be lost across the
   `/clear`.
2. **`load_files`** — the detail files needed for that task, as they appear
   in the Reference Files table (paths relative to the project directory).
   An empty list is fine for a monolithic project.

## Step 4: Arm the Handoff

Run via Bash, substituting your values:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/handoff.py" write \
  --project "<name>" \
  --next-task "<next task phrase>" \
  --load-files "<file1.md,file2.md>"
```

Omit `--load-files` when there are none.

Parse the JSON output:

- **`status: "ok"`** — proceed to Step 5.
- **`status: "error"`** — show the `message` and **stop**. Do not tell the
  user to clear: the documentation updates from Step 2 are safely on disk,
  and `/workspace:resume-project` by hand still recovers everything.

## Step 5: Report

Tell the user:

> Checkpoint saved. Press `/clear` — the next session will resume
> `<project>` at "<next task>" automatically.

The handoff expires after 60 minutes and fires only once.
```

- [ ] **Step 2: Verify the frontmatter parses and the skill is discovered**

Run:

```bash
python3 -c "
import pathlib, re
text = pathlib.Path('skills/checkpoint/SKILL.md').read_text()
assert text.startswith('---\n'), 'missing frontmatter'
fm = text.split('---')[1]
for key in ('name: checkpoint', 'disable-model-invocation: true'):
    assert key in fm, key
assert 'handoff.py' in text and 'write' in text
print('ok')
"
```

Expected: `ok`

- [ ] **Step 3: Validate the plugin**

Run: `claude plugin validate . --strict`
Expected: passes with no errors.

- [ ] **Step 4: Commit**

```bash
git add skills/checkpoint/SKILL.md
git commit -m "Add /workspace:checkpoint skill"
```

---

### Task 6: Resume without the task menu

When a handoff directive is in context, the checkpoint already decided what is
next, so `resume-project` must not re-ask.

**Files:**
- Modify: `skills/resume-project/SKILL.md:144-158` (Step 4)

**Interfaces:**
- Consumes: the directive text from `build_directive()` in Task 2

- [ ] **Step 1: Insert the handoff branch**

In `skills/resume-project/SKILL.md`, find:

```markdown
## Step 4: Task Selection

**4a.** Build a task menu from `P.checklist.unchecked_items`.
```

Replace with:

```markdown
## Step 4: Task Selection

**If a checkpoint handoff was injected into this session** — the SessionStart
context opened with "Checkpoint handoff pending" and named a project, a next
task, and detail files — then the task decision has already been made:

- Skip **4a** and **4b** entirely. Do not present a menu.
- Read the named detail files with the Read tool, joining them to `P.dir`.
- Report readiness: the loaded files, the checklist progress, and the next
  task from the directive.
- Continue with **4d**, **4e**, and **4f** as normal.

Otherwise, proceed with 4a onward.

**4a.** Build a task menu from `P.checklist.unchecked_items`.
```

- [ ] **Step 2: Verify the branch is present and Step 4 is still well-formed**

Run:

```bash
python3 -c "
import pathlib
text = pathlib.Path('skills/resume-project/SKILL.md').read_text()
assert 'Checkpoint handoff pending' in text
assert 'Skip **4a** and **4b** entirely' in text
assert text.count('**4a.** Build a task menu') == 1
for marker in ('**4d.**', '**4e.**', '**4f.**'):
    assert marker in text, marker
print('ok')
"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add skills/resume-project/SKILL.md
git commit -m "Skip the resume task menu when a handoff supplied the next task"
```

---

### Task 7: Documentation

**Files:**
- Modify: `CLAUDE.md` (layout block, skills table, key conventions)
- Modify: `README.md:37-50` (skills table, hook note)

- [ ] **Step 1: Update the layout block in CLAUDE.md**

Change the skills count and the hooks line:

```
skills/<name>/SKILL.md                            8 skills (workspace: prefix)
```

```
hooks/hooks.json                                  SessionStart → recent-projects.py / handoff.py
```

Add after the `scripts/skills.py` line:

```
scripts/handoff.py                                Checkpoint marker: write (skill) / read (hook)
```

Change the tests line:

```
tests/{test_setup.sh, test_skills.py, test_handoff.py}   Test suites
```

- [ ] **Step 2: Add the skill to the CLAUDE.md table**

Insert after the `/workspace:new-project` row:

```markdown
| `/workspace:checkpoint` | Update project docs and arm a handoff for the next `/clear` |
```

- [ ] **Step 3: Add a Key Conventions bullet in CLAUDE.md**

Insert after the **PyYAML** bullet:

```markdown
- **Checkpoint handoff**: `/workspace:checkpoint` writes a single-use marker
  to `<workspace>/.claude/handoff.json`; the SessionStart hook on the `clear`
  matcher (`handoff.py read`) consumes it and tells Claude to resume that
  project, then falls through to `recent-projects.py` when no handoff is
  armed. Marker TTL 60 min, schema version 1. `handoff.py` is yaml-free for
  the same reason `recent-projects.py` is. `/clear` itself can never be
  issued by Claude — it is not among the built-ins reachable through the
  Skill tool — so the marker is how state crosses that boundary.
```

- [ ] **Step 4: Update the README skills table and hook note**

Insert after the `/workspace:new-project` row in `README.md`:

```markdown
| `/workspace:checkpoint` | Save session progress and arm a handoff so the next `/clear` resumes automatically |
```

Replace the paragraph at `README.md:49-50`:

```markdown
A SessionStart hook surfaces your recent projects whenever you launch Claude
Code inside a workspace (it stays silent elsewhere). After
`/workspace:checkpoint`, that same hook instead resumes the checkpointed
project on your next `/clear`.
```

- [ ] **Step 5: Verify the docs are consistent**

Run:

```bash
python3 -c "
import pathlib
for name in ('CLAUDE.md', 'README.md'):
    text = pathlib.Path(name).read_text()
    assert '/workspace:checkpoint' in text, name
    assert text.count('| \`/workspace:checkpoint\`') == 1, name
claude_md = pathlib.Path('CLAUDE.md').read_text()
assert '8 skills' in claude_md
assert 'handoff.py' in claude_md
assert 'test_handoff.py' in claude_md
print('ok')
"
```

Expected: `ok`

Also confirm the table row count matches the skills on disk:

```bash
test "$(ls -d skills/*/ | wc -l | tr -d ' ')" = 8 && echo "8 skills on disk"
```

- [ ] **Step 6: Run the whole suite and validate**

Run:

```bash
python3 tests/test_handoff.py && python3 tests/test_skills.py && bash tests/test_setup.sh && claude plugin validate . --strict
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "Document the checkpoint handoff"
```

---

## Manual Verification

Two links in the chain cannot be exercised by unit tests, because only the
harness fires hooks. Do these once, after Task 7:

- [ ] **Live handoff.** In a real workspace: `claude --plugin-dir <this repo>`,
      resume or create a project, run `/workspace:checkpoint`, then press
      `/clear`. Expected: the new session opens with "Resuming <project> from
      checkpoint", loads the named detail files, and reports the next task
      without showing a task menu.
- [ ] **Normal clear is unchanged.** In the same session, press `/clear` again
      with no checkpoint armed. Expected: the familiar "Recent projects"
      banner, exactly as before this change.

## Out of Scope

Breaking-point detection — a `Stop` hook of `type: "prompt"` or `type: "agent"`
that notices a natural stopping point and suggests checkpointing — is a
deliberate follow-up, to be designed once the mechanism above is working.
