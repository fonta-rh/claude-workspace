# Surface Repo Skills in the Workspace (issue #1)

**Date:** 2026-07-07
**Status:** Approved design
**Base:** PR #3 (`workspace` plugin refactor, branch `issue-2-plugin-refactor`)

## Problem

Skills shipped inside cloned repos (`$WS/repos/<repo>/.claude/skills/`) are
discovered by Claude Code but scoped to their repo directory. They never
appear in user-facing autocomplete at the workspace root, where users
actually work. Domain-specific skills (e.g. `vet-review` from
`two-node-toolbox`) are effectively invisible.

Tested behavior (Claude Code v2.1.191):

- Flat symlink `WS/.claude/skills/<name>` → repo skill dir **is** discovered
  in autocomplete; nested dirs are **not** (no colon namespacing via nesting).
- Autocomplete uses the frontmatter `name:`; the Skill tool uses the
  directory name — so the symlink name must equal the frontmatter `name:`.
- The filesystem watcher picks up symlink creation/removal **live**, provided
  `.claude/skills/` existed at session start.

## Solution Overview

Flat-symlink selected repo skills into the workspace's `.claude/skills/`.
Bind the lifecycle to the project commands, mirroring worktrees:

| Command | Responsibility |
|---------|---------------|
| `setup.sh init` / `clone` | Ensure `$WS/.claude/skills/` exists (watcher precondition) |
| `/workspace:new` | Scan selected repos' skills, ask the user, link, record in frontmatter |
| `/workspace:resume` | Verify recorded skills, auto-repair broken/missing links |
| `/workspace:close` | Refcount across active projects, remove links nobody else uses |

State lives in each project's `CLAUDE.md` frontmatter:

```yaml
skills:
  - name: vet-review
    source: two-node-toolbox
```

No workspace or plugin `CLAUDE.md` table is generated or updated. The
workspace is a plain user directory (not a git clone), so no `.gitignore`
handling is needed.

## Decisions Log

| Decision | Choice |
|----------|--------|
| Baseline | Adopt issue #1's tested symlink proposal |
| Git hygiene | Moot post-PR #3 (workspace is not a git repo); dropped |
| Skills table in CLAUDE.md | Skipped — autocomplete + frontmatter are the record |
| Resume behavior | Verify + auto-repair, report what was fixed |
| Logic home | Python helper `scripts/skills.py`, JSON out, per `resume-project.py` pattern |

## Component: `scripts/skills.py`

Ships in the plugin; invoked as
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/skills.py" <subcommand> [args]`.

Conventions (identical to `resume-project.py`):

- `import workspace_lib`; workspace resolved via
  `resolve_workspace_root()` (`WORKSPACE_ROOT` → `CLAUDE_PROJECT_DIR` →
  walk-up to `dev-env.yaml`); exits with a JSON error if unresolvable.
- PyYAML for frontmatter, with the same self-describing JSON error when
  the module is missing.
- `from __future__ import annotations`; python3.9+ compatible.
- JSON to stdout; absolute paths in output. Every output carries a
  top-level `"status": "ok" | "error"`; fatal problems print
  `{"status": "error", "error": "..."}` and exit 0 — same as
  `resume-project.py`, so calling skills always get parseable JSON.

### `scan <repo> [<repo>...]`

Reads `$WS/repos/<repo>/.claude/skills/*/SKILL.md` frontmatter for each
named repo.

```json
{
  "workspace": "/abs/ws",
  "skills": [
    {
      "name": "vet-review",
      "description": "Review a change against TNF conventions",
      "repo": "two-node-toolbox",
      "dir": "vet-review",
      "path": "/abs/ws/repos/two-node-toolbox/.claude/skills/vet-review",
      "conflict": false,
      "already_present": null
    }
  ],
  "errors": []
}
```

- `dir` is the on-disk directory name; `name` is the frontmatter value.
  The symlink is always created under `name`.
- `conflict: true` on every entry whose `name` appears in more than one
  scanned repo.
- `already_present` is `null`, or `{"status": "same_source"}` when
  `$WS/.claude/skills/<name>` is a symlink already resolving to this
  skill's `path`, or `{"status": "collision", "target": "<abs>"}` when the
  entry is a real directory or a symlink resolving elsewhere, or
  `{"status": "dangling"}` when it is a symlink whose target no longer
  exists. Dangling entries are treated as absent by `/workspace:new`
  (offering the skill is fine — `link` replaces dangling symlinks).
- Per-repo problems (missing skills dir, unparseable frontmatter, skill
  missing `name:`) are collected in `errors` without failing the scan.
  A missing `.claude/skills/` dir in a repo is normal and reported as
  nothing at all (not an error).

### `link <name> <repo>`

Creates `$WS/.claude/skills/<name>` as a **relative** symlink
(`../../repos/<repo>/.claude/skills/<dir>`), so the workspace survives
being moved. `<dir>` is found by scanning the repo's skill dirs for the
one whose frontmatter `name:` equals `<name>` (JSON `status: error` if
none matches).

- Idempotent: if the entry already resolves to the same target, reports
  `{"linked": ..., "existed": true}`.
- Replaces a dangling symlink at the target name (harmless leftover).
- Refuses (JSON `status: error`) to touch a real directory or a symlink
  resolving elsewhere.
- Creates `$WS/.claude/skills/` if missing (with a `created_dir: true`
  flag in output, so the caller can warn that a session restart may be
  needed for the watcher).

### `verify <project>`

Reads `$WS/projects/<project>/CLAUDE.md` frontmatter `skills:` and checks
each entry:

| Status | Meaning | Repair (by `/workspace:resume`) |
|--------|---------|--------------------------------|
| `ok` | Symlink resolves to the recorded source skill | none |
| `missing` | No entry at `$WS/.claude/skills/<name>` | re-`link` |
| `broken` | Entry exists but does not resolve (dangling) | re-`link` |
| `source_gone` | Source skill dir no longer exists in the repo | warn; offer to drop from frontmatter |

A fifth condition — entry exists but resolves to a **different valid
skill** — is reported as `broken` with `"detail": "points_elsewhere"`.
Resume must NOT auto-repair this one (another project owns the name);
warn instead.

### `unlink-check <project>`

For each skill in the closing project's frontmatter, scans all **other**
projects with `status` ≠ `done` for a frontmatter skill with the same
`name`:

```json
{
  "skills": [
    {
      "name": "vet-review",
      "source": "two-node-toolbox",
      "is_symlink": true,
      "removable": false,
      "used_by": ["ocpedge-2608-multi-hypervisor"]
    }
  ]
}
```

- `removable: true` ⇔ the entry exists, `used_by` is empty, **and**
  `is_symlink` is true.
- An entry already absent from `$WS/.claude/skills/` is reported with
  `"missing": true` and `removable: false` — close skips it silently
  (nothing to remove, frontmatter still gets cleared).
- Check-only: actual removal is done by the close skill via
  `rm "$WS/.claude/skills/<name>"` (plain `rm`, never `rm -r` — target is
  a symlink).

Frontmatter **writes** remain the skill markdown's job (Edit tool), same
as worktree bookkeeping today.

## Command Flow Changes

### `scripts/setup.sh`

Idempotent `mkdir -p "$WORKSPACE_ROOT_RESOLVED/.claude/skills"` in both
the `init` and `clone` command paths (next to the existing
`.claude/settings.local.json` handling). Covers both
`/workspace:setup-environment` and `/workspace:create-domain`. This is
the watcher precondition: the directory must exist at session start.

### `skills/new/SKILL.md` — new Step 1g (after 1f, before Step 2)

1. Run `scan` with the repos selected in 1d. If it fails or finds
   nothing → skip silently (no question).
2. Entries with `already_present.status == "same_source"` are not asked
   about: record them in frontmatter and mention the reuse in the
   summary.
3. Entries with `already_present.status == "collision"` are excluded and
   reported ("name taken at workspace root").
4. Remaining skills: one multiSelect AskUserQuestion — label = `name`,
   description = `<description> (from <repo>)`.
5. Conflicts (same `name`, several repos): one single-select question per
   conflicted name — pick a source or skip. The unchosen source is simply
   not linkable this session (frontmatter can't be rewritten through a
   symlink).
6. `link` each selection. Failures are reported but never block project
   creation.
7. Frontmatter gains the `skills:` list (omit when empty, like
   `worktrees:`).
8. Step 4 summary lists linked skills next to worktrees: available
   immediately, no restart needed (unless `link` reported
   `created_dir: true`).

### `skills/resume/SKILL.md` — verify step after project load

Run `verify <project>` when the frontmatter has a non-empty `skills:`.

- `missing` / `broken` (no `points_elsewhere`) → re-run `link` from the
  recorded `source`, then report ("Relinked N skills").
- `broken` + `points_elsewhere` → warn, do not touch.
- `source_gone` → warn; offer (AskUserQuestion) to drop the entry from
  frontmatter.
- All `ok` → say nothing.

### `skills/close/SKILL.md` — Step 2.5 becomes "Worktree & Skill Cleanup"

After the worktree flow, if frontmatter `skills:` is non-empty:

1. Run `unlink-check <project>`.
2. `rm` every `removable: true` entry.
3. Report kept entries with the active projects still using them.
4. In Step 3b, set `skills: []` alongside `worktrees: []`.
5. Skills are unlinked even when the user chooses to keep worktrees —
   links are about autocomplete, not branches.

## Error Handling

- Script: `{"status": "error", "error": "..."}` (exit 0) for fatal issues
  (unresolvable workspace, missing PyYAML, unknown project, refusing to
  clobber); partial per-repo issues go in `errors` arrays on
  `status: ok` output.
- Skills markdown: any `skills.py` failure degrades to "continue without
  skill linking" with the error surfaced — never abort project
  creation/resume/close.
- Nothing under `$WS/.claude/skills/` that is not a symlink is ever
  modified or removed.

## Testing

New `tests/test_skills.py` — standalone stdlib `unittest`
(`python3 tests/test_skills.py`), tmpdir workspace fixtures (fake
`dev-env.yaml`, `repos/<r>/.claude/skills/...`, `projects/<p>/CLAUDE.md`),
driving the script as a subprocess with `WORKSPACE_ROOT` set (mirrors how
`test_setup.sh` isolates). Requires PyYAML (as does the script under
test).

Coverage matrix:

- **scan**: multi-repo dedup; conflict flagging; `already_present`
  same-source vs collision; repo without skills dir; malformed
  frontmatter → `errors`, not failure.
- **link**: creates relative symlink named after frontmatter `name`;
  idempotent re-link; refuses real dir; refuses foreign symlink;
  `created_dir` flag.
- **verify**: `ok`, `missing`, `broken` (dangling), `broken` +
  `points_elsewhere`, `source_gone`.
- **unlink-check**: exclusive → removable; shared with an active project
  → kept with `used_by`; shared only with a `done` project → removable;
  non-symlink entry → not removable.

## Scope (files touched)

| File | Change |
|------|--------|
| `scripts/skills.py` | New: scan / link / verify / unlink-check |
| `scripts/setup.sh` | `mkdir -p .claude/skills` in init + clone |
| `skills/new/SKILL.md` | Step 1g, frontmatter template, summary |
| `skills/resume/SKILL.md` | Verify + auto-repair step |
| `skills/close/SKILL.md` | Step 2.5 extension, frontmatter clearing |
| `tests/test_skills.py` | New test suite |

## Limitations

- Flat namespace only — nested/namespaced skill dirs are not discovered
  by Claude Code, so true name conflicts mean picking one source.
- Frontmatter can't be rewritten through a symlink, so no per-project
  renaming.
- Symlinks always target the **main checkout** (`repos/<repo>/`), never
  worktrees — skill content tracks the default branch.
- If `$WS/.claude/skills/` had to be created mid-session, the watcher
  won't see links until the session restarts (surfaced via
  `created_dir: true`).
- A project left open indefinitely keeps its links in place; they remain
  functional and are only reaped when the last referencing project
  closes.
