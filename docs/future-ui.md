<!-- File purpose: Describe the narrowed local Web contract and deferred extensions. -->

# Local Web scope

The implemented local panel covers existing training plans, per-attempt feedback
forms, database saves, and independent completion rates by topic and language.
See [Web setup and semantics](web.md).

React calls FastAPI. FastAPI directly calls Coach in one synchronous worker scope.
The adapter closes its Coach in that same scope. SQLite remains the authority.
GET requests do not initialize data, create plans, or rebuild learning state.

| Route | Purpose |
| --- | --- |
| `GET /v1/context` | Read workspace identity, date, timezone, and language. |
| `GET /v1/runtime` | Read store identity, verified assets, and managed instance status. |
| `GET /v1/plans/{date}` | Read an existing frozen plan and effective feedback. |
| `POST /v1/attempts/{id}/feedback` | Append progress or correction through Coach. |
| `GET /v1/submissions/{id}` | Read a receipt and its immutable feedback revision. |
| `GET /v1/scores` | Read topic rates for a language. |

Feedback writes require `X-Coach-Store-Id`. Reads check it when supplied.
The identity binds the workspace UUID to the canonical database location.
The frontend never silently replaces that identity during refresh or receipt retry.
Unknown or changed stores return `workspace_mismatch` without saving feedback.

Managed shutdown uses `POST /internal/runtime/stop` with an instance ID and a
private control header. It is a launcher operation, not a browser feature.
Control credentials stay outside public responses and are never bundled.

HTTP success uses `ok: true` and `data`. Failures use `ok: false` and `error`.
Feedback data contains the committed receipt and its exact feedback revision.
The browser checks submission identity, attempt identity, revision, and applied
status. It does not recompute the Python payload hash or compare an old receipt
with the newest feedback snapshot.

Missing fields preserve values. Explicit null clears a field. False is an answer.
The current page retains unsaved input on a handled failure. It has no durable
browser queue. Its states are unsaved, saving, saved to database, and save failed.

Accounts, remote access, public deployment, IndexedDB, background synchronization,
policy editing, and browser policy approval are outside this release.
Those additions need separate contracts and validation. This local HTTP panel
must not be treated as an authenticated public service.
