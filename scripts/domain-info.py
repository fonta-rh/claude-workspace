#!/usr/bin/env python3
"""Resolve a project's domain and report writability for /workspace:update-domain.

Usage:
  domain-info.py [project-name]                    # resolve + report
  domain-info.py --copy-on-write [project-name]    # ensure writable workspace copy

Output: JSON to stdout, always exit 0.
"""

from __future__ import annotations

import datetime
import json
import shutil
import sys
from pathlib import Path
from typing import Any

# Plugins cannot declare python dependencies. PyYAML is required to parse
# dev-env.yaml and project frontmatter — emit a self-describing JSON error
# (that the calling skill can relay) instead of a raw ImportError traceback.
try:
    import yaml
except ImportError:
    print(json.dumps({
        "status": "error",
        "error": "PyYAML is required by domain-info.py (dev-env.yaml / project "
                 "frontmatter is YAML). Install with: pip3 install pyyaml",
    }))
    sys.exit(0)

import workspace_lib


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
    if not isinstance(result, dict):
        return {}
    for k, v in result.items():
        if isinstance(v, (datetime.date, datetime.datetime)):
            result[k] = str(v)
    return result


def parse_domain_block(yaml_file: Path) -> dict[str, str]:
    """Parse the top-level `domain:` block of a dev-env.yaml (mapping or legacy scalar)."""
    default = {"name": "", "source": "bundled", "ref": "", "subdir": ""}
    if not yaml_file.is_file():
        return default
    try:
        data = yaml.safe_load(yaml_file.read_text())
    except yaml.YAMLError:
        return default
    if not isinstance(data, dict):
        return default
    block = data.get("domain", {})
    if isinstance(block, str):
        return {"name": block, "source": "bundled", "ref": "", "subdir": ""}
    if not isinstance(block, dict):
        return default
    return {
        "name": str(block.get("name", "")),
        "source": str(block.get("source", "bundled")),
        "ref": str(block.get("ref", "")),
        "subdir": str(block.get("subdir", "")),
    }


def domain_search_roots(root: Path) -> list[Path]:
    """Directories that may hold domains: workspace domains/ first, then bundled."""
    return [root / "domains", workspace_lib.PLUGIN_ROOT / "domains"]


def find_domain_dir(name: str, root: Path) -> Path | None:
    """Locate a domain directory by name: workspace first, then plugin-bundled."""
    if not name:
        return None
    for base in domain_search_roots(root):
        candidate = base / name
        if candidate.is_dir():
            return candidate
    return None


def resolve_domain_name(project_arg: str | None, root: Path) -> tuple[str, dict, dict | None]:
    """Resolve the domain name and its dev-env.yaml source block.

    Returns (domain_name, source_block, project_info). project_info is None
    when no project argument was given.
    """
    project_info: dict | None = None
    domain_name = ""

    if project_arg:
        project_dir = root / "projects" / project_arg
        if project_dir.is_dir():
            project_info = {"name": project_arg, "dir": str(project_dir)}
            fm = parse_frontmatter(project_dir / "CLAUDE.md")
            # Prefer the new `domain:` field; fall back to legacy `preset:`.
            raw = fm.get("domain") or fm.get("preset", "")
            if isinstance(raw, list):
                raw = raw[0] if raw else ""
            domain_name = str(raw)
        else:
            project_info = {"name": project_arg, "dir": None}

    ws_block = parse_domain_block(root / "dev-env.yaml")
    if domain_name:
        # Source tracking only exists for the workspace's own recorded domain;
        # a project's domain usually matches it, but fall back to "bundled"
        # with no URL if it doesn't (e.g. workspace was refreshed since).
        source_block = ws_block if ws_block["name"] == domain_name else {
            "name": domain_name, "source": "bundled", "ref": "", "subdir": "",
        }
    else:
        source_block = ws_block
        domain_name = ws_block["name"]

    return domain_name, source_block, project_info


def inventory_files(domain_dir: Path) -> dict[str, Any]:
    context_md = domain_dir / "context.md"
    context = []
    ctx_dir = domain_dir / "context"
    if ctx_dir.is_dir():
        context = [{"repo": p.stem, "path": str(p)} for p in sorted(ctx_dir.glob("*.md"))]
    supplemental = []
    sup_dir = domain_dir / "supplemental"
    if sup_dir.is_dir():
        supplemental = [{"repo": p.stem, "path": str(p)} for p in sorted(sup_dir.glob("*.md"))]
    docs = []
    docs_dir = domain_dir / "docs"
    if docs_dir.is_dir():
        docs = [{"name": p.stem, "path": str(p)} for p in sorted(docs_dir.glob("*.md"))]
    return {
        "context_md": str(context_md) if context_md.is_file() else None,
        "context": context,
        "supplemental": supplemental,
        "docs": docs,
    }


def inventory_repos(domain_dir: Path) -> list[str]:
    dev_env = domain_dir / "dev-env.yaml"
    if not dev_env.is_file():
        return []
    try:
        data = yaml.safe_load(dev_env.read_text())
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    repos = data.get("repos", [])
    if not isinstance(repos, list):
        return []
    return [str(r["name"]) for r in repos if isinstance(r, dict) and r.get("name")]


def build_domain_report(name: str, domain_dir: Path, root: Path, source_block: dict) -> dict:
    location = "workspace" if domain_dir.parent == root / "domains" else "bundled"
    source_type = "bundled" if source_block["source"] == "bundled" else "git"
    return {
        "name": name,
        "dir": str(domain_dir),
        "location": location,
        "writable": location == "workspace",
        "source": {
            "type": source_type,
            "url": None if source_type == "bundled" else source_block["source"],
            "ref": source_block["ref"],
            "subdir": source_block["subdir"],
        },
        "has_local_updates": (domain_dir / "UPDATES.md").is_file(),
        "files": inventory_files(domain_dir),
        "repos": inventory_repos(domain_dir),
    }


def main() -> None:
    args = sys.argv[1:]
    copy_on_write = "--copy-on-write" in args
    args = [a for a in args if a != "--copy-on-write"]
    project_arg = args[0] if args else None

    root = workspace_lib.resolve_workspace_root()
    if root is None:
        print(json.dumps({
            "status": "error",
            "error": "Could not determine the workspace root. Set WORKSPACE_ROOT "
                     "or run inside a workspace (a directory containing dev-env.yaml).",
        }))
        return

    domain_name, source_block, project_info = resolve_domain_name(project_arg, root)

    if not domain_name:
        print(json.dumps({
            "status": "no_domain",
            "error": "This workspace was not built from a domain (no domain: "
                     "block in dev-env.yaml, and no project domain recorded).",
        }))
        return

    domain_dir = find_domain_dir(domain_name, root)
    if domain_dir is None:
        print(json.dumps({
            "status": "not_found",
            "error": f"Domain '{domain_name}' is recorded but no directory "
                     f"was found for it (checked workspace and bundled domains/).",
        }))
        return

    if copy_on_write:
        if domain_dir.parent == root / "domains":
            action = "already_workspace"
        else:
            dest = root / "domains" / domain_name
            shutil.copytree(domain_dir, dest)
            domain_dir = dest
            action = "copied"
        report = build_domain_report(domain_name, domain_dir, root, source_block)
        report["copy_on_write_action"] = action
    else:
        report = build_domain_report(domain_name, domain_dir, root, source_block)

    print(json.dumps({
        "status": "ok",
        "workspace_root": str(root),
        "project": project_info,
        "domain": report,
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
