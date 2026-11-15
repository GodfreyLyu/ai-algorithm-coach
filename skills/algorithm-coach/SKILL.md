---
# File purpose: Guide algorithm training through the bundled durable local core.
name: algorithm-coach
description: Start daily algorithm training, continue unfinished attempts, record feedback, or discover and import problem metadata with the host's network tools. Use for an ongoing training catalog and record, not general coding questions alone.
---

# Algorithm Coach

Use the bundled tool as the only authority for plans and learning records.
Do not maintain a competing chat or Markdown ledger.

## Local capability and setup

The host needs Python 3.12 or later with SQLite, local tool execution, and a private
persistent data directory. The standalone Skill bundle includes its Python core.
The core path needs no web server or model API key. A Web bundle can also start
its local feedback panel. Read [Web setup](references/web.md) when installing,
configuring, or diagnosing that optional panel.

Use `scripts/coach.py` relative to this Skill directory.
Use `ALGORITHM_COACH_DATA_DIR` from the host environment when it is already set.
Otherwise resolve one private absolute data directory with the user and reuse it.
Pass `--data-dir PATH` before the subcommand. Keep data outside this Skill folder.
Do not create another workspace merely because the current one is unavailable.

A directory alone is not a workspace. It must contain `coach.sqlite3`.
If it is empty or the tool reports `not_initialized`, report that fact and stop.
Ask for the existing database directory. Initialize a new workspace only when
the user explicitly authorizes it at a confirmed path. Import authorization alone
does not authorize initialization. Do not overwrite an existing store or use
initialization as migration.

`--data-dir` selects a path for one command. Initialization does not register it
globally or set `ALGORITHM_COACH_DATA_DIR`. An exported value applies to that
shell and its child processes. Other host sessions may need the path again.
Do not edit shell profiles or host configuration without a separate request.

For an authorized new workspace, confirm the timezone and initialize once:

```sh
python3.12 scripts/coach.py --data-dir /path/to/private/coach-data init --timezone UTC --language Java --daily-count 5
```

Use the host's supported Python executable if its name differs.
If tools or persistence are unavailable, tutoring can continue, but say feedback
has not been saved. Never invent a receipt or promise later automatic persistence.

## Daily training

Run `start-session` when starting or resuming daily interactive training. It
ensures the plan exists, then starts or reuses the optional local feedback panel.
Use `plan` for headless planning and `show` to read an existing plan.
For a UI-link-only request, check `web status` first. Return its verified URL
when ready. Do not run `start-session` just to obtain a link if plan creation
is not authorized. The CLI has no separate managed start-only command.
A status URL opens the service. It is not a date-bound session link.
Read [Web setup](references/web.md#ui-link-only-requests) for existing options.
Use the configured timezone. Use `--date YYYY-MM-DD` only for a requested date.
For a training session, read `data.plan` for the assignment. Present `data.web.url` only when
`data.web.status` is `ready`. The URL binds the returned date and store identity.
Return that exact link instead of inventing a fixed port or using today's browser date.
Service readiness is not a feedback save receipt. Do not claim a record is saved
until its write has a matching committed receipt.
A ready service can still have no plan for the selected date. Explain the empty
state. Once the user requests a plan, run `start-session` and return its ready
link. An already open page may need **Refresh** to show the saved assignment.

If Web is unavailable or disabled, keep the saved plan and continue chat feedback.
Explain the returned reason. Do not initialize a replacement workspace, install
packages, or rebuild the UI during ordinary training. Do not claim that a local
URL is accessible from a remote browser or survives host process cleanup.
Present official links and brief reasons. Use the returned attempt IDs internally.
Do not ask the user to copy IDs or plan JSON during normal conversation.

Use `capabilities` to check this tool's actual supported features.
The core resolves the active dated policy before allocating work.
Show paused backlog, paused reviews, blocked planning, and shortfall reasons.
Never fill a shortfall with out-of-scope problems.
Published plans stay frozen. Explain their current policy conflicts when reported.

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
python3.12 scripts/coach.py --data-dir /path/to/private/coach-data feedback --attempt ATTEMPT_ID --submission ACTION_ID --expected-revision 0 --changes '{"result":"D","elapsed_minutes":20}'
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
Manual practice must pass the same active scope checks.
Paused work keeps its original feedback; it is not E, F, or complete.
Feedback for an older attempt can still be recorded outside today's scope.

A, B, C, complexity, proficiency, and boundary-test entries are self-reports.
Do not label them verified. One A is not stable mastery.
Explain mastery as the outcome of the recorded spacing rules and evidence.

## Scope policies and metadata

Read [catalog discovery](references/catalog-discovery.md) when the user asks to
find, recommend, verify, or import new problem metadata. First read `catalog`,
`capabilities`, and the effective `policy get` for the requested training dates.
Network access comes from the host's tools. The Skill and Python core do not
fetch websites; `remote_fetch` remains false. If the host cannot browse, say so
and offer the same preview and import path for a user-provided metadata file.

Finding or recommending problems authorizes a candidate report and read-only
preview. It does not authorize import. An explicit request to search and import,
or to expand the catalog, authorizes that bounded batch without per-item approval.
Require source checks for discovered candidates. For a user-provided file, report
any source checks the host could not perform. Obey the request's limits. Catalog
expansion does not authorize a training scope change or a rewrite of today's plan.

Read [policy operations](references/policies.md) when the user changes training
topics, difficulties, allowed or excluded problems, preferred topics, scope dates,
daily allocation limits, or catalog metadata. Also read it for legacy migration.

Use proposal, read-only preview, and exact-hash activation as separate operations.
Use global `latest_revision` for concurrency, not the date-effective revision.
Show the concrete proposal and preview, then obtain explicit approval before
activation. A model-written confirmation flag is not proof of user approval.
Do not infer that an expired policy still restricts training. Show its fallback.
Never edit stored policy revisions or bypass scope through manual practice.

## Maintenance commands

Use `config` to read saved settings. Changes need `--changes JSON` and
`--expected-revision N`. Do not reconfigure the user each day.
Use `catalog` for problem metadata and official links.
Use `migrate` only as the explicit schema version 1 upgrade with a backup.
Use `backup --output NEW_PATH` for a consistent backup.
Use `check` for integrity and `rebuild-state` to rebuild derived state when requested.
Backups and records are private. Do not export them for a public example.

The optional feedback panel runs only on the local computer. A Web bundle needs
its optional Python dependencies installed once. Remote access, a running MCP
server, cloud authentication, and deployment are not included.
