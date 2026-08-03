# Checkpoint Handoff — Design

**Date:** 2026-07-31
**Status:** Approved, ready for implementation planning

## Problem

The established way to work a long task in this plugin is to find a natural
breaking point and then run three things in sequence:

```
/workspace:update-project     # write what happened into the project docs
/clear                        # drop the spent context
/workspace:resume-project     # reload the minimum needed to continue
```

The middle step is the point of the exercise; the two around it are
bookkeeping. The third is especially wasteful, because the session that just
ended already knew exactly what came next and had to answer a task-selection
menu to say so again.

Collapsing all three into one command is **impossible**, and it is worth
recording why so nobody re-litigates it. `/clear` is a client-side control.
Claude cannot invoke it: the skills documentation states that only a few
built-in commands are reachable through the Skill tool — `/init`, `/review`,
and `/security-review` — and that others such as `/compact` are not. Nothing
a skill or hook can do will clear the context it is running in. Any design
that spans the clear boundary must therefore hand state across it rather than
issue a command through it.

## Goal

Reduce the sequence to two actions — one command and one keystroke — by making
the resume half automatic:

```
/workspace:checkpoint         # update docs, arm a handoff
/clear                        # the one thing only the user can do
                              # -> next session resumes on its own
```

A `/clear` with no armed handoff must behave exactly as it does today.

## Mechanism

Verified properties of the hook API that make this work:

| Property | Consequence |
| --- | --- |
| `SessionStart` fires on `/clear` with `source: "clear"` (matcher `clear`) | The new session can know it was born from a clear |
| `SessionStart` supports `hookSpecificOutput.additionalContext`, with no matcher restriction | Context can be injected with zero user typing |
| `SessionStart` supports only `command` and `mcp_tool` hook types | No model reasoning at the boundary itself |
| Matchers of letters, digits, `_`, `-`, spaces, `,`, `|` are exact-string lists, not regex | `startup\|resume\|fork\|compact` is a valid matcher |

`initialUserMessage` was considered and rejected: the documentation scopes it
to non-interactive `-p` mode, and its sibling `sessionTitle` is explicitly
"ignored on `clear` and `compact`". `additionalContext` is better regardless,
because it needs no keypress.

## Flow

```
-- session A --------------------------------------------
  /workspace:checkpoint
      1. invoke workspace:update-project via Skill tool
         -> project docs updated in-context (unchanged logic)
      2. handoff.py write --project X --next-task "..." --load-files a.md,b.md
         -> <workspace>/.claude/handoff.json
      3. print "Checkpoint saved. Press /clear."

  /clear

-- session B -- SessionStart, source=clear ---------------
  handoff.py read          (hook, matcher "clear")
      no marker / stale  -> exec recent-projects.py, exit   [today's behavior]
      fresh marker       -> delete it, emit additionalContext

  Claude reads the directive -> invokes workspace:resume-project X
      -> normal resume, Step 4 task menu replaced by loading the named files
      -> "Ready."
```

The marker is the only state that crosses the boundary, and it is deleted
before the directive is emitted, so a repeated `/clear` cannot re-fire it.

### The emitted directive

On a fresh marker, `handoff.py read` prints a `SessionStart` payload carrying
both a user-visible `systemMessage` and the `additionalContext` that steers
Claude:

```
Checkpoint handoff pending (saved 2 minutes ago).

Project: oadp-restore-hang
Next task: reproduce with restic disabled
Detail files: investigation.md, test-results.md

Invoke the workspace:resume-project skill with argument
`oadp-restore-hang`. In Step 4, skip the task menu: read the detail
files listed above and report readiness with the next task.
```

The age is rendered in words from `written_at` so the model and the user can
both judge whether the handoff still makes sense.

## The marker

Location: `<workspace>/.claude/handoff.json`.

```json
{
  "version": 1,
  "project": "oadp-restore-hang",
  "written_at": "2026-07-30T14:02:11+02:00",
  "next_task": "reproduce with restic disabled",
  "load_files": ["investigation.md", "test-results.md"]
}
```

Deliberately small. Frontmatter, checklist counts, worktree status, domain
docs, and linked skills are all recomputed from disk by `resume-project.py`;
copying them into the marker would create a second source of truth that can go
stale.

`load_files` are relative to the project directory, matching how the Reference
Files table already stores them. `next_task` is the departing model's
judgment, not merely the first unchecked checklist item — that judgment is the
thing that would otherwise be lost across the clear.

**Why workspace-local rather than the plugin data directory.** Locality gives
per-workspace isolation for free: two workspaces have two roots, so two
markers, with no hashing scheme and no shared-directory contention. A
plugin-data location keyed by a hash of the workspace root was considered on
the grounds that a single-repo self-workspace has the workspace root inside a
real repo checkout, but `setup.sh init --self` already writes `dev-env.yaml`,
`projects/`, and `.claude/settings.local.json` into that checkout. `.claude/`
is already the plugin's, and the marker is covered by whatever the user
already does about those untracked paths. (Self-workspace mode lives on the
unmerged `single-repo-self-workspace` branch; this reasoning is recorded so it
survives the merge.)

## Lifetime

Single-use, with a time budget:

- Deleted the moment it is consumed.
- Ignored and deleted if older than **60 minutes**.
- A negative age (clock skew) is treated as fresh rather than discarded.

This is forgiving of a message or two between checkpoint and clear, while
preventing a marker forgotten in the morning from firing on an unrelated clear
that evening.

## Components

| File | Change |
| --- | --- |
| `scripts/handoff.py` | new — yaml-free; `write` and `read` subcommands |
| `skills/checkpoint/SKILL.md` | new — thin; delegates to update-project |
| `skills/resume-project/SKILL.md` | edit — one branch in Step 4 |
| `hooks/hooks.json` | edit — matchers on both entries |
| `tests/test_handoff.py` | new |
| `CLAUDE.md`, `README.md` | docs — skill table, layout, conventions |

### `scripts/handoff.py`

Imports limited to `json`, `datetime`, `pathlib`, `argparse`, and
`workspace_lib`. **No PyYAML**, preserving the rule that the SessionStart hook
never needs a third-party dependency.

```
handoff.py write --project NAME --next-task TEXT [--load-files a.md,b.md]
    -> {"status":"ok","path":...} | {"status":"error","message":...}

handoff.py read          # hook mode
    -> fresh marker : delete it, print the SessionStart JSON payload
    -> otherwise    : os.execv into recent-projects.py   (today's behavior)
```

The `execv` passthrough is what preserves the existing banner on a normal
clear without duplicating its rendering. Folding the banner into
`workspace_lib.py` so both scripts could import it was rejected:
`recent-projects.py` contains a hyphen and is not importable, so that route
forces a rename or a module extraction for a cosmetic gain.

### `skills/checkpoint/SKILL.md`

Frontmatter carries `disable-model-invocation: true`, following the
documented guidance for side-effecting commands like `/commit` and `/deploy`.
Claude should not arm a handoff on its own.

1. Resolve the project exactly as `update-project` Step 1 does: the project
   already loaded in this conversation, else the `$ARGUMENTS` token, else ask.
   Deliberately **no** `resume-project.py` call — the departing context is the
   one being wound down, and loading that JSON merely to learn a name is the
   cost this feature exists to avoid.
2. Invoke `workspace:update-project` via the Skill tool. All document writing
   happens there, under its existing scope rules.
3. From the docs just written, decide `next_task` and `load_files`.
4. Run `handoff.py write`. On error, report it and **do not** tell the user to
   clear.
5. Report: "Checkpoint saved. Press `/clear`."

### `skills/resume-project/SKILL.md`

Step 4 gains a preamble: if the SessionStart context carried a handoff (a
project, a next task, and detail files), skip 4a and 4b, read the named detail
files, and report readiness with the next task. Steps 4d–4f continue as
normal. No other step changes.

### `hooks/hooks.json`

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|fork|compact",
        "hooks": [
          { "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/recent-projects.py\"" }
        ]
      },
      {
        "matcher": "clear",
        "hooks": [
          { "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/handoff.py\" read" }
        ]
      }
    ]
  }
}
```

## Error handling

Governing rule: **`handoff.py read` always exits 0 and never crashes a session
start.** A top-level try/except falls through to the passthrough.

| Condition | Behavior |
| --- | --- |
| No marker | Passthrough to banner |
| Corrupt JSON, missing keys, `version != 1` | Delete, passthrough |
| Age > 60 min | Delete, passthrough |
| Age negative (clock skew) | Treat as fresh |
| Workspace root unresolvable | Exit 0 silent, matching `recent-projects.py` |
| Project directory missing at **write** | Error JSON; handoff not armed; user not told to clear |
| Project gone at **read** | Directive still emitted; `resume-project.py` returns `not_found` and the skill's existing picker handles it |
| PyYAML missing | `handoff.py` unaffected; `resume-project.py`'s existing self-describing error path relays the install command |

If the handoff never fires for any reason, `/workspace:resume-project` by hand
still recovers everything, because step 1 of `/checkpoint` already wrote it all
to disk. The marker is best-effort connective tissue; anything that matters
belongs in the project documents.

## Testing

`tests/test_handoff.py` — stdlib `unittest`, subprocess-driven against a
throwaway workspace with `WORKSPACE_ROOT` set, mirroring `test_skills.py`.

Cases:

- `write` round-trip produces a well-formed marker
- fresh marker: directive emitted **and** file deleted
- stale marker: passthrough and file deleted
- corrupt marker: passthrough and file deleted
- absent marker: passthrough
- unresolvable workspace root: silent, exit 0
- `write` against a nonexistent project: error status, no file created

Passthrough cases assert byte-equality against `recent-projects.py` invoked
directly, which pins the no-regression guarantee for normal clears.

Two steps unit tests cannot cover, to be done manually:

- `claude plugin validate . --strict` after editing `hooks.json`
- one live run (`claude --plugin-dir .` → `/workspace:checkpoint` → `/clear`)
  to confirm the `clear` matcher actually fires; this is the only link in the
  chain that solely the harness can exercise

## Out of scope

**Breaking-point detection.** A `prompt`- or `agent`-type `Stop` hook could
watch for the shape of a natural breaking point (checklist item closed, tests
green, commit landed) and suggest checkpointing, automating the judgment call
rather than the mechanics. `Stop` does support those hook types. This is a
deliberate follow-up, to be designed once the mechanism above is working.

**Firing on `startup`.** A checkpoint followed by quitting and relaunching
produces `source: "startup"`, not `"clear"`, so the handoff will not fire.
Excluded as speculative; it is a one-word matcher change if it proves annoying
in practice.
