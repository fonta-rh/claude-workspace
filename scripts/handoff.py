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
