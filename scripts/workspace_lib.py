#!/usr/bin/env python3
"""Shared helpers for the workspace plugin's python scripts.

Deliberately minimal and **yaml-free** so the SessionStart hook
(recent-projects.py) never needs a third-party dependency. Imported by
resume-project.py, consolidate-project.py, and recent-projects.py via a
plain ``import workspace_lib`` — python3 prepends the running script's own
directory to sys.path, so the sibling import resolves identically whether
the plugin is installed, loaded with ``--plugin-dir``, invoked by the hook,
or run as a subprocess.

Two roots are kept distinct:

* **Plugin root** — where this file (and the rest of the plugin) ships.
  Read-only; derived from this file's own location.
* **Workspace root** — the user-chosen directory holding ``dev-env.yaml``,
  ``repos/``, ``projects/``, and workspace-local ``domains/``. Resolved at
  runtime; never derived from ``__file__`` (that would point into the
  plugin).
"""

from __future__ import annotations

import os
from pathlib import Path

# This library ships inside the plugin, so its own location IS the plugin
# root (scripts/ is one level below the plugin root).
PLUGIN_ROOT = Path(__file__).resolve().parent.parent

DEV_ENV_YAML = "dev-env.yaml"


def _walk_up_for_marker(start: Path, marker: str) -> Path | None:
    """Walk up from ``start`` (inclusive) looking for a dir containing ``marker``."""
    try:
        current = start.resolve()
    except OSError:
        return None
    for candidate in (current, *current.parents):
        if (candidate / marker).is_file():
            return candidate
    return None


def resolve_workspace_root() -> Path | None:
    """Resolve the workspace root, or None if it cannot be determined.

    Resolution order (matches setup.sh):
      1. ``WORKSPACE_ROOT`` env var (explicit override).
      2. ``CLAUDE_PROJECT_DIR`` env var (set by Claude Code to the launch dir).
      3. Walk up from the current working directory to the nearest ancestor
         containing ``dev-env.yaml``.
      4. ``None``.

    There is intentionally **no** ``__file__`` fallback: this file lives in
    the plugin, not the workspace.
    """
    env_ws = os.environ.get("WORKSPACE_ROOT")
    if env_ws:
        return Path(env_ws).expanduser().resolve()

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if project_dir:
        return Path(project_dir).expanduser().resolve()

    found = _walk_up_for_marker(Path.cwd(), DEV_ENV_YAML)
    if found is not None:
        return found

    return None
