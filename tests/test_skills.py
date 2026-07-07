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
