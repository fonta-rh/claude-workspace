---
name: dev-env-setup
description: Initialize or refresh a dev environment from a domain or custom config
argument-hint: [setup|setup custom|<git-url>]
user-invocable: true
---

# Dev Environment Setup Skill

You are helping a developer set up or refresh their multi-repo development
environment. This skill handles cloning repos, distributing context files,
and generating the root CLAUDE.md repo table.

## Subcommand Routing

Parse `$ARGUMENTS` to determine the mode:

- **`$ARGUMENTS` is a git URL** (starts with `https://`, `git@`, `ssh://`,
  `git://`, or ends with `.git`): Follow [Mode A](#mode-a-from-domain),
  but skip Step 1 — use the URL directly as the domain source.
- **`$ARGUMENTS` is empty, "setup", or starts with "setup "** (but NOT
  "setup custom"): Follow [Mode A: From Domain](#mode-a-from-domain)
- **`$ARGUMENTS` is "setup custom" or starts with "setup custom "**:
  Follow [Mode B: From Scratch](#mode-b-from-scratch)

---

## Mode A: From Domain

### Step 0: Check for existing domain (refresh path)

Before presenting choices, check if `dev-env.yaml` already exists and
contains a `domain:` block. If it does, read the `source` field:
- If source is `bundled`: offer to refresh from the local domain files.
- If source is a URL: offer to re-fetch from that URL.

Use AskUserQuestion with options:
- **"Re-initialize (keep current domain)"** — refresh from the recorded source
- **"Choose a different domain"** — continue to Step 1

If `dev-env.yaml` does not exist, skip this step and go to Step 1.

### Step 1: Select Domain

**If `$ARGUMENTS` is a git URL**, skip the question — use that URL as the
domain source and go straight to Step 2.

Otherwise, list available domains by scanning the `domains/` directory.
For each subdirectory, read `domain.yaml` to get name and description.

Present the domains to the user via AskUserQuestion with the following options:
- One option per bundled domain (name + description)
- An additional option: **"External domain (git URL)"**

If the user selects "External domain", ask them to provide the git URL.
The URL may include a `#subdir` fragment for packs that contain multiple domains
(e.g., `https://github.com/org/domains.git#myteam`).

If only one bundled domain exists, suggest it as the default but still confirm.

### Step 2: Initialize

Run `./setup.sh init <domain-name-or-url>` via Bash. This:
- For bundled domains: copies `dev-env.yaml` to the root.
- For external URLs: shallow-clones the pack, validates the layout,
  installs it into `domains/<name>/`, then copies `dev-env.yaml`.
- In both cases: records the domain source in `dev-env.yaml` and copies
  `settings.local.json.tpl` if `.claude/settings.local.json` doesn't exist.

If refreshing (Step 0 chose refresh), run `./setup.sh refresh-domain` instead.

### Step 3: Clone Repos

Run `./setup.sh clone` via Bash to clone all repos defined in
`dev-env.yaml`. This may take a while for large repos — let the user
know.

### Step 4: Verify Distributed Context Files

`./setup.sh clone` (Step 3) already distributes the active domain's files
as part of each repo clone. For each repo, `clone_repo` does the following
from `domains/<domain>/`:

1. **Context** — if `context/<repo-name>.md` exists, it is copied to
   `repos/<repo-name>/DOMAIN-CONTEXT.md` **always** (even when the repo has
   its own native CLAUDE.md). This is the repo's role-in-the-domain context,
   read alongside CLAUDE.md.
2. **Supplemental CLAUDE.md** — if `supplemental/<repo-name>.md` exists and
   the repo has **no native `CLAUDE.md`**, it is copied to
   `repos/<repo-name>/CLAUDE.md`. A native CLAUDE.md is never overwritten.

No manual copying is needed here — just confirm the files landed and log
which repos got a `DOMAIN-CONTEXT.md`, which got a supplemental `CLAUDE.md`,
and which kept their native `CLAUDE.md`.

### Step 5: Generate Root CLAUDE.md Repo Table

Read the `dev-env.yaml` to build a markdown table of all repos. Then
read the current root `CLAUDE.md` and replace the content between the
`<!-- AUTO-GENERATED` comment markers with the freshly generated table.

The table format:
```markdown
| Name | Category | Summary |
|------|----------|---------|
| `<name>` | <category> | <summary> |
```

### Step 6: Summary

Present a summary to the user:
- Number of repos cloned
- Which repos got supplemental CLAUDE.md files
- Which repos already had native CLAUDE.md files (skipped)
- Pointer to domain docs (`domains/<domain>/docs/`) if the directory exists
- Suggest next steps: `/project:new` to start a task

---

## Mode B: From Scratch

### Step 1: Gather Requirements

Ask the user to describe their project or focus area:
> "What project or component are you working on? This helps me suggest
> relevant repositories."

### Step 2: Add Repos

Help the user build their repo list. Options:
- Paste Git URLs directly
- Search by org/repo name
- Browse suggestions based on their description

For each repo, collect: name, URL, directory, branch, category, summary.

### Step 3: Generate dev-env.yaml

Write the `dev-env.yaml` file at the repo root using the Write tool,
following the schema from `dev-env.yaml.template`.

### Step 4: Clone Repos

Run `./setup.sh clone` via Bash.

After cloning, if `.claude/settings.local.json` does not exist and
`settings.local.json.tpl` exists at the repo root, copy it to
`.claude/settings.local.json`. This gives the user the default
permissions and SessionStart hook.

### Step 5: Generate Repo Context

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
- The repo's category and summary from `dev-env.yaml`
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

Read `.claude/skills/dev-env-setup/context-template.md` once for the
template structure and principles. Then for each repo selected in 5c:

1. Draft a context file using: Explore findings + project description +
   dev-env.yaml metadata, following the loaded template
2. Show the draft and use AskUserQuestion with 3 options:
   - **Approve** — write to `repos/<repo-name>/CLAUDE.md`
   - **Edit** — ask user what to change, incorporate feedback, show
     updated draft, ask for final approval (one round max)
   - **Skip** — use a stub instead (Step 5f)
3. Write approved files to `repos/<repo-name>/CLAUDE.md`

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

### Step 6: Generate Root CLAUDE.md

Same as Mode A Step 5 — update the repo table in root CLAUDE.md.

### Step 7: Review

Show the user what was set up:
- List all repos and their status
- Show which repos got **collaboratively generated** context (with
  approximate line count) — these are ready to use
- Show which repos got **stub** CLAUDE.md files — warn that these
  should be filled in for best results
- Show which repos have **native** CLAUDE.md (skipped — repo's own
  context takes priority)

---

## Important Notes

- Always use the Write tool to create/modify files, not Bash echo/cat
- Use Bash tool only for `./setup.sh` commands and `mkdir -p`
- The `dev-env.yaml` file is gitignored (user-specific config)
- Domain context files in `domains/<domain>/context/` are committed to
  the repo and shared across the team
- When copying context files to `repos/<name>/CLAUDE.md`, those copies
  are gitignored via the `repos/` entry in `.gitignore`
- External domain directories under `domains/<name>/` are gitignored via
  `.git/info/exclude` (local-only, not committed)
- Dispatch Explore agents in parallel (single message with multiple Task
  tool calls) for efficiency during Mode B Step 5b
- Include the user's project description from Step 1 in every Explore
  prompt so findings are project-relevant, not generic
- Limit per-repo edit loops to one round in Step 5d — the user can
  always edit the file later
- Load the context template from `.claude/skills/dev-env-setup/context-template.md`
  once before generating any context files — do not inline the template
