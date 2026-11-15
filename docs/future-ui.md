<!-- File purpose: Specify the planned React TypeScript and FastAPI feedback boundary. -->

# Future feedback UI

Status: design only. The current delivery is the local Skill loop.

## Product behavior

React with TypeScript will provide the feedback form.
FastAPI will serve the API and built static UI from the same origin.
The adapter will call the existing application service.
It will not create another learning database or require a model to save feedback.
The existing local policy lifecycle is not a deployed HTTP approval mechanism.
Any UI for policy approval must establish a trusted user action on the exact
proposal hash. A model-generated confirmation flag is insufficient.

The stable entry page will open today's plan in the configured timezone.
Problem links, attempt IDs, current feedback, and revision numbers will be prefilled.
A–F and elapsed time will be the main controls.
Extra fields will be optional. Earlier dates and correction history will be visible.
Settings will be persistent. Users will not copy plans into the form each day.
The form will show policy-paused work and frozen-plan conflicts without converting
them to completion, deferral, or skip feedback.

## Save states

| Label | Required meaning |
| --- | --- |
| Saved on this device | The local draft was durably stored on this device. |
| Pending sync | A durable operation is waiting for authority confirmation. |
| Synced | The authority committed and applied the matching feedback revision. |
| Sync failed | Input is retained and the reason and retry action are visible. |
| Conflict needs attention | A newer revision exists and needs user resolution. |

A draft storage failure must show unsaved.
The browser queue may remove an operation only after checking its matching receipt.
Refreshing a loaded page or losing a response must not lose a saved operation.
Full offline browsing and background delivery are separate scope decisions.

## Proposed transport contracts

| Route | Application operation |
| --- | --- |
| `POST /v1/plans/ensure` | Ensure a plan exists without replacing a published plan. |
| `GET /v1/plans/{date}` | Read a plan and current attempt revisions. |
| `POST /v1/attempts` | Start an explicit redo or review. |
| `POST /v1/attempts/{id}/feedback` | Append progress or a correction. |
| `GET /v1/attempts/{id}/history` | Read the immutable revision history. |
| `GET /v1/submissions/{id}` | Check a committed operation receipt. |
| `GET /v1/learning-state` | Read derived evidence and due reviews. |
| `GET/PATCH /v1/config` | Read or update versioned settings. |

Writes carry a stable submission ID and an expected revision.
Omitted fields preserve values. Explicit clearing remains distinct from false.
Responses must identify the attempt, revision, content, and applied state.
Authentication, input errors, and conflicts must have distinct error contracts.
These routes are not available in the local CLI release.

The local CLI currently wraps results as `ok: true` with a `data` object.
Failures use `ok: false` and an `error` object.
An applied feedback receipt includes `submission_id`, `attempt_id`, `revision`,
`payload_hash`, `state_version`, `saved_at`, and `status: applied`.
The HTTP adapter must explicitly map this contract and choose suitable HTTP codes.
It must not mistake a readable failure response for a committed operation.

## Security and release gate

A browser session and an automated caller need separate authentication paths.
No long-lived machine secret belongs in frontend code or browser local storage.
HTTPS, CSRF defenses, allowed origins, owner login, revocation, and secret handling
must be tested before deployment. See [security](../SECURITY.md).

Release requires an end-to-end test: submit through the form, restart the process,
read the revision through the Skill, and show its effect on the next plan.
API unit tests alone do not establish that loop.
