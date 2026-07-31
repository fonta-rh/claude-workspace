---
name: update-domain
description: Feed lessons learned from a project session back into the domain it was built from — context files, supplemental CLAUDE.md, and reference docs
argument-hint: "[name-or-number] [PR link or focus hint]"
---

# Update Domain From Project Lessons

Close the knowledge loop: a project session often surfaces durable facts
about the domain it was built from (a repo's behavior, a proven command, a
cross-repo gotcha). This command mines those lessons and writes them into
the domain's own files, so future workspaces built from it start smarter.

The first token in `$ARGUMENTS` is an optional project name or numeric
shorthand. Everything after it is an optional PR/diff link or focus hint
for lesson mining.

## Guardrails — read before editing anything

- **Never write to a bundled domain directly.** A domain resolved with
  `location: "bundled"` lives under `${CLAUDE_PLUGIN_ROOT}/domains/` — the
  plugin's own shipped, read-only checkout. This is true even if you
  happen to be developing this very plugin and that directory is a
  writable git checkout you could technically edit: it is not *this*
  workspace's copy, and editing it silently changes the plugin for every
  other workspace instead of this one. Always run
  `domain-info.py --copy-on-write` (Step 6) first and use only the `dir`
  path it returns for Edit/Write calls.
- **No writes before Step 5's confirmation.** Mining and routing are
  read-only; nothing is written until the user approves the plan.
- **Never touch:** `domain.yaml` (domain identity), the domain's own
  `dev-env.yaml` (repo list), the workspace root `dev-env.yaml`,
  `settings.local.json.tpl`, `projects/` files (that's
  `/workspace:update-project`'s territory), memory files. Never delete a
  domain file.
- **Redistribution is copy-only.** Step 7 may `cp` an edited
  `context/<repo>.md` over an already-cloned repo's `DOMAIN-CONTEXT.md`.
  Never overwrite a repo's own `CLAUDE.md` from `supplemental/<repo>.md`
  — it may have diverged; tell the user instead.

## Step 1: Resolve Project

Extract the first token from `$ARGUMENTS`. Run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resume-project.py" <first-token>`
via Bash (omit the token if none was provided). Parse the JSON and handle
by `status`, same as `/workspace:consolidate-project` Step 1:

- **`ok`** — use `project.name`. Proceed to Step 2.
- **`no_argument`** — check if a project was loaded earlier in this
  conversation; if so, re-run with that name. Otherwise present the first
  3 `alternatives` as AskUserQuestion options plus "See all projects".
- **`not_found`** / **`out_of_range`** — show `error_message`, present
  `alternatives` as a picker, re-run with chosen name.
- **`no_projects`** — show `error_message` and stop.
- **`error`** — if the message mentions **PyYAML**, relay the install
  command (`pip3 install pyyaml`). Otherwise show the message and stop.

## Step 2: Resolve Domain

Run via Bash:
```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/domain-info.py" <project-name>
```

Parse the JSON and handle by `status`:

- **`ok`** — note `domain.writable`, `domain.location`, and
  `domain.source.type`. Proceed to Step 3.
- **`no_domain`** — tell the user this workspace/project has no domain to
  update (e.g. a single-repo self-workspace) and stop.
- **`not_found`** — tell the user the recorded domain has no directory on
  disk and stop.
- **`error`** — if the message mentions **PyYAML**, relay the install
  command. Otherwise show the message and stop.

## Step 3: Mine Lessons

Read `domain.files` from Step 2 first — never propose a lesson that's
already documented there.

Mine from: the current session's conversation, the project's CLAUDE.md and
Reference Files detail docs, and an optional PR/diff link or focus hint
passed after the project token in `$ARGUMENTS`.

Categories to look for:
- Repo capability or behavior changes
- Key paths worth orienting new sessions to
- Proven build/test/debug commands not already documented
- Cross-repo interactions and gotchas
- Domain-wide facts (apply to every repo in the domain)
- Long-form reference material (architecture notes, deep dives)

Filter aggressively: only durable, domain-level knowledge. Not project
status, not one-off debugging detail, not anything already in the target
file. If nothing qualifies, say so and stop — do not manufacture a lesson
to justify writing something.

## Step 4: Route Each Lesson

For each lesson, pick exactly one target:

| Lesson shape | Target |
|---|---|
| Repo-specific orientation | `context/<repo>.md` — create from `${CLAUDE_PLUGIN_ROOT}/skills/create-domain/context-template.md`'s shape if missing. The repo must appear in `domain.repos` (Step 2's output). |
| Repo working-doc material | `supplemental/<repo>.md` — only if it already exists; never create a new supplemental file. |
| Domain-wide fact | `context.md` — keep the whole file ~20–40 lines. |
| Long-form reference | `docs/<topic>.md` — new or existing. |

Follow `context-template.md`'s line discipline (30–75 lines per-repo file).
If a per-repo file would overflow, move the long-form part to `docs/` and
leave a one-line pointer instead.

## Step 5: Confirm (Dry Run)

Show a table, one row per lesson:

```
| # | Lesson | Target file | New/Edit |
|---|--------|-------------|----------|
```

Followed by the actual diff (or full content, for new files) for each
target file — computed against the **current** files at `domain.dir` from
Step 2 (identical content will exist post-copy-on-write, since Step 6 is
a plain copy).

Ask via AskUserQuestion: apply all / apply a subset / cancel.

**No file is written before this is answered.**

## Step 6: Ensure Writable

If `domain.writable` was `false` in Step 2:

Explain briefly: this domain is bundled with the plugin, so the workspace
gets its own copy at `domains/<name>/` before editing (shadows the
bundled one automatically; `source: bundled` stays untouched in
`dev-env.yaml`, so `refresh-domain` remains safe). Confirm, then run:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/domain-info.py" --copy-on-write <project-name>
```

Use the `domain.dir` from **this** response for every Edit/Write in Step
7 — not the original bundled path.

## Step 7: Apply

For each approved lesson: Edit the existing file or Write the new one
(never echo/cat file contents into existence).

Append an entry to `UPDATES.md` in the domain dir (create it with a short
one-line header if it doesn't exist yet):

```markdown
## <YYYY-MM-DD> — <project-name>
- <file>: <one-line summary of what changed and why>
```

For each edited `context/<repo>.md`, if
`<workspace>/repos/<repo>/DOMAIN-CONTEXT.md` exists, `cp` the updated file
over it (mirrors `distribute_domain_files`'s unconditional overwrite for
that exact file). Do not touch a repo's own `CLAUDE.md`.

## Step 8: Offer PR-Back (External Domains Only)

If `domain.source.type == "git"`, ask via AskUserQuestion whether to open
a PR against the source repo. If yes:

1. Clone `domain.source.url` to a temp dir.
2. Copy the changed files in (respecting `domain.source.subdir` when set)
   — exclude `UPDATES.md` by default, it's workspace-local bookkeeping.
3. Branch `update-domain/<name>-<YYYY-MM-DD>`, commit, confirm before
   pushing, then create the PR (or print manual push/PR instructions if
   `gh` isn't available or the user declines the push).

## Step 9: Report

Summarize: files changed, whether redistribution ran, the `UPDATES.md`
entry, and the PR link if one was opened.

If `domain.source.type == "git"`, add a reminder: `refresh-domain`
re-fetches from the source and discards local domain edits (it warns when
`UPDATES.md` is present, but the safest path is merging the PR first).
