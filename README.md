<!-- File purpose: Describe the local training loop, setup, tests, and project scope. -->

# ai-algorithm-coach

A local algorithm coach with a durable training record.
The Skill handles the conversation. Python handles the rules. SQLite stores the facts.

This version completes the local Skill loop first. It needs no database server,
model API key, or web service. The planned feedback UI uses React with TypeScript
and FastAPI. That UI is not part of this version.

## What works

- Create a daily plan from saved records.
- Continue unfinished practice before adding new work.
- Record A–F results, time, and optional details.
- Keep feedback history and accept explicit corrections.
- Retry a submission without counting it twice.
- Derive weak areas and due reviews from recorded evidence.
- Back up the database and check its integrity.
- Package the core with the Skill for use outside this repository.
- Restrict training with dated, versioned scope policies.
- Preview a policy before a host-approved activation.
- Import additional problem metadata without replacing existing entries.
- Migrate a version 1 workspace explicitly, with a backup.

The default language is Java. The default daily plan target is five problems.
Unfinished work uses the same plan capacity. A large backlog can use every slot.
There is no implemented phase system or guaranteed four-plus-extra quota.
Language, daily total, timezone, preferred run time, and review rules are configurable.
Saving a preferred run time does not create a scheduled task.
Scope policies constrain eligibility. They do not replace the learning rules.

## Requirements

- Python 3.12 or later, with `sqlite3` and timezone data.
- A Skill host that can run local tools and access a private persistent directory.
- A local disk for the database.

A text-only chat client cannot guarantee durable feedback.
The Skill must report that feedback is not saved when it cannot run its tool.
Support for a particular AI client must be checked in that client.

## Quick start

Run these commands from the repository root. Replace the example data path.
Keep the data directory outside the repository. Choose your real timezone once.
`UTC` is the example, not a guess about your location.

```sh
export ALGORITHM_COACH_DATA_DIR="/path/to/private/coach-data"
python3.12 skills/algorithm-coach/scripts/coach.py init --timezone UTC --daily-count 5 --language Java
python3.12 skills/algorithm-coach/scripts/coach.py plan
```

The plan returns stable attempt IDs. Your Skill host uses those IDs internally.
You can then say, for example, "The first problem is D. I spent 20 minutes."
The Skill records the result through the tool and checks its receipt.
You do not need to paste plan data into the conversation each day.

For direct CLI use, replace the synthetic attempt ID below with one from the plan.
Choose one submission ID for this action. Reuse it only when retrying that action.

```sh
python3.12 skills/algorithm-coach/scripts/coach.py feedback \
  --attempt ATTEMPT_ID_FROM_PLAN \
  --submission example-first-feedback \
  --expected-revision 0 \
  --changes '{"result":"D","elapsed_minutes":20}'
python3.12 skills/algorithm-coach/scripts/coach.py state
python3.12 skills/algorithm-coach/scripts/coach.py plan
```

Calling `plan` twice returns the same published plan. It does not replace feedback.
The next training date can continue the same unfinished attempt.
Use `--date YYYY-MM-DD` to request a specific training date.

## Set a training scope

Policies can restrict topics, difficulties, or specific problem IDs.
They can exclude IDs, prefer topics, and set a shared daily allocation limit.
The unrestricted baseline is revision 0.

Read the current policy and its global `latest_revision` first:

```sh
python3.12 skills/algorithm-coach/scripts/coach.py capabilities
python3.12 skills/algorithm-coach/scripts/coach.py policy get
python3.12 skills/algorithm-coach/scripts/coach.py policy propose \
  --file examples/easy-arrays-policy.toml \
  --expected-revision 0 --submission example-policy-proposal
python3.12 skills/algorithm-coach/scripts/coach.py policy preview --proposal PROPOSAL_ID
```

The example uses `0` only for a workspace with no activated policy.
Use the actual `latest_revision` for every proposal and activation.
The date-effective `revision` can differ from this global concurrency version.

Inspect the exact proposed body, dates, hash, paused work, and fallback behavior.
Activation requires an explicit decision through the trusted host or direct CLI.
After approving that exact proposal, use its hash and the current global version:

```sh
python3.12 skills/algorithm-coach/scripts/coach.py policy activate \
  --proposal PROPOSAL_ID --accept-hash EXACT_PROPOSAL_HASH \
  --expected-revision 0 --submission example-policy-activation
```

Proposing or previewing does not activate a policy or publish a plan.
Omitting `effective_from` uses the next local training date.
Omitted scope fields inherit the policy resolved for that start date.
Omitting `effective_until` removes the end date; it does not inherit one.
An expired policy falls back to a prior applicable policy or the unrestricted
baseline. Preview that transition before approval.

Out-of-scope unfinished work and reviews stay visible as paused work.
Their feedback is unchanged. Feedback for an older attempt can still be recorded.
Published plans stay frozen and report any current policy conflict.
An activation that would conflict with published plans in its effective dates
is refused. Choose the next unpublished date or change the proposal.

`daily_count` limits a generated plan. A policy `max_daily_count` is a hard shared
limit for distinct daily allocations through planning and manual practice.
Without that policy limit, manual practice has no implicit cap from `daily_count`.
See [policy rules and approval](docs/policies.md) for fields and examples.

## Add problem metadata

```sh
python3.12 skills/algorithm-coach/scripts/coach.py catalog import \
  --file examples/catalog-extra.toml --submission example-catalog-import
```

Imports accept curated metadata only: ID, title, difficulty, tags, and an official
LeetCode link. Existing IDs cannot be changed. Exact repeats are safe.
URL validation does not prove that metadata is correct or that a solution is AC.
No remote scraping, full statement, paid content, or practice record is imported.

## Correct feedback

Read the current revision before making a new change.
A correction is a new immutable revision. It keeps the previous record.

```sh
python3.12 skills/algorithm-coach/scripts/coach.py history --attempt ATTEMPT_ID_FROM_PLAN
python3.12 skills/algorithm-coach/scripts/coach.py feedback \
  --attempt ATTEMPT_ID_FROM_PLAN \
  --submission example-correction \
  --expected-revision 1 \
  --kind correction \
  --changes '{"result":"C"}'
python3.12 skills/algorithm-coach/scripts/coach.py receipt --submission example-correction
```

Do not retry a failed action with a new submission ID until its original receipt
has been checked. A timeout does not prove that a write failed.

## Installable Skill bundle

Build into a new directory. The builder refuses to replace an existing destination.

```sh
python3.12 scripts/build_skill.py --output /path/to/new/algorithm-coach
```

The output includes `SKILL.md`, the entry script, and the Python core.
It does not need the source checkout at runtime.
Add that folder to a compatible host through its supported Skill mechanism.
This command does not install into any account or global Skill directory.

Configure the same private data directory in that host's tool environment.
If environment variables are unavailable, pass `--data-dir` before the subcommand.
Do not store private records inside the bundle.

## Commands

| Command | Purpose |
| --- | --- |
| `init` | Create the local workspace and save initial settings. |
| `plan` | Ensure that a plan exists for a training date. |
| `show` | Read an existing plan. |
| `feedback` | Append progress or a correction with a submission ID. |
| `history` | Read the revisions for one attempt. |
| `receipt` | Check one submission. |
| `state` | Read weak areas and review state. |
| `config` | Read settings or update them with an expected revision. |
| `practice` | Start an explicit redo or review as a new attempt. |
| `catalog` | Read problem metadata and official links. |
| `catalog import` | Append validated metadata from TOML or JSON. |
| `capabilities` | Read the supported local features and limits. |
| `policy get/history` | Read the effective policy, global version, or revision history. |
| `policy propose/preview/activate` | Prepare, inspect, and explicitly activate a scope policy. |
| `migrate` | Upgrade a version 1 database with a pre-migration backup. |
| `backup` | Write a consistent backup to a new destination. |
| `check` | Check database integrity and references. |
| `rebuild-state` | Rebuild derived learning state from stored records. |

Use `--help` for the exact options. Commands emit structured JSON.
No command sends training records to a remote service.

## Feedback meanings

| Result | Meaning |
| --- | --- |
| A | Reported independent AC, without hints. |
| B | Reported AC after a hint. |
| C | Reported AC after reading an answer. |
| D | Attempted but not yet AC. |
| E | Deferred. It is not complete. |
| F | Skipped for this attempt. It is not complete. |

A–C are user reports. They are not verified judge results.
One A does not mean stable mastery. Review rules use separate attempts on separate
dates. Revisions of one attempt never count as several independent completions.
See [feedback semantics](docs/feedback-semantics.md).

## Test

No third-party test dependency is required.

```sh
python3.12 -m unittest discover -s tests -v
python3.12 scripts/check_comments.py
python3.12 scripts/check_docs.py
```

Tests use synthetic records in temporary directories.
They cover the local feedback loop, repeat submissions, corrections, plan reruns,
review rules, backup recovery, and the standalone Skill bundle.
These tests do not establish compatibility with every AI client or deployment host.

Every PR to `main` runs named syntax, logic, and documentation checks.
See [GitHub Actions and owner review](docs/github-actions.md) for job names,
local commands, repository rules, and the owner-authored PR exception.

## Architecture and next steps

The core is independent of the conversation and transport.
CLI calls the same application service that a future API will call.
The SQLite database is the only authority for this local workspace.
Chat summaries and future browser caches are views or pending input.

See the [architecture](docs/architecture.md), [data model](docs/data-model.md),
[policy guide](docs/policies.md), [backup guide](docs/backup-restore.md),
and [future UI contract](docs/future-ui.md).

The next product phase adds React TypeScript forms and a FastAPI adapter.
It must preserve the same attempt IDs, feedback revisions, and receipts.
Remote API access, a running MCP server, cloud authentication, and deployment
are not implemented here. A Skill has no built-in scheduler.
An operating system or external service must trigger scheduled runs.

## Open source boundary

Examples and tests contain synthetic records only.
The catalog stores problem metadata and official links. It does not include full
problem statements, paid material, or any user's chat history.
There is no import from an existing private prototype.

The code uses the [MIT license](LICENSE).
Third-party problem names and linked content remain third-party material.
See [contribution rules](CONTRIBUTING.md) and the [security boundary](SECURITY.md).
External metadata and runtime boundaries are listed in [third-party notices](THIRD_PARTY_NOTICES.md).
