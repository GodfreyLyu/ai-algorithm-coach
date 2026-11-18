<!-- File purpose: Guide policy proposals, explicit approval, and metadata operations. -->

# Policy operations

Read this when the user changes training scope, dates, limits, or catalog metadata.
Use `capabilities` and command help to check the installed version first.
There is no model-owned configuration ledger.

## Define the requested change

Policies can set `name`, `topics_any`, `difficulties`, `problem_ids`,
`excluded_problem_ids`, `preferred_topics`, `max_daily_count`, `effective_from`,
and `effective_until`.
Tags within `topics_any` use OR. Allowed dimensions intersect. Exclusions win.
Preferences only rank eligible problems. They never widen scope.
Empty allowlists are invalid. `null` removes an allowed-dimension restriction.
Empty exclusions and preferences are valid.

Keep unrelated fields omitted. Omitted scope fields inherit the policy resolved
on the proposed start date. The default start is tomorrow in the saved timezone.
Omitted `effective_until` means no end date, not an inherited end date.
If a user requests a limited window, include the end date explicitly.

## Prepare and preview

Read `policy get`. Use its global `latest_revision` as `--expected-revision`.
Do not substitute `revision`, which is only effective for the queried date.
Global version can be newer because another policy starts in the future.

Submit one proposal with a stable action ID:

```sh
python3.12 scripts/coach.py policy propose --changes '{"topics_any":["array"],"difficulties":["easy"]}' --expected-revision GLOBAL_VERSION --submission ACTION_ID
python3.12 scripts/coach.py policy preview --proposal PROPOSAL_ID
```

The proposal receipt has `status: proposed`, `proposal_id`, `content_hash`, body,
and base configuration, catalog, and policy versions. It does not activate anything.
Preview is read-only. It must not generate a saved plan or attempts.
Inspect staleness, exact body, dates, diff, eligible count, selections, paused
backlog and reviews, shortfall, conflicts, and fallback after expiry.
Check `activation_allowed`. If false, show each `activation_blockers` entry's
`code`, `message`, and `details`. Resolve stale, empty-scope, frozen-plan, or manual
capacity conflicts before asking for approval. Do not bypass the preflight result.
An allowed preview is not a reservation. Activation rechecks conditions again.

`expiry_fallback` contains the resolved policy for the day after a bounded window.
It is `null` when there is no end date. The preview date must be inside the window.
A week-long policy does not forecast a week of future results. Publishing future
plans now freezes choices from current records. Use read-only previews for an
overview when the user has not asked to publish those plans.

An expired policy resolves to a prior applicable policy or unrestricted baseline.
Do not promise that its restrictions continue after the window.
Use `policy get --date YYYY-MM-DD` for transition dates when needed.
State concrete dates when a request mixes today, tomorrow, and a future window.
A scope that starts tomorrow does not restrict actual today retroactively.

## Obtain exact approval

Present the concrete preview and exact proposal hash. Wait for explicit approval
of that proposal through the trusted host or direct user action.
Do not infer approval from the model's own `user_confirmed` flag.
The hash binds content; it does not independently prove a person's consent.
If the host cannot establish approval, leave the proposal inactive.

Activate only the approved proposal:

```sh
python3.12 scripts/coach.py policy activate --proposal PROPOSAL_ID --expected-revision GLOBAL_VERSION --accept-hash EXACT_HASH --submission ACTIVATION_ACTION_ID
```

Check `ok: true`, `data.status: applied`, the proposal hash, revision, and submission
ID. A changed proposal or stale context needs review again.
Retry a lost response using the same operation ID and payload. Query its receipt.

## Existing work

Do not turn paused work into E, F, or completion.
Old feedback can still be saved or corrected outside the current scope.
The core applies eligibility to manual practice and review allocation too.

Old plans remain frozen. Explain reported policy conflicts without rewriting them.
Activation is refused when affected published plans violate the proposed scope.
Recommend the next unpublished date. Do not silently move the user's dates.
The check uses saved plan configuration. A lower current `daily_count` alone does
not invalidate an older larger plan. A new explicit policy cap can still conflict.

The plan target is `daily_count`. A policy `max_daily_count` is a hard shared
allocation cap across manual practice and plans. Without that policy cap, manual
practice has no implicit daily limit from `daily_count`.

## Metadata and schema

Read [catalog discovery](catalog-discovery.md) for host-assisted search, source
checks, import authorization, preview, receipt checks, and readback.
Use `catalog preview --file PATH` before a new metadata batch. Preview is read-only.
Use `catalog import --file PATH --submission ACTION_ID --expected-hash PAYLOAD_HASH`
for the authorized batch. The hash comes from that batch's allowed preview.
TOML uses `[[problems]]`. JSON uses an object with a `problems` array.
Do not pass a raw JSON array. Policy files use their field names at the top level.
Entries contain ID, title, difficulty, tags, and official LeetCode URL only.
Do not import statements, paid content, practice logs, private paths, or credentials.
An accepted URL shape is not proof that the page exists or its fields are correct.
Imports append metadata. They cannot change an existing problem identity.
Import does not activate a policy or force new problems into a frozen plan.
Use the policy proposal, preview, and exact approval steps above for scope changes.

If the tool reports `schema_mismatch`, show the expected and actual versions.
Preserve the workspace. A compatible store must be prepared through external
maintenance before these commands can run. Do not erase data or initialize a
second workspace to bypass a schema error.
