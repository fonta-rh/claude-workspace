#!/usr/bin/env python3
"""Tests for scripts/domain-info.py.

Standalone: python3 tests/test_domain_info.py
Requires PyYAML (as does the script under test).

Mirrors tests/test_skills.py: builds a throwaway "plugin" dir (scripts/ +
domains/, behaving like an install) and throwaway workspace dirs, then drives
domain-info.py as a subprocess with WORKSPACE_ROOT set.
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

REPO_ROOT = Path(__file__).resolve().parent.parent


def new_plugin(tmp: Path) -> Path:
    """Build a throwaway plugin dir: scripts/{domain-info.py,workspace_lib.py} + domains/."""
    plugin = tmp / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "scripts" / "domain-info.py", plugin / "scripts")
    shutil.copy(REPO_ROOT / "scripts" / "workspace_lib.py", plugin / "scripts")
    (plugin / "domains").mkdir()
    return plugin


def make_domain_dir(dir_: Path, name: str = "testdom", with_extras: bool = True) -> None:
    """Write a minimal domain: domain.yaml, dev-env.yaml (repos), context/testrepo.md."""
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "domain.yaml").write_text(f'name: {name}\ndescription: "Test domain"\n')
    (dir_ / "dev-env.yaml").write_text(
        "repos:\n"
        "  - name: testrepo\n"
        "    url: https://example.com/r.git\n"
        "    branch: main\n"
        "    category: testing\n"
        "    summary: \"test repo\"\n"
    )
    if with_extras:
        (dir_ / "context").mkdir()
        (dir_ / "context" / "testrepo.md").write_text(f"# testrepo context (domain: {name})\n")


def run_domain_info(plugin: Path, ws: Path, *args: str) -> dict:
    """Run domain-info.py against workspace ws; assert exit 0; return parsed JSON."""
    result = subprocess.run(
        [sys.executable, str(plugin / "scripts" / "domain-info.py"), *args],
        capture_output=True, text=True,
        env={**os.environ, "WORKSPACE_ROOT": str(ws)},
    )
    assert result.returncode == 0, (
        f"domain-info.py exited {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return json.loads(result.stdout)


class DomainInfoFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="domain-info-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.plugin = new_plugin(self.tmp)
        self.ws = self.tmp / "ws"
        (self.ws / "projects").mkdir(parents=True)

    def write_dev_env(self, body: str) -> None:
        (self.ws / "dev-env.yaml").write_text(body)

    def make_project(self, name: str, frontmatter: str) -> Path:
        proj_dir = self.ws / "projects" / name
        proj_dir.mkdir(parents=True)
        (proj_dir / "CLAUDE.md").write_text(f"---\n{frontmatter}\n---\n\n# {name}\n")
        return proj_dir


class TestErrorStatuses(DomainInfoFixture):
    def test_no_workspace_is_error(self):
        empty = Path(tempfile.mkdtemp(prefix="no-ws-"))
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        result = subprocess.run(
            [sys.executable, str(self.plugin / "scripts" / "domain-info.py")],
            capture_output=True, text=True, cwd=str(empty),
            env={k: v for k, v in os.environ.items()
                 if k not in ("WORKSPACE_ROOT", "CLAUDE_PROJECT_DIR")},
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], "error")

    def test_no_domain_block(self):
        self.write_dev_env("repos: []\n")
        data = run_domain_info(self.plugin, self.ws)
        self.assertEqual(data["status"], "no_domain")

    def test_domain_recorded_but_dir_missing(self):
        self.write_dev_env("domain:\n  name: ghost\n  source: bundled\n")
        data = run_domain_info(self.plugin, self.ws)
        self.assertEqual(data["status"], "not_found")


class TestResolution(DomainInfoFixture):
    def test_bundled_domain_ok(self):
        make_domain_dir(self.plugin / "domains" / "testdom")
        self.write_dev_env("domain:\n  name: testdom\n  source: bundled\n")
        data = run_domain_info(self.plugin, self.ws)
        self.assertEqual(data["status"], "ok")
        d = data["domain"]
        self.assertEqual(d["name"], "testdom")
        self.assertEqual(d["location"], "bundled")
        self.assertFalse(d["writable"])
        self.assertEqual(d["source"]["type"], "bundled")
        self.assertEqual(d["repos"], ["testrepo"])

    def test_scalar_domain_block(self):
        make_domain_dir(self.plugin / "domains" / "testdom")
        self.write_dev_env("domain: testdom\n")
        data = run_domain_info(self.plugin, self.ws)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["domain"]["name"], "testdom")
        self.assertEqual(data["domain"]["source"]["type"], "bundled")

    def test_git_source_domain(self):
        make_domain_dir(self.plugin / "domains" / "testdom")
        self.write_dev_env(
            "domain:\n"
            "  name: testdom\n"
            "  source: https://example.com/domain-pack.git\n"
            "  ref: main\n"
            "  subdir: packs/testdom\n"
        )
        # Even though source says git, resolution still finds the bundled dir
        # by name (this exercises source-block passthrough, not fetching).
        data = run_domain_info(self.plugin, self.ws)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["domain"]["source"]["type"], "git")
        self.assertEqual(data["domain"]["source"]["url"], "https://example.com/domain-pack.git")
        self.assertEqual(data["domain"]["source"]["subdir"], "packs/testdom")

    def test_workspace_domain_shadows_bundled(self):
        make_domain_dir(self.plugin / "domains" / "testdom")
        make_domain_dir(self.ws / "domains" / "testdom")
        self.write_dev_env("domain:\n  name: testdom\n  source: bundled\n")
        data = run_domain_info(self.plugin, self.ws)
        d = data["domain"]
        self.assertEqual(d["location"], "workspace")
        self.assertTrue(d["writable"])

    def test_project_frontmatter_domain(self):
        make_domain_dir(self.plugin / "domains" / "testdom")
        self.write_dev_env("repos: []\n")  # workspace itself has no domain recorded
        self.make_project("demo", "domain: testdom")
        data = run_domain_info(self.plugin, self.ws, "demo")
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["domain"]["name"], "testdom")
        self.assertEqual(data["project"]["name"], "demo")

    def test_project_legacy_preset(self):
        make_domain_dir(self.plugin / "domains" / "testdom")
        self.write_dev_env("repos: []\n")
        self.make_project("demo", "preset: testdom")
        data = run_domain_info(self.plugin, self.ws, "demo")
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["domain"]["name"], "testdom")

    def test_file_inventory_missing_subdirs(self):
        # Domain with only dev-env.yaml + domain.yaml (no context/, supplemental/, docs/).
        make_domain_dir(self.plugin / "domains" / "bare", with_extras=False)
        self.write_dev_env("domain:\n  name: bare\n  source: bundled\n")
        data = run_domain_info(self.plugin, self.ws)
        files = data["domain"]["files"]
        self.assertIsNone(files["context_md"])
        self.assertEqual(files["context"], [])
        self.assertEqual(files["supplemental"], [])
        self.assertEqual(files["docs"], [])

    def test_has_local_updates_flag(self):
        make_domain_dir(self.ws / "domains" / "testdom")
        self.write_dev_env("domain:\n  name: testdom\n  source: bundled\n")
        data = run_domain_info(self.plugin, self.ws)
        self.assertFalse(data["domain"]["has_local_updates"])

        (self.ws / "domains" / "testdom" / "UPDATES.md").write_text("# Updates\n")
        data = run_domain_info(self.plugin, self.ws)
        self.assertTrue(data["domain"]["has_local_updates"])


class TestCopyOnWrite(DomainInfoFixture):
    def test_copies_bundled_to_workspace(self):
        make_domain_dir(self.plugin / "domains" / "testdom")
        self.write_dev_env("domain:\n  name: testdom\n  source: bundled\n")

        data = run_domain_info(self.plugin, self.ws, "--copy-on-write")
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["domain"]["copy_on_write_action"], "copied")
        self.assertEqual(data["domain"]["location"], "workspace")
        self.assertTrue(data["domain"]["writable"])
        self.assertTrue((self.ws / "domains" / "testdom" / "domain.yaml").is_file())
        # source: bundled untouched in dev-env.yaml
        self.assertIn("source: bundled", (self.ws / "dev-env.yaml").read_text())

    def test_idempotent_on_second_call(self):
        make_domain_dir(self.plugin / "domains" / "testdom")
        self.write_dev_env("domain:\n  name: testdom\n  source: bundled\n")
        run_domain_info(self.plugin, self.ws, "--copy-on-write")

        data = run_domain_info(self.plugin, self.ws, "--copy-on-write")
        self.assertEqual(data["domain"]["copy_on_write_action"], "already_workspace")

    def test_noop_when_already_workspace_domain(self):
        make_domain_dir(self.ws / "domains" / "testdom")
        self.write_dev_env("domain:\n  name: testdom\n  source: bundled\n")
        data = run_domain_info(self.plugin, self.ws, "--copy-on-write")
        self.assertEqual(data["domain"]["copy_on_write_action"], "already_workspace")


if __name__ == "__main__":
    unittest.main()
