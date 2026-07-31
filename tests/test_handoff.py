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
