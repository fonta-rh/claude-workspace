---
name: create-domain
description: Build a custom multi-repo workspace from arbitrary repos — gather repos, clone, and generate per-repo context collaboratively
argument-hint: "[project description]"
---

# Create a Custom Workspace / Domain

You are helping a developer build a multi-repo workspace from scratch, for
any set of repositories (no bundled domain). You gather repos, write a
`dev-env.yaml`, clone them, and collaboratively generate per-repo context
files with Claude.

The plugin ships read-only at `${CLAUDE_PLUGIN_ROOT}`. The **workspace** is a
separate, user-chosen directory `$WS`. Pass `--workspace "$WS"` to every
`setup.sh` call.

To set up from a ready-made bundled domain instead, use
`/workspace:setup-environment`.

## Step 0: Choose the Workspace Location

Decide where the workspace will live and store it as `$WS` (same as
`/workspace:setup-environment` Step 0): offer sensible locations via
AskUserQuestion (`~/Workspace/<name>` recommended, current dir, or Other),
expand `~`, then `mkdir -p "$WS"`.

## Step 1: Gather Requirements

Ask the user to describe their project or focus area (unless a description
was already given in `$ARGUMENTS`):

> "What project or component are you working on? This helps me suggest
> relevant repositories."

## Step 2: Add Repos

Help the user build their repo list. Options:
- Paste Git URLs directly
- Search by org/repo name
- Browse suggestions based on their description

For each repo, collect: name, URL, directory, branch, category, summary.

## Step 3: Generate dev-env.yaml

Write `$WS/dev-env.yaml` using the Write tool, following the schema in
`${CLAUDE_PLUGIN_ROOT}/templates/dev-env.yaml.template`.

**Optional — persist as a reusable workspace domain.** Ask the user (via
AskUserQuestion) whether to save this config as a named domain under
`$WS/domains/<name>/` so it can be re-initialized or shared later. If yes,
create `$WS/domains/<name>/` with:
- `domain.yaml` (name + description)
- `dev-env.yaml` (the repo list)
- optional `context/`, `docs/`, `settings.local.json.tpl`

(Workspace domains shadow bundled ones of the same name.)

## Step 4: Clone Repos

Run via Bash:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh" --workspace "$WS" clone
```

After cloning, if `$WS/.claude/settings.local.json` does not exist, create
it from the plugin's template so the user gets the default permissions:

```bash
mkdir -p "$WS/.claude"
cp "${CLAUDE_PLUGIN_ROOT}/templates/settings.local.json.tpl" "$WS/.claude/settings.local.json"
```

(The SessionStart hook is shipped by the plugin, so the template no longer
carries a hooks block.)

## Step 5: Generate Repo Context

#### Step 5a — Offer context generation choice

Use AskUserQuestion with 2 options:
- **"Generate context collaboratively"** (Recommended) — Claude explores
  each repo and drafts context files for the user to review
- **"Use stub templates (I'll fill them in later)"** — skip to Step 5f

Every repo gets at least a stub file; there is no "skip all" option.

#### Step 5b — Dispatch Explore agents (parallel)

For each cloned repo **without** a native CLAUDE.md, launch an Explore
agent via the Task tool (`subagent_type=Explore`). **Run all agents in
parallel** (single message, multiple Task tool calls).

Repos **with** a native CLAUDE.md are noted for the user (Step 5e) and
skipped for exploration.

Explore prompt for each repo must include:
- The user's project description from Step 1
- The repo's category and summary from `$WS/dev-env.yaml`
- Request these findings:
  1. Purpose (one sentence)
  2. Project-relevant paths (3–8 key paths)
  3. Test files (up to 5)
  4. Build/test commands (3–5)
  5. Native docs summary (README, HACKING.md, etc.)
  6. Cross-repo references (imports/dependencies to other repos in the env)

#### Step 5c — Triage: select repos for full context

Present a summary table of exploration results:
```
| Repo | Category | Auto-Detected Purpose |
```

Use AskUserQuestion with `multiSelect=true` — the user picks which repos
should get full collaboratively-generated context files. Non-selected repos
get stubs (Step 5f).

#### Step 5d — Per-repo draft & review

Read `${CLAUDE_PLUGIN_ROOT}/skills/create-domain/context-template.md` once
for the template structure and principles. Then for each repo selected in 5c:

1. Draft a context file using: Explore findings + project description +
   dev-env.yaml metadata, following the loaded template
2. Show the draft and use AskUserQuestion with 3 options:
   - **Approve** — write to `$WS/repos/<repo-name>/CLAUDE.md`
   - **Edit** — ask user what to change, incorporate feedback, show
     updated draft, ask for final approval (one round max)
   - **Skip** — use a stub instead (Step 5f)
3. Write approved files to `$WS/repos/<repo-name>/CLAUDE.md`

#### Step 5e — Native CLAUDE.md handling

Repos with an existing native CLAUDE.md are skipped — inform the user
these repos already have their own context. Do not overwrite.

#### Step 5f — Stub fallback

Create stubs for: repos not selected in 5c, repos skipped in 5d, or
**all** repos if the user chose stubs in 5a. Use this template:

```markdown
# <repo-name>

<!-- TODO: Add project-specific context for this repo. -->
<!-- Useful things to document: -->
<!--   - What this repo does in the context of your project -->
<!--   - Key paths and entry points relevant to your work -->
<!--   - Build/test commands you use frequently -->

## Key Paths

- TODO

## Notes

- TODO
```

After creating stubs, **warn the user**: list the repos that got stubs
and note they should be filled in for best results with Claude.

## Step 6: Generate the Workspace Root CLAUDE.md

Create/update `$WS/CLAUDE.md` with a repo table, exactly as in
`/workspace:setup-environment` Step 5 (use the same template and
`<!-- AUTO-GENERATED -->` markers; there is no domain name for a fully
custom workspace — say "custom").

## Step 7: Review

Show the user what was set up:
- The workspace location `$WS`
- All repos and their status
- Which repos got **collaboratively generated** context (with approximate
  line count) — ready to use
- Which repos got **stub** CLAUDE.md files — warn they should be filled in
- Which repos have **native** CLAUDE.md (skipped — repo's own context
  takes priority)
- **Next step:** launch `claude` from inside `$WS` for future sessions.

---

## Important Notes

- Always pass `--workspace "$WS"` to `setup.sh`.
- Always use the Write tool to create/modify files, not Bash echo/cat.
- Use the Bash tool only for `setup.sh` commands, `cp` of the settings
  template, and `mkdir -p`.
- Dispatch Explore agents in parallel (single message, multiple Task tool
  calls) for efficiency during Step 5b.
- Include the user's project description from Step 1 in every Explore prompt
  so findings are project-relevant, not generic.
- Limit per-repo edit loops to one round in Step 5d — the user can edit the
  file later.
- Load the context template from
  `${CLAUDE_PLUGIN_ROOT}/skills/create-domain/context-template.md` once
  before generating any context files — do not inline it.
