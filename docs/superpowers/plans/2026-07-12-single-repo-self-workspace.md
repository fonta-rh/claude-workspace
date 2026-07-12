# Single-Repo Self-Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make single-repo, no-domain workspaces first-class: a `self:` block in `dev-env.yaml`, bootstrapped by `setup.sh init --self` + the setup-environment skill, and understood by the new-project skill.

**Architecture:** A top-level `self:` block (`name`, `summary`) in `dev-env.yaml` marks a workspace that wraps the git repo it lives in. `repos:` keeps its exact current meaning (normally `[]` here), so repo-iterating code is untouched. Bootstrap logic lives in `setup.sh` (testable); skills read the block and branch. The wrapped repo's own CLAUDE.md is never read or written by the plugin.

**Tech Stack:** bash (setup.sh + test_setup.sh), Markdown skill prose, YAML templates.

**Spec:** `docs/superpowers/specs/2026-07-12-single-repo-self-workspace-design.md`

## Global Constraints

- bash 3.2+ (macOS system bash): no associative arrays, no `${var,,}`.
- `self:` detection in bash must be grep-based (`^self:`) — no YAML parser dependency.
- `self:` and `domain:` are mutually exclusive; both present is an error.
- The plugin never reads or writes the wrapped repo's `CLAUDE.md`.
- Plugin root is read-only at runtime; scripts self-derive it; skills use `${CLAUDE_PLUGIN_ROOT}`.
- Commit messages: plain imperative, no `feat:`/`fix:` prefixes (matches repo history). End every commit message with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Run tests from the repo root: `bash tests/test_setup.sh`.

---

### Task 1: `setup.sh init --self` + self dev-env template

**Files:**
- Create: `templates/dev-env-self.yaml.template`
- Modify: `scripts/setup.sh` (header usage comment ~line 12-21, new `init_self()` after `init_domain()` ~line 796, `init` branch of `main()` ~line 908, `usage()` ~line 860)
- Test: `tests/test_setup.sh` (append a new group before the final summary block)

**Interfaces:**
- Produces: `setup.sh --workspace <ws> init --self [<name>]` — writes `<ws>/dev-env.yaml` with a `self:` block (`name` defaults to the workspace basename), creates `<ws>/projects/`, `.claude/settings.local.json` (template merge), `.claude/skills/`. Refuses (exit 1) when `<ws>` is not a git repo root or `dev-env.yaml` exists.
- Produces: template placeholder `__SELF_NAME__` (used only by `init_self`).
- Consumes: existing `apply_settings_template()` — called with `""` so it falls through to `$TEMPLATES_DIR/settings.local.json.tpl`; existing `ensure_skills_dir()` (already runs in the `init` branch of `main()`).

- [ ] **Step 1: Find where the new test group goes**

Open `tests/test_setup.sh` and locate the final results/summary block at the end of the file (the code after the last `group ...` section that prints totals and exits). The new group from Step 2 is appended immediately before that block. Note the helper conventions used by every group: `new_plugin`, `new_workspace`, `run_setup`, `cleanup`, and the `assert_*` functions defined at the top.

- [ ] **Step 2: Write the failing tests**

Append before the summary block:

```bash
# ─── init --self (single-repo self-workspace) ────────────────────────────────

group "init --self (single-repo self-workspace)"

plugin=$(new_plugin)
ws=$(new_workspace)
git init -q -b main "$ws"

assert_success "init --self succeeds in a git repo root" \
    run_setup "$plugin" "$ws" init --self myrepo
assert_file   "creates dev-env.yaml" "$ws/dev-env.yaml"
assert_contains "dev-env.yaml has a self: block" "$ws/dev-env.yaml" "^self:"
assert_contains "self block records the repo name" "$ws/dev-env.yaml" "name: myrepo"
assert_contains "repos list is empty" "$ws/dev-env.yaml" "^repos: \[\]"
assert_not_contains "no domain block" "$ws/dev-env.yaml" "^domain:"
assert_dir  "creates projects/" "$ws/projects"
assert_dir  "creates .claude/skills/" "$ws/.claude/skills"
assert_file "creates settings.local.json from template" "$ws/.claude/settings.local.json"

assert_failure "second init --self refuses (dev-env.yaml exists)" \
    run_setup "$plugin" "$ws" init --self myrepo

assert_success "clone is a clean no-op with empty repos" \
    run_setup "$plugin" "$ws" clone

cleanup "$ws"

ws=$(new_workspace)
git init -q -b main "$ws"
run_setup "$plugin" "$ws" init --self >/dev/null 2>&1
assert_contains "name defaults to the workspace basename" \
    "$ws/dev-env.yaml" "name: $(basename "$ws")"
cleanup "$ws"

ws=$(new_workspace)
assert_failure "init --self refuses a non-git directory" \
    run_setup "$plugin" "$ws" init --self myrepo
cleanup "$ws" "$plugin"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `bash tests/test_setup.sh`
Expected: the new group's asserts FAIL (e.g. "init --self succeeds in a git repo root" fails — `init_domain` treats `--self` as a domain name and errors "Domain '--self' not found"). All pre-existing groups still pass.

- [ ] **Step 4: Create `templates/dev-env-self.yaml.template`**

```yaml
# Dev Environment Configuration — single-repo self-workspace
# ===========================================================
#
# This workspace wraps the git repo it lives in: the workspace root IS the
# repo checkout. There is no domain, and nothing to clone for the repo
# itself. Generated by:  setup.sh init --self  (via /workspace:setup-environment)
#
# Schema:
#
#   self:                    # Marks this as a single-repo self-workspace
#     name: <repo-name>      # Short name of the wrapped repo
#     summary: <one-liner>   # Brief description (used by workspace skills)
#
#   repos: []                # Optional extra reference repos — same schema as
#                            # multi-repo workspaces (name/url/branch/category/
#                            # summary); cloned under repos/ by setup.sh clone.
#
# `self:` and `domain:` are mutually exclusive.
#
# Isolation model: edit-in-place. /workspace:new-project creates pure
# context/tracking projects under projects/; you edit this checkout directly
# on whatever branch you choose.

self:
  name: __SELF_NAME__
  summary: ""

repos: []
```

- [ ] **Step 5: Add `init_self()` to `scripts/setup.sh`**

Insert after the closing `}` of `init_domain()` (currently line 796), before the `# ─── Refresh Domain` divider:

```bash
# ─── Init Self (single-repo workspace) ───────────────────────────────────────
# The workspace root IS the wrapped repo checkout. No domain, nothing to
# clone; dev-env.yaml gets a self: block and an empty repos list.

init_self() {
    local name="${1:-}"

    if [[ ! -d "$WORKSPACE_ROOT_RESOLVED/.git" ]]; then
        log_error "Not a git repository root: $WORKSPACE_ROOT_RESOLVED"
        log_info "A self-workspace wraps an existing repo checkout."
        log_info "Run with --workspace pointing at the repo root."
        exit 1
    fi

    if [[ -f "$DEV_ENV_YAML" ]]; then
        log_error "dev-env.yaml already exists: $DEV_ENV_YAML"
        log_info "This workspace is already initialized. Edit the file directly,"
        log_info "or remove it and re-run 'init --self' to start over."
        exit 1
    fi

    [[ -z "$name" ]] && name="$(basename "$WORKSPACE_ROOT_RESOLVED")"

    sed "s/__SELF_NAME__/$name/" "$TEMPLATES_DIR/dev-env-self.yaml.template" \
        > "$DEV_ENV_YAML"
    log_success "Initialized dev-env.yaml (self-workspace: $name)"

    mkdir -p "$WORKSPACE_ROOT_RESOLVED/projects"
    apply_settings_template ""

    echo
    log_info "Next steps:"
    log_info "  Fill in self.summary in dev-env.yaml"
    log_info "  /workspace:new-project — scaffold a task under projects/"
}
```

(`apply_settings_template ""` is safe: with an empty domain dir the `-f "/settings.local.json.tpl"` check is false and it falls through to `$TEMPLATES_DIR/settings.local.json.tpl`.)

- [ ] **Step 6: Route `init --self` in `main()`**

In the `case "$action"` block, replace:

```bash
        init)
            resolve_workspace_root create
            init_domain "$target"
            ensure_skills_dir
            ;;
```

with:

```bash
        init)
            resolve_workspace_root create
            if [[ "$target" == "--self" ]]; then
                init_self "${3:-}"
            else
                init_domain "$target"
            fi
            ensure_skills_dir
            ;;
```

(`$3` is the third positional after `set -- "${positionals[@]}"` — the optional repo name.)

- [ ] **Step 7: Document the command in the header comment and `usage()`**

In the header usage comment (after the `init <url#subdir>` line, currently line 14), add:

```
#   setup.sh --workspace <path> init --self [<name>] Initialize a single-repo self-workspace
```

In `usage()`, after the `init <url#subdir>` echo line, add:

```bash
    echo "  init --self [<name>]  Initialize a single-repo self-workspace"
    echo "                        (workspace root = the repo checkout; no domain)"
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `bash tests/test_setup.sh`
Expected: PASS — all pre-existing asserts plus all 13 new ones.

- [ ] **Step 9: Commit**

```bash
git add templates/dev-env-self.yaml.template scripts/setup.sh tests/test_setup.sh
git commit -m "Add setup.sh init --self for single-repo self-workspaces

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Self-mode guards + schema documentation

**Files:**
- Modify: `scripts/setup.sh` (new `has_self_block()` helper near `parse_yaml_domain()` ~line 218, `detect_repo_source()` ~line 226, `refresh_domain()` ~line 800)
- Modify: `templates/dev-env.yaml.template` (schema comment block)
- Test: `tests/test_setup.sh` (append a second new group)

**Interfaces:**
- Consumes: Task 1's `init --self` (tests bootstrap self workspaces with it).
- Produces: `has_self_block [<yaml-file>]` — exit 0 iff the file has a top-level `self:` block (grep-based, defaults to `$DEV_ENV_YAML`). `refresh-domain` on a self workspace exits 1 with a message containing "single-repo". `clone`/`update`/`status`/`list` exit 1 when both `self:` and `domain:` are present.

- [ ] **Step 1: Write the failing tests**

Append after Task 1's group in `tests/test_setup.sh`:

```bash
# ─── Self-mode guards ─────────────────────────────────────────────────────────

group "self-mode guards"

plugin=$(new_plugin)
ws=$(new_workspace)
git init -q -b main "$ws"
run_setup "$plugin" "$ws" init --self myrepo >/dev/null 2>&1

out=$(run_setup "$plugin" "$ws" refresh-domain 2>&1)
assert_failure "refresh-domain refuses on a self workspace" \
    run_setup "$plugin" "$ws" refresh-domain
assert_output_contains "refresh-domain explains it is a self workspace" \
    "single-repo" "$out"

printf 'domain:\n  name: fake\n  source: bundled\n' >> "$ws/dev-env.yaml"
assert_failure "clone rejects self: and domain: together" \
    run_setup "$plugin" "$ws" clone
out=$(run_setup "$plugin" "$ws" clone 2>&1)
assert_output_contains "mutual-exclusion error names both blocks" \
    "mutually exclusive" "$out"
cleanup "$ws" "$plugin"
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `bash tests/test_setup.sh`
Expected: "refresh-domain refuses on a self workspace" PASSES already (it exits 1 with "No domain recorded"), but "refresh-domain explains it is a self workspace" and "mutual-exclusion error names both blocks" FAIL; "clone rejects self: and domain: together" FAILS (clone happily proceeds).

- [ ] **Step 3: Add `has_self_block()`**

Insert in `scripts/setup.sh` immediately after the closing of `parse_yaml_domain()` (before the `# ─── Repo Source Detection` divider):

```bash
# Returns 0 if a dev-env.yaml declares a top-level self: block (single-repo
# self-workspace). grep-based so it needs no YAML parser (hook-safe).
has_self_block() {
    local yaml_file="${1:-$DEV_ENV_YAML}"
    grep -q '^self:' "$yaml_file" 2>/dev/null
}
```

- [ ] **Step 4: Enforce mutual exclusion in `detect_repo_source()`**

Replace the body of the `if [[ -f "$DEV_ENV_YAML" ]]` branch:

```bash
detect_repo_source() {
    if [[ -f "$DEV_ENV_YAML" ]]; then
        REPO_SOURCE="$DEV_ENV_YAML"
        local domain_info
        domain_info=$(parse_yaml_domain "$DEV_ENV_YAML")
        ACTIVE_DOMAIN_NAME="${domain_info%%|*}"
        if [[ -n "$ACTIVE_DOMAIN_NAME" ]] && has_self_block; then
            log_error "dev-env.yaml declares both 'self:' and 'domain:' — they are mutually exclusive."
            log_info "Remove one of the two blocks from: $DEV_ENV_YAML"
            exit 1
        fi
    else
```

(The `else` branch and everything below it are unchanged.)

- [ ] **Step 5: Make `refresh-domain` self-aware**

In `refresh_domain()`, immediately after the existing `dev-env.yaml` existence check:

```bash
    if has_self_block; then
        log_error "This is a single-repo self-workspace — no domain to refresh."
        log_info "Self-workspaces have no domain; edit dev-env.yaml directly."
        exit 1
    fi
```

- [ ] **Step 6: Document `self:` in the multi-repo template's schema comment**

In `templates/dev-env.yaml.template`, after the `domain:` schema lines (ending `#     subdir: <subdir> ...`) and before the `#   repos:` line, insert:

```
#
#   self:                        # Single-repo self-workspace marker — the
#     name: <repo-name>          # workspace root IS the repo checkout.
#     summary: <one-liner>       # Generated by `setup.sh init --self`;
#                                # mutually exclusive with `domain:`.
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `bash tests/test_setup.sh`
Expected: PASS — all groups green.

- [ ] **Step 8: Commit**

```bash
git add scripts/setup.sh templates/dev-env.yaml.template tests/test_setup.sh
git commit -m "Guard self-workspaces: refresh-domain refusal, self/domain exclusion

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: setup-environment skill — self-repo path

**Files:**
- Modify: `skills/setup-environment/SKILL.md`

**Interfaces:**
- Consumes: `setup.sh init --self [<name>]` from Task 1 (exact behavior incl. refusal cases).
- Produces: skill prose defining the "Self-Repo Path" (steps S1-S4) referenced in the Task 5 docs.

- [ ] **Step 1: Update frontmatter and intro**

Change the frontmatter `description` to:

```yaml
description: Set up or refresh a workspace — multi-repo from a domain (pick a location, clone repos, distribute context) or a single-repo self-workspace wrapping the current checkout
```

After the first intro paragraph ("You are helping a developer bootstrap..."), add:

```markdown
Two modes exist. **Multi-repo (domain)**: a user-chosen directory gets
`dev-env.yaml`, cloned repos under `repos/`, and distributed context.
**Single-repo (self)**: the workspace root IS an existing repo checkout —
no domain, no cloning, and the plugin's only footprint is `dev-env.yaml`,
`projects/`, and `.claude/settings.local.json`. Step 0 picks the mode.
```

- [ ] **Step 2: Insert the mode fork as the new Step 0**

Rename the existing `## Step 0: Choose the Workspace Location` heading to `## Step 0a: Choose the Workspace Location (multi-repo path)` and insert before it:

```markdown
## Step 0: Choose the Mode

**If `$ARGUMENTS` is a git URL**, skip this question — that is an external
domain (multi-repo path); go to Step 0a.

Check whether the launch directory is inside a git repository:

```bash
git rev-parse --show-toplevel 2>/dev/null
```

- **If it is**, and that repo root has no `dev-env.yaml` yet, ask via
  AskUserQuestion:
  - **"Wrap this repo (`<basename of repo root>`) as a single-repo
    workspace"** — set `$WS` = the repo root and jump to the
    [Self-Repo Path](#self-repo-path-single-repo-workspace).
  - **"Multi-repo workspace from a domain"** — continue with Step 0a.
- **If it is not a git repo** (or the repo root already has a
  `dev-env.yaml`), continue with Step 0a.
```

- [ ] **Step 3: Make the refresh check self-aware**

In `## Step 0.5: Check for an Existing Domain (refresh path)`, after the sentence "Check if `$WS/dev-env.yaml` already exists and contains a `domain:` block.", add:

```markdown
If it exists and contains a top-level `self:` block instead, this is a
single-repo self-workspace — tell the user it is already set up (there is
no domain to refresh; `dev-env.yaml` is edited directly) and stop.
```

- [ ] **Step 4: Add the Self-Repo Path section**

Insert before the `---` that precedes `## Important Notes`:

````markdown
## Self-Repo Path (single-repo workspace)

No domain, no cloning. **Never read or modify the repo's own CLAUDE.md** —
orientation for future sessions comes from the SessionStart hook (recent
projects), per-project CLAUDE.md files, and `dev-env.yaml`.

### S1: Initialize

Run via Bash (`<name>` = the repo root's basename; confirm with the user
first if it looks generic, e.g. `src` or `repo`):

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh" --workspace "$WS" init --self <name>
```

If it refuses because `dev-env.yaml` already exists, the workspace is
already initialized — tell the user and stop.

### S2: Fill in the summary

Suggest a one-line summary of the repo from its `README.md` (Read tool),
or ask the user if there is none. Confirm it, then Edit
`$WS/dev-env.yaml`, replacing `summary: ""` in the `self:` block with the
confirmed line (YAML-quoted).

### S3: projects/ tracking

Ask via AskUserQuestion whether per-task project docs under `projects/`
should be tracked in git:

- **"Track in git (Recommended)"** — project docs are real docs; nothing
  to do.
- **"Ignore"** — append a `projects/` line to `$WS/.gitignore` (Edit, or
  Write if the file doesn't exist).

### S4: Summary

Present:

- What was created: `dev-env.yaml` (self block), `projects/`,
  `.claude/settings.local.json`.
- The isolation model: edit-in-place — `/workspace:new-project` creates
  context/tracking projects under `projects/`; code changes happen
  directly in this checkout on whatever branch the user picks.
- **Next step:** "Launch `claude` from `$WS` for future sessions — the
  SessionStart hook will surface recent projects."
- Offer — **print, never write** — a snippet the user may paste into
  their repo's CLAUDE.md:

  ```markdown
  ## Task Workflow

  Per-task context lives under `projects/<task>/`, managed by the
  `workspace` plugin: `/workspace:new-project` scaffolds a task,
  `/workspace:resume-project` reloads one. Launch `claude` from the repo
  root so the workspace resolves.
  ```
````

- [ ] **Step 5: Validate**

Run: `claude plugin validate . --strict`
Expected: validation passes with no errors.

- [ ] **Step 6: Commit**

```bash
git add skills/setup-environment/SKILL.md
git commit -m "Add single-repo self-workspace path to setup-environment skill

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: new-project skill — self-mode branching

**Files:**
- Modify: `skills/new-project/SKILL.md`

**Interfaces:**
- Consumes: the `self:` block schema (`self.name`, `self.summary`) from Task 1.
- Produces: nothing downstream — resume/close/update/consolidate need no changes (self projects keep today's `repos: []` frontmatter shape).

- [ ] **Step 1: Add the self-workspace branch to Step 1d**

In `skills/new-project/SKILL.md`, Step **1d. Related Repositories**, insert before item 1 ("Read `$WS/dev-env.yaml`..."):

```markdown
**Single-repo self-workspace check:** if `$WS/dev-env.yaml` has a
top-level `self:` block, this workspace wraps the repo it lives in.
Note `self.name` and `self.summary` for the Step 4 summary, then **skip
steps 1d, 1e, and 1g entirely** — no repo selection (the repo is
implicit), no worktrees (edit-in-place: code changes happen directly in
the checkout on a branch the user picks), and no skill linking (the
repo's `.claude/skills/` already is the workspace's). In step 1f, do not
create PR worktrees — record any PR URL in `related_links:` only. The
project frontmatter uses `repos: []` and omits `branch:`, `worktrees:`,
and `skills:`.
```

- [ ] **Step 2: Add the edit-in-place reminder to Step 4**

In `## Step 4: Suggest Skills and Next Steps`, after item 2 (the worktree listing), add:

```markdown
2b. In a single-repo self-workspace, remind instead: code changes happen
    directly in this checkout — suggest creating a git branch named after
    the project folder before starting.
```

- [ ] **Step 3: Validate**

Run: `claude plugin validate . --strict`
Expected: validation passes with no errors.

- [ ] **Step 4: Commit**

```bash
git add skills/new-project/SKILL.md
git commit -m "Skip repo/worktree/skill steps in new-project for self-workspaces

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Repo docs

**Files:**
- Modify: `CLAUDE.md` (plugin repo root — this is developer documentation for the plugin, NOT a wrapped repo's CLAUDE.md; editing it is in scope)

**Interfaces:**
- Consumes: names/paths introduced in Tasks 1-4.

- [ ] **Step 1: Update the Layout block**

In `CLAUDE.md`'s Layout code block, change the templates line to:

```
templates/{dev-env.yaml.template, dev-env-self.yaml.template, settings.local.json.tpl}
```

- [ ] **Step 2: Add a Key Conventions bullet**

Append to the `## Key Conventions` list:

```markdown
- **Single-repo self-workspaces**: a top-level `self:` block (`name`,
  `summary`) in `dev-env.yaml` marks a workspace whose root IS the wrapped
  repo checkout (`setup.sh init --self`). Mutually exclusive with
  `domain:`; `repos:` keeps its normal meaning (usually `[]`). Detection
  in bash is grep-based (`has_self_block`). The plugin never touches the
  wrapped repo's CLAUDE.md.
```

- [ ] **Step 3: Run the full suite + validation one last time**

Run: `bash tests/test_setup.sh && claude plugin validate . --strict`
Expected: all tests pass; validation clean.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "Document single-repo self-workspace mode in repo docs

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Migrate the means workspace (acceptance test)

**Files:**
- Modify: `/Users/pfontani/Workspace/means/dev-env.yaml` (OUTSIDE this repo — the user's reference use case; two-line addition, easily reverted)

**Interfaces:**
- Consumes: the `self:` block schema and the Task 2 guards.

- [ ] **Step 1: Add the self block**

Edit `/Users/pfontani/Workspace/means/dev-env.yaml`: above the existing `repos: []` line, add:

```yaml
self:
  name: means
  summary: "Bureaucratic desk game — the workspace wraps this checkout"

```

Leave the existing explanatory comments in place (they remain accurate; the user may trim them later).

- [ ] **Step 2: Verify the tooling reads it**

Run (from this repo's root, pointing setup.sh at means):

```bash
bash scripts/setup.sh --workspace /Users/pfontani/Workspace/means status
bash scripts/setup.sh --workspace /Users/pfontani/Workspace/means refresh-domain
WORKSPACE_ROOT=/Users/pfontani/Workspace/means \
    python3 scripts/resume-project.py act1-feedback-pass 2>&1 | head -5
```

Expected: `status` prints the empty repo table and exits 0; `refresh-domain` exits 1 with "single-repo self-workspace — no domain to refresh"; the resume script emits `"status": "ok"` JSON for the project.

- [ ] **Step 3: Report**

Do not commit anything in the means repo — show the user the diff of `dev-env.yaml` and the three command outputs, and note the optional follow-up (trimming the now-redundant workspace prose from means's CLAUDE.md and dev-env.yaml comments) is theirs to take.

---

## Self-Review Notes

- Spec coverage: schema (Task 1-2), bootstrap script (Task 1), guards/error handling (Task 2), setup-environment fork + self path incl. projects/-tracking question and print-only CLAUDE.md snippet (Task 3), new-project branching with zero changes to other lifecycle skills (Task 4), docs (Task 5), means migration acceptance (Task 6). Testing requirements map to Tasks 1-2 (test_setup.sh) and 3-5 (`claude plugin validate`).
- Type/name consistency: `has_self_block`, `init_self`, `__SELF_NAME__`, `dev-env-self.yaml.template`, and `init --self [<name>]` are used with identical spelling across tasks.
