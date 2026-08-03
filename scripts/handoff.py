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
import os
import sys
from datetime import datetime, timezone
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


def unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


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


def cmd_read(args: argparse.Namespace) -> int:
    root = workspace_lib.resolve_workspace_root()
    if root is None:
        # Not inside a workspace: stay silent, matching recent-projects.py.
        return 0

    marker = load_marker(marker_path(root))
    if marker is None:
        passthrough()
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    write = sub.add_parser("write", help="Arm a handoff for the next /clear")
    write.add_argument("--project", required=True)
    write.add_argument("--next-task", required=True)
    write.add_argument("--load-files", default="",
                       help="Comma-separated detail files, relative to the project dir")

    sub.add_parser("read", help="Consume a handoff at session start (hook mode)")

    return parser


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


if __name__ == "__main__":
    sys.exit(main())
