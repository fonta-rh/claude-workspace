#!/usr/bin/env python3
"""Show the most recently active projects, excluding done projects.

Used by the SessionStart hook to give Claude and the user quick context.
Output: JSON with systemMessage (user-visible) and additionalContext (model context).

Deliberately yaml-free: this runs on every SessionStart and plugins cannot
declare python dependencies, so it must never import a third-party module.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import workspace_lib


def parse_frontmatter(claude_md: Path) -> dict[str, str]:
    """Extract YAML frontmatter as a flat key-value dict.

    Only parses if line 1 is exactly '---' and a closing '---' exists.
    """
    try:
        lines = claude_md.read_text().splitlines()
    except OSError:
        return {}

    if not lines or lines[0].strip() != "---":
        return {}

    result = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    else:
        return {}

    return result


def newest_mtime(directory: Path) -> float | None:
    """Return the most recent file mtime under directory, or None."""
    newest = None
    for root, _, files in os.walk(directory):
        for f in files:
            try:
                mt = os.path.getmtime(os.path.join(root, f))
            except OSError:
                continue
            if newest is None or mt > newest:
                newest = mt
    return newest


TERMINAL_STATUSES = {"done", "complete", "closed"}


def collect_projects(projects_dir: Path) -> list[dict]:
    """Collect non-done projects with their metadata and mtime."""
    entries = []
    for d in sorted(projects_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue

        fm = parse_frontmatter(d / "CLAUDE.md")
        if fm.get("status", "").lower() in TERMINAL_STATUSES:
            continue

        mtime = newest_mtime(d)
        if mtime is None:
            continue

        entries.append({
            "name": d.name,
            "type": fm.get("type", "—"),
            "status": fm.get("status", "—"),
            "mtime": mtime,
            "date_str": datetime.fromtimestamp(mtime).strftime("%b %d %H:%M"),
        })

    entries.sort(key=lambda e: e["mtime"], reverse=True)
    return entries


def main():
    """Entry point: output recent non-done projects as JSON or plain names."""
    # SessionStart hook: must stay silent (exit 0, no output) when not launched
    # inside a workspace, so it never adds noise to unrelated projects.
    project_root = workspace_lib.resolve_workspace_root()
    if project_root is None:
        sys.exit(0)
    projects_dir = project_root / "projects"

    if not projects_dir.is_dir():
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "--names":
        for entry in collect_projects(projects_dir):
            print(entry["name"])
        sys.exit(0)

    entries = collect_projects(projects_dir)
    if not entries:
        sys.exit(0)

    top = entries[:3]

    lines = ["Recent projects:", ""]
    lines.append("  #   NAME                           TYPE           STATUS     LAST ACTIVE")
    lines.append("  -   ----                           ----           ------     -----------")
    for i, e in enumerate(top, 1):
        lines.append(f"  {i:<3} {e['name']:<30} {e['type']:<14} {e['status']:<10} {e['date_str']}")
    lines.append("")
    lines.append("  Tip: /workspace:resume-project <name-or-number>")

    output = "\n".join(lines)
    payload = {
        "systemMessage": output,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": output,
        },
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
