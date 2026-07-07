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

    def test_scan_skill_with_invalid_utf8_reports_error(self):
        skill_dir = self.ws / "repos" / "repo-a" / ".claude" / "skills" / "binary"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_bytes(b"\xff\xfe---\nname: x\n---\n")
        out = run_skills(self.ws, "scan", "repo-a")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["skills"], [])
        self.assertEqual(len(out["errors"]), 1)
        self.assertIn("binary", out["errors"][0])

    def test_scan_no_args_is_error(self):
        out = run_skills(self.ws, "scan")
        self.assertEqual(out["status"], "error")

    def test_scan_unsafe_name_reports_error(self):
        self.make_repo_skill("repo-a", "pwned", "../../pwned")
        out = run_skills(self.ws, "scan", "repo-a")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["skills"], [])
        self.assertEqual(len(out["errors"]), 1)
        self.assertIn("pwned", out["errors"][0])


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

    def test_link_unsafe_name_is_error(self):
        self.make_repo_skill("repo-a", "pwned", "../../pwned")
        out = self.link("../../pwned", "repo-a")
        self.assertEqual(out["status"], "error")
        self.assertFalse((self.ws / "pwned").exists())
        self.assertFalse(os.path.lexists(self.tmp / "pwned"))

    def test_link_refuses_when_skills_path_is_a_file(self):
        self.make_repo_skill("repo-a", "vet-review", "vet-review")
        (self.ws / ".claude").mkdir(parents=True)
        (self.ws / ".claude" / "skills").write_text("not a directory\n")
        out = self.link("vet-review", "repo-a")
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
