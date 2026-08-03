---
name: resume-project
description: Resume an existing project workspace — reload its context and continue work
argument-hint: [name-or-number]
---

# Resume Project Workspace

Resume work on an existing project. Projects live under `projects/` in the
workspace.

## Step 1: Resolve Project

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resume-project.py" $ARGUMENTS`
via Bash. Parse the JSON output and handle by `status`:

- **`ok`** — proceed to Step 2.
- **`no_argument`** — present the first 3 `alternatives` as AskUserQuestion
  options plus "See all projects" (which shows the full list). Re-run the
  script with the chosen name.
- **`not_found`** or **`out_of_range`** — show `error_message`, present
  `alternatives` as a picker, re-run with the chosen name.
- **`no_projects`** — show `error_message` and stop.
- **`error`** — if the message mentions **PyYAML**, the dependency is missing
  on the user's machine; relay the install command (`pip3 install pyyaml`)
  rather than retrying. For any other error, show the message and stop.

Store the `project` object from the JSON as `P` for the remaining steps.
**All paths in `P` (context_file, repo_context_files, worktree paths, domain
docs, etc.) are absolute** — use them directly with the Read tool or Bash;
no path joining is needed.

## Step 2: Load Project Index

1. Read `P.context_file` using the Read tool (skip if null).
2. If `P.domain_context` is non-null, read it immediately using the Read
   tool. This is a short orientation file (~20-30 lines) that provides
   essential context about the domain's system architecture.
3. **Do NOT read `P.repo_context_files` or `P.domain_docs` yet.** Store
   both lists for on-demand loading (see Step 5).

## Step 3: Present Summary

Display a structured summary:

```
## Project: <P.name>

| Field | Value |
|-------|-------|
| **Type** | <P.frontmatter.type or "Unknown"> |
| **Created** | <P.frontmatter.created or "Unknown"> |
| **Status** | <P.frontmatter.status or "Unknown"> |
| **JIRA** | <P.frontmatter.jira or "None"> |
| **Repos** | <comma-separated P.frontmatter.repos, or "None specified"> |
```

**If `P.worktree_status` is non-empty:**
Show a worktree status table:

```
| Repo | Branch | Status | Path |
|------|--------|--------|------|
| <repo> | <branch> | <status> | `<path>` |
```

Where `<status>` is derived from each entry in `P.worktree_status`:
- `exists=false` → `MISSING`
- `error` is non-null → `ERROR: <message>`
- `dirty=true` and `ahead > 0` → `dirty (N files), ahead by N`
- `dirty=true` → `dirty (N files)`
- `no_upstream=true` → `no upstream (local-only commits)`
- `ahead > 0` → `ahead by N`
- otherwise → `clean`

If any worktree is MISSING, suggest how to recreate it (paths in
`P.worktree_status` are absolute):
- For PR branches (starting with `pr/`):
  > "Worktree for `<repo>` is missing. Recreate with:
  > `git -C <workspace>/repos/<repo> fetch origin pull/<N>/head:pr/<N> &&
  >  git -C <workspace>/repos/<repo> worktree add .worktrees/pr/<N> pr/<N>`"
- For dev branches:
  > "Worktree for `<repo>` is missing. Recreate with:
  > `git -C <workspace>/repos/<repo> worktree add .worktrees/<branch> -b <branch>
  >  origin/<default-branch>`"

Add: "When working on code changes, use the worktree paths above
instead of the main checkout."

**If `P.frontmatter.skills` is non-empty:**
Verify the project's linked skills:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/skills.py" verify <P.name>
```

If the output has `status: "error"`, mention it briefly and move on.
Otherwise act per skill `state`:

- `ok` → nothing; say nothing when all skills are `ok`.
- `missing` or `broken` WITHOUT `detail` → repair automatically:
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/skills.py" link <name> <source>`
  then report: "Relinked skill `<name>` (from `<source>`)."
- `broken` with `detail: "points_elsewhere"` → do NOT touch the entry
  (another project or the user owns that name now). Warn: "Skill
  `<name>` no longer points at `<source>` — leaving it alone."
- `source_gone` → the skill no longer exists in the source repo. Warn,
  and ask (AskUserQuestion) whether to remove the entry from this
  project's `skills:` frontmatter (Edit tool) or keep it for reference.

Repairs never block the resume flow — report and continue.

**If `P.has_reference_files`:**
Show the reference files table from `P.reference_files`. If
`P.unregistered_files` is non-empty, note them. Show checklist progress
as `P.checklist.checked`/`P.checklist.total`. Add: "Detail files will
be loaded based on what you choose to work on."

**If not:** Show `P.all_files` list. Add: "Full project context loaded."

**If `P.repo_context_files` is non-empty:**
Show an "Available Repo Context" table:

```
| Repo | Source | Path |
|------|--------|------|
| <repo> | <source> | `<path>` |
```

Add: "Repo context files will be loaded on demand when you work on a
specific repo."

**If `P.domain_docs` is non-empty:**
Show a "Domain Docs" table:

```
| Doc | Path |
|-----|------|
| <name> | `<path>` |
```

Add: "Domain docs available for deeper reference (architecture, debugging)."

## Step 4: Task Selection

**If a checkpoint handoff was injected into this session** — the SessionStart
context opened with "Checkpoint handoff pending" and named a project, a next
task, and detail files — then the task decision has already been made:

- Skip **4a** and **4b** entirely. Do not present a menu.
- Read the named detail files with the Read tool, joining them to `P.dir`.
- Report readiness: the loaded files, the checklist progress, and the next
  task from the directive.
- Continue with **4d**, **4e**, and **4f** as normal.

Otherwise, proceed with 4a onward.

**4a.** Build a task menu from `P.checklist.unchecked_items`. For each
item, match its text and `section` against `P.reference_files` descriptions
to determine which detail files are relevant. Reference-file paths are
relative to the project directory (`P.dir`, absolute) — join them to read.

**4b.** Present via AskUserQuestion with options like:
- "Next: <task text> (loads: file1.md, file2.md)"
- "Review all project notes (loads: all detail files)"
- "Something else"

Skip file annotations if `P.has_reference_files` is false (monolithic
project — all content is already in context from Step 2).

**4c.** After the user picks, read the mapped detail files using Read.
Confirm what was loaded.

**4d.** If `P.worktree_status` is non-empty and the selected task
involves a repo with a worktree, remind which path to use (from the
worktree's absolute `path`).

**4e.** Suggest relevant skills from `P.skill_suggestions`.

**4f.** Remind: "If you create new detail files during this session, add
them to the Reference Files table in CLAUDE.md."

## Step 5: Lazy Context Loading

**Do NOT load repo context files or domain docs until needed.** You have
the manifests from `P.repo_context_files` and `P.domain_docs` — use them
reactively:

- When the user's query involves a specific repo, **read its context file
  then** (from `P.repo_context_files` matching that repo name).
- When a task from Step 4 maps to specific repos, load their context at
  that point.
- When the user's query involves cross-repo interactions, architecture
  understanding, or debugging on a live cluster, **load the relevant
  domain doc** from `P.domain_docs`.
- If the user asks to "load all context", comply — but default to lazy.

This keeps the context window lean for multi-repo projects where you
typically work in one repo at a time.

---

## Notes

- Always use the Read tool for files, never cat via Bash
- Use Bash for `ls`, `find`, and `mkdir -p` operations
- If no context file exists, ask the user for context — don't fabricate one
