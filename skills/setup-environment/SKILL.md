---
name: setup-environment
description: Set up or refresh a multi-repo workspace from a domain — pick a location, choose a domain, clone repos, distribute context
argument-hint: "[<git-url>]"
---

# Set Up Workspace Environment

You are helping a developer bootstrap a multi-repo development workspace
from a **domain** (a bundled or external config of repos + context). This
skill picks a location for the workspace, clones repos, distributes context
files, and generates the workspace's root CLAUDE.md.

The plugin ships read-only at `${CLAUDE_PLUGIN_ROOT}`. The **workspace** is a
separate, user-chosen directory. All `setup.sh` calls therefore pass
`--workspace "$WS"` explicitly — do not rely on the current directory, which
during this skill is the launch dir, not the chosen workspace.

To build a fully custom workspace from arbitrary repos (no bundled domain),
use `/workspace:create-domain` instead.

## Step 0: Choose the Workspace Location

Decide where the workspace will live and store it as `$WS`.

- **If `$ARGUMENTS` contains an existing workspace path**, use it.
- **Otherwise**, use AskUserQuestion to offer sensible locations, e.g.:
  - `~/Workspace/<name>` (Recommended)
  - `~/dev/<name>`
  - the current directory
  - Other (free-text path)

  Ask the user for the workspace folder name if needed. Expand `~` to the
  home directory.

Create it: `mkdir -p "$WS"` via Bash. (`setup.sh init` also creates a fresh
workspace, but creating it now lets later steps operate on a known path.)

**If `$ARGUMENTS` is a git URL** (starts with `https://`, `git@`, `ssh://`,
`git://`, or ends with `.git`): treat it as an external domain source and
skip Step 1 — use the URL directly in Step 2.

## Step 0.5: Check for an Existing Domain (refresh path)

Check if `$WS/dev-env.yaml` already exists and contains a `domain:` block.
If it does, read the `source` field and offer via AskUserQuestion:

- **"Re-initialize (keep current domain)"** — refresh from the recorded
  source (run `refresh-domain` in Step 2)
- **"Choose a different domain"** — continue to Step 1

If `$WS/dev-env.yaml` does not exist, skip this step.

## Step 1: Select Domain

**If `$ARGUMENTS` is a git URL**, skip this — use that URL as the domain
source and go to Step 2.

Otherwise, list available domains by running:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh" --workspace "$WS" init
```

This prints bundled and workspace domains (each tagged with its source),
each with a name and description. Present them via AskUserQuestion:
- One option per listed domain (name + description)
- An additional option: **"External domain (git URL)"**

If the user selects "External domain", ask for the git URL. The URL may
include a `#subdir` fragment for packs that contain multiple domains
(e.g., `https://github.com/org/domains.git#myteam`).

If only one domain exists, suggest it as the default but still confirm.

## Step 2: Initialize

Run via Bash:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh" --workspace "$WS" init <domain-name-or-url>
```

This:
- For bundled/workspace domains: copies the domain's `dev-env.yaml` to
  `$WS/dev-env.yaml`.
- For external URLs: shallow-clones the pack, validates the layout,
  installs it into `$WS/domains/<name>/`, then copies `dev-env.yaml`.
- In both cases: records the domain source in `$WS/dev-env.yaml` and creates
  or merges `$WS/.claude/settings.local.json` from the settings template.

If refreshing (Step 0.5 chose refresh), run this instead:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh" --workspace "$WS" refresh-domain
```

## Step 3: Clone Repos

Run via Bash to clone all repos defined in `$WS/dev-env.yaml`:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh" --workspace "$WS" clone
```

This may take a while for large repos — let the user know.

## Step 4: Verify Distributed Context Files

`clone` (Step 3) already distributes the active domain's files as part of
each repo clone. For each repo, the script does the following from the
active domain directory (`$WS/domains/<domain>/` or the bundled
`${CLAUDE_PLUGIN_ROOT}/domains/<domain>/`):

1. **Context** — if `context/<repo-name>.md` exists, it is copied to
   `$WS/repos/<repo-name>/DOMAIN-CONTEXT.md` **always** (even when the repo
   has its own native CLAUDE.md). This is the repo's role-in-the-domain
   context, read alongside CLAUDE.md.
2. **Supplemental CLAUDE.md** — if `supplemental/<repo-name>.md` exists and
   the repo has **no native `CLAUDE.md`**, it is copied to
   `$WS/repos/<repo-name>/CLAUDE.md`. A native CLAUDE.md is never overwritten.

No manual copying is needed — just confirm the files landed and log which
repos got a `DOMAIN-CONTEXT.md`, which got a supplemental `CLAUDE.md`, and
which kept their native `CLAUDE.md`.

## Step 5: Generate the Workspace Root CLAUDE.md

Build a markdown repo table from `$WS/dev-env.yaml` (one row per repo):

```markdown
| Name | Category | Summary |
|------|----------|---------|
| `<name>` | <category> | <summary> |
```

Then:

- **If `$WS/CLAUDE.md` already exists**, replace only the content between
  the `<!-- AUTO-GENERATED` and `<!-- END AUTO-GENERATED -->` markers with
  the freshly generated table. Leave everything else untouched.
- **If it does not exist**, create it from the template below, substituting
  the repo table between the markers and the domain name where noted.

<!-- WORKSPACE ROOT CLAUDE.md TEMPLATE -->
````markdown
# CLAUDE.md

Guidance for Claude Code when working in this multi-repo workspace.

## What This Workspace Is

A multi-repo development workspace managed by the `workspace` Claude Code
plugin. Source repositories are cloned into `repos/`. The active domain is
**<domain-name>** (see `dev-env.yaml`).

## Source of Truth Priority

1. **Always look at repos in this workspace FIRST** before using internal
   knowledge or web searches.
2. If a component has a repo here, that repo is the **authoritative source
   of truth**.
3. Repos may contain a **`DOMAIN-CONTEXT.md`** alongside their `CLAUDE.md` —
   it describes the repo's role in the domain and cross-repo relationships.
   **Read both** when working in a repo.

## Fork Model

Push changes to your personal fork first, then open pull requests to the
upstream repository.

## Worktree Convention

Projects that modify source repos use git worktrees for branch isolation:
`repos/<repo>/.worktrees/<branch-name>/`. Created by `/workspace:new`,
shown by `/workspace:resume`, cleaned up by `/workspace:close`. When a
project has worktrees, use the worktree path for modifications; the main
checkout stays on the default branch for reference.

## Repository Table

<!-- AUTO-GENERATED by /workspace:setup-environment — do not edit manually -->
<!-- To regenerate, re-run /workspace:setup-environment -->

| Name | Category | Summary |
|------|----------|---------|
<!-- repo rows go here -->

<!-- END AUTO-GENERATED -->

## Skills (workspace plugin)

| Skill | Description |
|-------|-------------|
| `/workspace:setup-environment` | Set up or refresh the workspace from a domain |
| `/workspace:create-domain` | Build a custom workspace from arbitrary repos |
| `/workspace:new` | Create a new project workspace for a task |
| `/workspace:resume` | Resume an existing project |
| `/workspace:close` | Close a completed project |
| `/workspace:update` | Update project docs from the session |
| `/workspace:consolidate` | Archive completed checklist items |

## Domain Docs

For architecture, debugging, and domain concepts, see the active domain's
docs (workspace `domains/<name>/docs/`, or the plugin-bundled domain).
````
<!-- END TEMPLATE -->

## Step 6: Summary

Present a summary to the user:
- The workspace location `$WS`
- Number of repos cloned
- Which repos got supplemental CLAUDE.md files
- Which repos already had native CLAUDE.md files (skipped)
- Pointer to domain docs if present
- **Next step:** "Launch `claude` from inside `$WS` for future sessions —
  the SessionStart hook will surface recent projects there, and
  `/workspace:new` will scaffold tasks in that workspace."

---

## Important Notes

- Always pass `--workspace "$WS"` to `setup.sh`; never assume the current
  directory is the workspace.
- Always use the Write/Edit tools to create/modify files, not Bash echo/cat.
- Use the Bash tool only for `setup.sh` commands and `mkdir -p`.
- `$WS/dev-env.yaml` is user-specific configuration.
- Context files copied into `$WS/repos/<name>/` are working copies, not
  committed to the source repos.
