# Single-Repo Self-Workspace Design

**Date:** 2026-07-12
**Status:** Approved (brainstormed with user; means repo is the reference use case)

## Problem

The workspace plugin assumes a multi-repo workspace bootstrapped from a
domain: pick a domain, clone repos into `repos/`, distribute context. For a
single repo with no external preset (e.g. `/Users/pfontani/Workspace/means`),
the project-lifecycle skills (`new-project`, `resume-project`,
`update-project`, `close-project`, `consolidate-project`) already work with a
hand-written `dev-env.yaml` containing `repos: []` — but the bootstrap is
contrived: the user must hand-write `dev-env.yaml`, and the "this workspace
wraps the repo it lives in" concept exists only in prose comments that no
tooling reads.

## Goal

Make single-repo, no-domain workspaces first-class: declared in schema,
bootstrapped by `/workspace:setup-environment`, and understood by
`new-project`. Edit-in-place isolation (no worktrees on the self repo) —
worktree support may come later and is not blocked by this design.

## Design

### 1. Schema: top-level `self:` block in dev-env.yaml

```yaml
self:
  name: means
  summary: "Bureaucratic desk game — the workspace wraps this checkout"

repos: []
```

- **Presence of `self:` = single-repo mode.** No inference from empty repo
  lists or `.git` sniffing.
- Fields: `name` (repo short name) and `summary` (one line, feeds skill
  prose). No `branch:`, no `url:` — the checkout's git metadata is the
  source of truth and config copies would go stale (YAGNI).
- **`self:` and `domain:` are mutually exclusive.** Both present is a
  validation error.
- **`repos:` keeps its exact current meaning** (clonable external repos,
  landing under `repos/`). Normally `[]` in self mode, but entries are
  allowed and behave exactly as in multi-repo mode. The self repo is never
  listed in `repos:`, so no repo-iterating code needs a skip rule.
- **Backward compatible both ways:** multi-repo workspaces (no `self:`)
  see zero change; a bare `repos: []` file with no `self:` block (the
  current means hack) also keeps working as today.

### 2. Bootstrap: `setup.sh init --self` + setup-environment fork

`scripts/setup.sh` gains `init --self [<name>]`:

1. Refuses if the workspace root is not a git repo root, or if
   `dev-env.yaml` already exists (points at the existing file).
2. Writes `dev-env.yaml` from a new `templates/dev-env-self.yaml.template`
   (`self:` block with the repo name — defaulting to the workspace root's
   basename — a placeholder summary, `repos: []`, and schema comments).
3. Creates/merges `.claude/settings.local.json` from the existing settings
   template, creates `projects/` and `.claude/skills/` — same as domain init.

`refresh-domain` on a self workspace errors cleanly ("single-repo workspace
— no domain to refresh").

`skills/setup-environment/SKILL.md` grows a fork before the location step:
if the launch directory is inside a git repo, offer "Wrap this repo
(`<name>`) as a single-repo workspace" alongside the domain path. The self
path:

- Sets `$WS` = repo root, runs `init --self`.
- Asks for a one-line summary (suggesting one from README/CLAUDE.md) and
  Edits it into the `self:` block.
- Asks whether `projects/` should be tracked in git or added to
  `.gitignore` (default: track).
- **Never reads or writes the repo's CLAUDE.md.** The end-of-setup summary
  may *print* a suggested snippet pointing contributors at the task
  workflow — never written. Orientation comes from the SessionStart hook
  (recent projects), per-project CLAUDE.mds, and `dev-env.yaml`.
- Skips domain selection, clone, and context distribution entirely.

### 3. Lifecycle skills

Only `skills/new-project/SKILL.md` changes, and only its Step 1 branching.
When `dev-env.yaml` has a `self:` block:

- **1d (repo selection)** — skipped knowingly: "single-repo workspace; you
  edit the checkout directly."
- **1e (worktrees)** — skipped (edit-in-place).
- **1f (analysis-PR worktree)** — skipped; the PR URL goes into
  `related_links` only.
- **1g (skill linking)** — skipped: the repo's `.claude/skills/` *is* the
  workspace's; Claude Code picks it up natively.
- Project frontmatter is unchanged from today's `repos: []` form, which is
  why `resume-project`, `close-project`, `update-project`,
  `consolidate-project`, `resume-project.py`, `workspace_lib.py`,
  `skills.py`, and the SessionStart hook need **zero changes**.

### 4. Error handling

All at the entry point: `init --self` refuses non-git-repo roots and
existing `dev-env.yaml`; `self:` + `domain:` together is rejected where
setup.sh reads the file (`detect_repo_source`); `refresh-domain` on a self
workspace errors with a self-aware message. Nothing new can fail at
resume/close time because nothing there changed.

### 5. Testing

New cases in `tests/test_setup.sh`: `init --self` produces the right
dev-env.yaml, settings merge, `projects/`; name defaults to basename;
re-run refuses; non-git-repo refuses; `clone` in a self workspace is a
clean no-op; `refresh-domain` errors; both-blocks file is rejected.

Skill-prose changes are verified by `claude plugin validate . --strict`
and by dogfooding: **migrating means is the acceptance test** — add the
`self:` block to its dev-env.yaml, confirm `/workspace:new` and
`/workspace:resume` behave, optionally strip the workspace prose from its
CLAUDE.md.

## Out of Scope

- Worktrees on the self repo (`.worktrees/` at the workspace root). The
  schema carries enough (`self.name`) to add this later.
- Hybrid workflows beyond "repos: entries still clone normally".
- Any generation or modification of the wrapped repo's CLAUDE.md.
