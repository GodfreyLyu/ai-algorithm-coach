<!-- File purpose: Describe the logical local records and their consistency rules. -->

# Data model

This is the logical model. The schema implementation is in the storage module.
Read it together with [feedback semantics](feedback-semantics.md).

## Saved configuration

`config` returns its optimistic `revision` and a `config` object.
Updates use a partial changes object and the expected revision.

| Field | Default | Meaning |
| --- | --- | --- |
| `language` | `Java` | Language for new attempts. |
| `daily_count` | `5` | Generated plan capacity, including unfinished work. |
| `baseline_count` | `4` | Existing selection preference; not a phase quota. |
| `timezone` | `UTC` | IANA timezone for training dates. |
| `run_time` | `null` | Optional preferred local time; not an active timer. |
| `review_intervals` | `[3, 7]` | Required spacing between qualifying independent attempts. |
| `assisted_review_days` | `1` | Review delay after B or C. |
| `stable_review_days` | `30` | Maintenance review delay after stable evidence. |
| `skip_cooldown_days` | `7` | Default eligibility delay after a skipped attempt. |

Changing saved configuration does not rewrite a published plan.
No phase quota system is implemented. A policy `max_daily_count` is the optional
shared hard cap for manual and planned allocations. Without it, manual practice
is not implicitly capped by `daily_count`.

## Logical records

| Record | Role |
| --- | --- |
| Configuration | One saved configuration with an optimistic revision. |
| Problem | An ID, tags, difficulty metadata, title, and official link. |
| Daily plan | A frozen training date and the context used to choose its items. |
| Plan item | A position, problem, attempt reference, and selection reason. |
| Practice attempt | One unit of practice, with its language and practice context. |
| Feedback revision | An immutable progress or correction record for an attempt. |
| Learning state | Rebuildable problem and topic evidence derived from attempts. |
| Review | A due practice need linked to its evidence and execution attempt. |
| Submission receipt | A permanent operation ID, content identity, and committed result. |
| Policy proposal | An immutable normalized policy body, content hash, and base versions. |
| Activated policy | An immutable policy revision with inclusive effective dates. |
| Policy approval | An acceptance record bound to the exact activated content hash. |

## Relationships

One problem can have many attempts.
One attempt can appear in several daily plans when it is continued.
One attempt has an ordered feedback history.
Only separate attempts can contribute separate completion evidence.

A planned attempt may have no feedback yet. Its missing result remains unknown.
Creating a plan does not mean that its attempts were started or completed.
A review starts a separate attempt linked to earlier evidence.

## Identity and versions

The training date uniquely identifies a published plan within this workspace.
Attempt IDs identify feedback targets even when a plan spans several days.
Feedback revisions prevent stale edits from replacing new information.
Submission IDs identify operations across retries.

A submission stores a normalized content identity.
The same ID with the same content returns its stored result.
The same ID with different content is rejected.
The receipt remains meaningful after the request process exits.

Global policy `latest_revision` is the highest activated policy revision.
It is the compare-and-swap version for proposal and activation.
The policy `revision` effective on a queried date can be older or baseline 0.
A future activated policy still advances the global version.
Configuration, catalog, and learning-state versions are separate context.

Plans retain their policy snapshot. Current policy comparisons are diagnostics,
not changes to the stored assignment. Paused attempts and reviews retain identity
and feedback. They can become eligible again without reconstructing lost history.

## Schema migration

Schema version 2 stores policy history and imported metadata context.
Opening a version 1 store does not silently migrate it.
The explicit migration creates a consistent backup first, then changes schema and
version in one transaction. Failure rolls back the schema changes.
Practice IDs, plan history, feedback revisions, and receipts are preserved.

## Original and derived records

Feedback history is retained. A correction does not delete an earlier revision.
Current learning state is a projection of effective attempt evidence.
It must not count an erroneous superseded claim as another practice attempt.
Rule and configuration context must be explicit when rebuilding state.

Self-reported complexity and result claims are unverified data.
There is no automatic correctness-verification channel in the local MVP.
Future assessments need separate source, method, scope, and evidence records.

## Storage boundary

SQLite is the only authority in the local mode.
The catalog shipped with the code contains public metadata only.
No chat summary, Markdown ledger, browser cache, or second database can replace
the saved feedback history.

An eventual move to a remote authority needs an explicit migration and cutover.
An unavailable remote service must not silently cause a second local authority.
