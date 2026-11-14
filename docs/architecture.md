<!-- File purpose: Explain module boundaries, the local data flow, and delivery scope. -->

# Architecture

This release is a local tool. A manually requested date uses the records available
when its plan is generated. It does not reconstruct an earlier learning snapshot.

## Current delivery

The local Skill loop is the first delivery.
It uses Python 3.12 or later, SQLite, and the standard library.
No dependency installation or long-running service is needed for that loop.

```text
Conversation -> Skill -> CLI -> Application service -> SQLite
                              -> Deterministic rules
```

The Skill interprets user intent and explains recommendations.
It does not invent save receipts or keep a competing learning ledger.
The CLI validates its command input and returns structured results.
The application service owns transactions, versions, and idempotency.
Rules choose candidates and derive learning state.
Storage owns schema, consistency checks, and backups.

## Authority and execution

One database is the authority for one local learning workspace.
It contains saved configuration, plans, attempts, feedback history, and receipts.
Derived state can be rebuilt. Chat context is not a data source.

The Skill host must allow tool execution and persistent local storage.
Without those abilities it can provide tutoring, but it must say feedback is not
saved. The bundle carries the same core as the repository. It does not rely on a
second maintained implementation.

## Planning

A training date comes from the configured timezone or an explicit date.
Plans record their configuration and rule context.
Once published, a plan is frozen. Running the command again returns that plan.
It does not change its items or replace feedback.

Candidates prioritize active unfinished attempts, due reviews, weak areas,
and new coverage. Deferred work returns when its recorded date is due.
Undated deferrals remain visible for explicit rescheduling.
A skipped attempt stops carrying forward and never counts as complete.
Unselected backlog remains pending. It is not silently skipped.

## Feedback transaction

The service checks a stable submission ID and the expected feedback revision.
It appends a revision, updates derived state, and saves a receipt in one transaction.
A successful response is based on the committed receipt.
A repeated request with the same ID and content gets the original receipt.
The same ID with different content produces a conflict.

This is retryable idempotent processing. It is not an end-to-end exactly-once claim.
There is no separate asynchronous sync worker in the local MVP.

## Planned adapters

The next UI uses React with TypeScript and a FastAPI adapter.
It will call the same application use cases. See [the UI contract](future-ui.md).
A future MCP adapter must also remain thin.
Neither adapter should contain its own selection rules or learning database.

Scheduled execution belongs to an operating system or external platform.
The Skill does not wake itself up. A scheduled deterministic planning command
should work without an active model session.

## Explicit limits

There is no web server, browser login, remote API, running MCP transport, scheduler,
or cloud deployment in this delivery. No private prototype is imported.
Real AI client compatibility and any future deployment require separate checks.
