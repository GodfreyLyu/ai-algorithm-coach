<!-- File purpose: Describe code evidence, scoped host reviews, and learning checkpoints. -->

# Code reviews and learning evidence

The Skill, CLI, and optional Web panel use the same Coach service and SQLite
store. The runtime supports schema version 4. New users explicitly initialize a
workspace. Existing users open a compatible store. A schema mismatch is reported
without changing the database. Format conversion is external maintenance, not a
Skill capability or a bundled command.

## Host analysis

Feedback retains the user's complexity claims. `review evidence` stores code
against an exact attempt and feedback revision. `review status` exposes pending,
missing-code, reviewed, and stale work. The host model reads this evidence and
uses `review submit` to save its analysis with a committed operation receipt.
No project command calls a model API. A browser save does not launch a model.

Review records contain code identity, size definitions, complexity conclusions,
reasoning, sources, reviewer identity, and separately scoped learning evidence.
Changing code or feedback invalidates the prior version binding. Old code and
reviews stay available. Identical retries return the original receipt.
Model agreement does not prove AC, oral explanation, independence, or mastery.
Missing proof stays unknown. The form writes code evidence but cannot submit a
host review verdict. It uses the same store, revision, origin, and receipt guards.

## Current records and checkpoints

Practice context records the original identity, recommendation date, framework,
and disposition of an attempt. Research can add sources and selection reasons;
it cannot change outcomes or relax an original timebox. `history --attempt ID`
reads one practice history. `history --problem ID` reads the problem's attempts
and supporting evidence. Unbound evidence is not another practice attempt.

A learning checkpoint stores confirmed state, covered feedback and assessment
versions, the rule version, and evidence coverage. It is an immutable factual
boundary, separate from the rebuildable `learning_state` projection. A new user
needs no checkpoint. The interview profile continues from compatible checkpoints.
The standard profile derives state from full attempt evidence. It rejects partial
checkpoints with `checkpoint_profile_unsupported`; complete evidence permits a
full replay. Corrections outside reliable coverage require reconciliation;
they cannot create an unsupported stable result. Checkpoints do not establish
independent proof.

The checkpoint body has this current-data contract:

| Field | Value |
| --- | --- |
| `state` | A confirmed problem-state object for the row's problem and language. |
| `feedback_revisions` | A map from covered attempt IDs to their non-negative feedback revisions. |
| `assessment_versions` | The same covered IDs mapped to the record reader's opaque assessment-version strings. |
| `outcomes` | The same covered IDs mapped to the effective outcomes defined below. |
| `evidence_coverage` | `complete` when all evidence needed for replay is present; otherwise `partial`. |
| `rule_version` | The rule contract checked before the profile uses a checkpoint. |
| `stable_dates` | Optional distinct ISO dates that support the saved stable streak. |

Each outcome contains `result` (A–F or `null`), `practice_date` (ISO date),
`training_identity` (`new`, `retest`, or `transfer`), `stable_pass` (boolean), and
`review_decision`. That decision is `null` without A–D feedback; otherwise it
contains `days` (selected interval), `range` (inclusive minimum/maximum days), and
`reason`. The rule version and these outcomes must match the configured profile.
Use the record reader's effective revision and assessment identities. A code hash
alone is not an assessment version. Complete coverage permits a full replay;
partial coverage preserves the confirmed boundary and reports uncertain older
corrections. The checkpoint is prepared as compatible data, not inferred by a
daily run from unstructured notes.

Native attempt context can contain `training_identity`,
`original_recommendation_date`, `primary_framework`, and selection research.
Its scheduling `disposition` defaults to `open`. `completed` is bound to
`disposition_revision`; a newer feedback revision can retract that closure.
`record_only` keeps a historical record out of future backlog allocation.
Supporting evidence with no practice identity belongs in `history_evidence`,
where it cannot add an attempt or completion count.

The optional interview profile adds bounded allocation and evidence-based review
bands. See its [Skill workflow](../skills/algorithm-coach/references/interview-profile.md).
The standard profile keeps its existing selection rules. Both use the same store.

## Scheduling

An external task starts the Skill with the configured database path and tool
permissions. Read current settings and records, process pending analysis, save
researched candidate context, then run `start-session`. It saves or reuses the
plan before starting the managed local feedback panel. Return its exact date/store
URL only after `web.status` is `ready`.

Preferred run time in SQLite is not a scheduler. The full workflow needs a host
model session and local execution. A prompt alone does not establish write or
network permissions. Check the effective host configuration when wiring a task.
