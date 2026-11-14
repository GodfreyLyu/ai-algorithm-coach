---
# File purpose: Guide algorithm training through the bundled durable local core.
name: algorithm-coach
description: Plan daily algorithm practice, continue unfinished attempts, and record or correct training feedback through the bundled local Python tool. Use for an ongoing algorithm training record, not general coding questions alone.
---

# Algorithm Coach

Use the bundled tool as the only authority for plans and learning records.
Do not maintain a competing chat or Markdown ledger.

## Local capability and setup

The host needs Python 3.12 or later with SQLite, local tool execution, and a private
persistent data directory. The standalone Skill bundle includes its Python core.
It needs no web server or model API key.

Use `scripts/coach.py` relative to this Skill directory.
Use `ALGORITHM_COACH_DATA_DIR` from the host environment when it is already set.
Otherwise resolve one private absolute data directory with the user and reuse it.
Pass `--data-dir PATH` before the subcommand. Keep data outside this Skill folder.
Do not create another workspace merely because the current one is unavailable.

At first use, confirm the timezone and initialize once:

```sh
python3.12 scripts/coach.py --data-dir /path/to/private/coach-data init --timezone UTC --language Java --daily-count 5
```

Use the host's supported Python executable if its name differs.
If tools or persistence are unavailable, tutoring can continue, but say feedback
has not been saved. Never invent a receipt or promise later automatic persistence.

## Daily training

Run `plan` to ensure today's plan exists. Use `show` to read an existing plan.
Use the configured timezone. Use `--date YYYY-MM-DD` only for a requested date.
Present official links and brief reasons. Use the returned attempt IDs internally.
Do not ask the user to copy IDs or plan JSON during normal conversation.

The core sets capacity and candidate order. Unfinished work occupies daily slots.
Do not add new problems to satisfy a four-plus-extra preference after the cap is full.
Do not mark unselected backlog complete or skipped.
Repeated planning returns the same published plan.

Provide hints and explanations as requested. Keep model suggestions separate from
saved facts. The Skill cannot schedule itself or wake up in the background.

## Record feedback

Map a clear user response to its existing attempt. If the target or result is
ambiguous, ask only for the missing fact. Unanswered fields stay unanswered.

| Result | Meaning |
| --- | --- |
| A | User reports independent AC without hints. |
| B | User reports AC after hints. |
| C | User reports AC after reading an answer. |
| D | Not yet AC; continue this attempt. |
| E | Deferred; not complete. |
| F | Skip this attempt; not complete. |

Use `history --attempt ID` when the current revision is not known.
Create one stable submission ID for the user action.
Submit structured values using `feedback`:

```sh
python3.12 scripts/coach.py feedback --attempt ATTEMPT_ID --submission ACTION_ID --expected-revision 0 --changes '{"result":"D","elapsed_minutes":20}'
```

Build tool arguments safely. Do not interpolate arbitrary feedback into shell code.
Time is cumulative minutes for the attempt. It is not a retryable increment.
Optional fields include `blocked_on`, `explanation`, `boundary_tests`, `proficiency`,
`time_complexity`, `space_complexity`, `assistance`, `defer_until`, and `skip_until`.
Use tool help and validation errors for exact allowed values.
Omit untouched fields. Use `null` only when the user clearly clears a field.
Do not convert a missing boolean into `false`.

A committed matching receipt is required before saying feedback is saved and
applied. That statement does not mean the solution was verified correct.
The CLI wraps success as `ok: true` with a `data` object.
For feedback, check `data.status` is `applied`, and check its `submission_id`,
`attempt_id`, and `revision`. `payload_hash` identifies the submitted content.
An `ok: false` response is a failure, even if the process returned readable JSON.
If the command fails, say the feedback is not confirmed saved and retain its input.
After a timeout, query `receipt --submission ACTION_ID` or retry the identical
operation. Reuse its submission ID, expected revision, and content.
Do not loop indefinitely. After repeated failures, show the actionable error and
leave the submission unresolved.

## Progress, corrections, and reviews

Continuing D keeps the same attempt ID, even on a later date.
Known hint or answer dependence cannot become A through ordinary progress.
Use a new attempt for a genuinely independent redo or review.

If the user corrects a prior fact, use `--kind correction`, a new submission ID,
and the current expected revision. Keep the original history.
Preserve the original practice occurrence time for late corrections.
Use `--occurred-at` only for a known or explicitly supplied occurrence time.
For a revision conflict, read current history and resolve the difference with the
user. Do not silently overwrite another result.

Use `state` to read weak areas and due reviews after recording feedback.
Use `practice --problem ID --submission ACTION_ID` for an explicit new redo.
Add `--review ID` when starting a specific recorded review.

A, B, C, complexity, proficiency, and boundary-test entries are self-reports.
Do not label them verified. One A is not stable mastery.
Explain mastery as the outcome of the recorded spacing rules and evidence.

## Maintenance commands

Use `config` to read saved settings. Changes need `--changes JSON` and
`--expected-revision N`. Do not reconfigure the user each day.
Use `catalog` for problem metadata and official links.
Use `backup --output NEW_PATH` for a consistent backup.
Use `check` for integrity and `rebuild-state` to rebuild derived state when requested.
Backups and records are private. Do not export them for a public example.

The current release has no feedback Web App, remote API, running MCP server,
cloud authentication, or deployment. Do not claim those features are active.
