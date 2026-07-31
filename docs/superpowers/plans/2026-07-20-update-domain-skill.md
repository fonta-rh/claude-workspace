# `/workspace:update-domain` Implementation Plan

**Goal:** A new skill that feeds lessons learned from a project session back
into the **domain** the workspace was built from — e.g., a merged PR in repo Y
adds a domain-relevant capability, so the domain's context files should
reflect it. Closes the knowledge loop: today knowledge only flows
domain → workspace, never back.

**Architecture:** A new helper script `scripts/domain-info.py` (JSON to
stdout, exit 0) owns the deterministic parts — project → domain resolution,
writability detection, file inventory, and copy-on-write of bundled domains
into `$WS/domains/<name>/`. The skill (`skills/update-domain/SKILL.md`) owns
the judgment parts — mining lessons from the conversation and project docs,
routing each lesson to the right domain file, dry-run confirmation, and an
interactive PR-back flow for external domains.

## Decisions made with the user

- **Route per lesson**: classify each lesson and target the right file
  (`context.md`, `context/<repo>.md`, `supplemental/<repo>.md`, `docs/*.md`),
  showing a diff before writing — not a single fixed target file.
- **Lesson sources**: the current session conversation + the project's docs
  (update-project's mining pattern); an optional PR/diff pointer can be passed
  via `$ARGUMENTS`.
- **Writability**: copy-on-write for bundled domains (the workspace copy
  shadows the bundled one); for external domains, offer to commit/PR the
  changes back to the recorded source repo.
- **Invocation**: standalone skill plus prose cross-references from
  `update-project` and `close-project` (matching the repo's existing
  cross-skill pattern; no formal sub-skill mechanism exists).

## Verified design facts (from code)

- `find_domain_dir()` (`scripts/setup.sh`) and `domain_search_roots()`
  (`scripts/resume-project.py`) both resolve workspace `domains/` before
  bundled — a workspace copy shadows automatically, no config change needed.
- `refresh_domain()` (`setup.sh`) with `source: bundled` only re-resolves via
  `find_domain_dir` and re-copies `dev-env.yaml` — **bundled copy-on-write is
  refresh-safe with `source: bundled` left unchanged**.
- The real clobber risk is **external** domains: `fetch_external_domain()`
  does `rm -rf "$dest"` after a generic `Overwrite? [y/N]` — local lesson
  edits would be silently discarded on refresh/re-init.
- `distribute_domain_files()` runs only at clone time: overwrites
  `DOMAIN-CONTEXT.md` unconditionally; copies `supplemental/<repo>.md` →
  `CLAUDE.md` only when the repo has no native CLAUDE.md. Edited files need
  manual redistribution to already-cloned repos.
- Not every domain has every subdir (lvm-operator has no `supplemental/`;
  example is minimal) — never assume the layout.

## Key decisions

- **D1 — copy-on-write keeps `source: bundled`**: copy the bundled dir →
  `$WS/domains/<name>/`; do not touch `dev-env.yaml` (shadowing makes the
  copy authoritative; refresh stays safe).
- **D2 — local-modification marker `UPDATES.md`** in the domain dir: per-run
  changelog entry (date, project, files touched, one-liners). Doubles as the
  machine-detectable "has local edits" flag. Never distributed to repos
  (distribution copies only exact-named `context/`/`supplemental/` files).
- **D3 — new helper `scripts/domain-info.py`** (not a resume-project.py
  mode): resume-project.py is project-scoped and never parses the
  `dev-env.yaml` `domain:` block. Python owns deterministic logic
  (resolution, writability, file inventory, copy-on-write); Claude owns
  lesson mining, routing, prose, diffs, PR flow.
- **D4 — redistribution**: after editing `context/<repo>.md`, `cp` over
  `repos/<repo>/DOMAIN-CONTEXT.md` if it exists (mirrors distribute's
  unconditional overwrite). Never auto-copy an edited `supplemental/<repo>.md`
  over a repo's `CLAUDE.md` (it may have diverged) — inform the user instead.
- **D5 — PR-back is Claude-side interactive** (no script): the workspace copy
  has `.git` stripped, so clone the recorded source URL to a temp dir, apply
  changed files (honoring `subdir`), branch `update-domain/<domain>-<date>`,
  commit, confirm before push, create the PR.

## Changes

### 1. `scripts/domain-info.py` (new)

Follows script conventions: `from __future__ import annotations`,
python3.9+, imports `workspace_lib`, lazy PyYAML with self-describing JSON
error, JSON to stdout, always exit 0.

```
domain-info.py [project-name]                    # resolve + report
domain-info.py --copy-on-write [project-name]    # ensure writable workspace copy
```

Resolution: workspace via `workspace_lib.resolve_workspace_root()`; domain
name from project frontmatter `domain:` (legacy `preset:` fallback, as in
resume-project.py), else `$WS/dev-env.yaml` `domain:` block (mapping and
legacy scalar forms); dir via workspace-first lookup (mirror
`find_domain_base`).

Output JSON (`status: ok`):

```json
{
  "status": "ok",
  "workspace_root": "/abs/ws",
  "project": {"name": "my-proj", "dir": "/abs/ws/projects/my-proj"},
  "domain": {
    "name": "tnf",
    "dir": "/abs/.../domains/tnf",
    "location": "bundled",
    "writable": false,
    "source": {"type": "bundled", "url": null, "ref": "", "subdir": ""},
    "has_local_updates": false,
    "files": {
      "context_md": "/abs/.../context.md",
      "context": [{"repo": "api", "path": "..."}],
      "supplemental": [{"repo": "origin", "path": "..."}],
      "docs": [{"name": "architecture", "path": "..."}]
    },
    "repos": ["api", "installer"]
  }
}
```

Error statuses: `error` (no workspace / PyYAML missing), `no_domain`
(workspace not built from a domain), `not_found` (name recorded but no dir).

`--copy-on-write`: `shutil.copytree` bundled → `$WS/domains/<name>/`;
`action: "copied" | "already_workspace"`; no-op for domains already
workspace-local (all external domains are, by construction).

### 2. `skills/update-domain/SKILL.md` (new)

Frontmatter: `name: update-domain`, `description: Feed lessons learned from a
project session back into the domain it was built from — context files,
supplemental CLAUDE.md, and reference docs`, `argument-hint:
"[name-or-number] [PR link or focus hint]"`. (Convention: no `allowed-tools`.)

Steps (numbered prose; consolidate-project's script-driven flow +
update-project's mining categories):

1. **Resolve project** — first `$ARGUMENTS` token →
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resume-project.py" <token>`; same
   status handling as consolidate-project Step 1.
2. **Resolve domain** — `domain-info.py <project>`; handle
   `no_domain`/`not_found`/`error`; note `writable` and `source.type`.
3. **Mine lessons** — from the conversation, the project's CLAUDE.md +
   Reference Files detail docs, and an optional PR/diff pointer in
   `$ARGUMENTS`. Categories: repo capability/behavior changes; key paths;
   proven build/test/debug commands; cross-repo interactions and gotchas;
   domain-wide facts; long-form reference material. Filter: durable
   domain-level knowledge only — not project status, not one-offs, not
   anything already in the target files (read them first). Nothing
   qualifies → say so, stop.
4. **Route each lesson** — repo-specific orientation → `context/<repo>.md`
   (create from `${CLAUDE_PLUGIN_ROOT}/skills/create-domain/context-template.md`
   shape if missing; repo must be in `domain.repos`); repo working-doc
   material where `supplemental/<repo>.md` exists → that file (never create
   new supplemental files); domain-wide → `context.md` (~20–40 lines);
   long-form → `docs/<topic>.md`. Line discipline per context-template.md
   (30–75 lines per-repo); overflow moves to `docs/` with a pointer.
5. **Confirm (dry run)** — table `| # | Lesson | Target file | New/Edit |` +
   per-file diffs; AskUserQuestion: apply all / subset / cancel. **No writes
   before confirmation.**
6. **Ensure writable** — if `writable: false`: explain copy-on-write
   (shadowing, `source: bundled` stays, refresh-safe), confirm, run
   `--copy-on-write`, use returned paths.
7. **Apply** — Edit existing / Write new (never echo/cat). Append an
   `UPDATES.md` entry (create with a short header if missing). Redistribute
   changed `context/<repo>.md` → `repos/<repo>/DOMAIN-CONTEXT.md` via `cp`
   where present.
8. **Offer PR-back (external only)** — if `source.type == git`:
   AskUserQuestion; on yes: clone the source URL to a temp dir, copy changed
   files into `subdir/` when set, branch `update-domain/<domain>-<date>`,
   commit, confirm before push, create the PR (or print manual
   instructions). Exclude `UPDATES.md` from the PR by default.
9. **Report** — files changed, redistribution done, UPDATES.md entry, PR
   link. External-domain caveat: `refresh-domain` re-fetches and discards
   local domain edits (warns when UPDATES.md is present) — merge the PR
   first.

Guardrails ("NEVER touch"): `domain.yaml` identity, the domain's
`dev-env.yaml` repo list, the workspace root `dev-env.yaml`,
`settings.local.json.tpl`, bundled plugin `domains/`, `repos/` sources
(except the redistribution copies in D4), `projects/` files (that's
update-project's territory), memory files. Never delete domain files.

### 3. `scripts/setup.sh` (small edit)

In `fetch_external_domain()`, inside the existing `if [[ -d "$dest" ]]`
branch before the `Overwrite? [y/N]` prompt: if `$dest/UPDATES.md` exists,
`log_warn` that local domain updates exist and overwriting discards them
(suggest the PR-back flow first). Covers both `refresh-domain` and
re-`init <url>`.

### 4. Cross-references (one line each)

- `skills/update-project/SKILL.md` — end of Step 4: if the session produced
  durable domain-level knowledge, suggest `/workspace:update-domain` (this
  command itself never edits domain files).
- `skills/close-project/SKILL.md` — near the closing confirmation: suggest
  `/workspace:update-domain <name>` if the project produced domain-worthy
  lessons.

### 5. Docs

- `CLAUDE.md`: Layout section — `7 skills` → `8 skills`, add
  `scripts/domain-info.py`; add the skill row to the Skills table.
- `README.md`: add a row to the skills table:
  `| /workspace:update-domain | Feed lessons learned from a project back into its domain's context files |`.
- No `plugin.json` change (skills are auto-discovered).

### 6. Tests

- **`tests/test_domain_info.py`** (new; mirrors `tests/test_skills.py`: temp
  workspace, subprocess with `WORKSPACE_ROOT`, JSON assertions, exit 0; fake
  plugin root via a temp copy of `scripts/` + fixture `domains/`, like
  `test_setup.sh new_plugin()`). Cases: frontmatter `domain:`; legacy
  `preset:`; dev-env.yaml fallback (mapping + scalar); bundled vs
  workspace-shadowed location/writability; file inventory with missing
  subdirs; `--copy-on-write` (copies, idempotent `already_workspace`, no-op
  on workspace domains); `no_domain` / `not_found` / no-workspace `error`.
- **`tests/test_setup.sh`**: new group "refresh warns on local domain
  updates" — init an external `file://` domain, create `UPDATES.md` in the
  workspace copy, `refresh-domain` piped `n` → warning shown, file survives;
  piped `y` → copy refreshed.
- `bash tests/test_setup.sh` and `claude plugin validate . --strict` must
  pass.

## Verification (end-to-end)

1. `bash scripts/setup.sh --workspace /tmp/ws init example && bash scripts/setup.sh --workspace /tmp/ws clone`
2. Fabricate `projects/demo/CLAUDE.md` (frontmatter `domain: example`) plus a
   `findings.md` with a plausible lesson.
3. From `/tmp/ws`, `claude --plugin-dir <this-repo>`, run
   `/workspace:update-domain demo`. Verify: dry-run table + diffs precede
   writes; copy-on-write created `/tmp/ws/domains/example/`; edits land
   there; `UPDATES.md` appended; `source: bundled` untouched; a subsequent
   `refresh-domain` resolves the workspace copy.
4. Repeat with a `file://` external domain to exercise the PR-back offer and
   the refresh warning.

## Implementation order

1. `scripts/domain-info.py` + `tests/test_domain_info.py`
2. `setup.sh` UPDATES.md warning + `test_setup.sh` group
3. `skills/update-domain/SKILL.md`
4. Cross-references + `CLAUDE.md` / `README.md`
5. Full test run + plugin validate + end-to-end dogfood
