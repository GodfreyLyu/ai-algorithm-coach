<!-- File purpose: Describe the logical local records and their consistency rules. -->

# Data model

This is the logical model. The complete schema is defined in the schema module.
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
| `training_profile` | `standard` | Standard rules or the opt-in interview profile. |

Changing saved configuration does not rewrite a published plan.
The standard profile has no phase quota system. A policy `max_daily_count` is the optional
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
| Learning state | Rebuildable problem and topic evidence derived from current records. |
| Learning checkpoint | Confirmed state with covered versions, rule context, and evidence coverage. |
| History evidence | Supporting records with an optional attempt link. |
| Solution evidence | Immutable code bound to one feedback revision. |
| Complexity review | Scoped host analysis of one solution version. |
| Training context | Native practice identity and researched framework or selection context. |
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

## Current schema

Schema version 4 is the runtime contract. New workspaces create it directly.
Compatible existing workspaces use the same model. A different version returns a
schema mismatch without rewriting data. External maintenance must prepare a
compatible store before the Skill can use it.

A learning checkpoint is independent of the derived `learning_state` projection.
It records confirmed state, covered feedback and assessment versions, the rule
version, and evidence coverage. The interview profile continues from compatible
checkpoints after checking the rule version. The standard profile uses full
attempt evidence and reports `checkpoint_profile_unsupported` for a partial
checkpoint. Complete evidence permits a full replay. Older corrections require
reconciliation. The core must not invent evidence or retain an unsupported streak.

## Original and derived records

Feedback history is retained. A correction does not delete an earlier revision.
Current learning state is a projection of effective attempt evidence.
It must not count an erroneous superseded claim as another practice attempt.
Rule and configuration context must be explicit when rebuilding state.

Self-reported complexity and result claims are unverified data.
Host-model assessments use separate immutable source, method, scope, and code
evidence records. They do not change self-reports into online-judge verification.
See [code reviews and learning evidence](reviews.md).

Topic scores are read-only projections, not another learning authority.
For one language, use each problem's latest valid effective A-D attempt result.
Each topic reports its independent A percentage, sample size, result counts,
and existing stable-mastery count. No samples means no score. See the
[score definition](web.md#topic-scores). The UI score does not change mastery
or selection rules and needs no additional persistence tables.
Practice progress is the same kind of projection. It groups current results by
practice date and lists each problem's latest A-D result. It adds no tables.

## Storage boundary

SQLite is the only authority in the local mode.
The catalog shipped with the code contains public metadata only.
No chat summary, Markdown ledger, browser cache, or second database can replace
the saved feedback history.

An eventual move to a remote authority needs a separate data cutover.
An unavailable remote service must not silently cause a second local authority.

Catalog discovery adds no schema or problem fields. Candidate files keep the
five-field problem model. A preview is an ephemeral read-only result. Its
`payload_hash` uses the same normalized operation content as an import receipt.
Source URLs, query times, and Agent field checks belong in a separate private
report. They are not program-verified correctness claims or saved learning state.
