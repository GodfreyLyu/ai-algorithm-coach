<!-- File purpose: Keep project changes aligned with the local training and documentation rules. -->

# Project rules

- Use short English sentences in comments and project documents.
- Start each maintained source or text file with a purpose comment.
- Keep required format markers in place. The Skill starts with YAML frontmatter.
- Give every Python function and method a docstring. Include `Inputs:`, `Outputs:`,
  `Logic:`, and `Dependencies:`. Include test helpers and private methods.
- Keep training decisions in the shared Python core. Adapters must call that core.
- Put training rules in `src/algorithm_coach/core/`. Core modules do not open
  databases or perform I/O.
- Put the schema, transactions, and persisting `Coach` mixins in `store/`.
  Only `web/` may import Web dependencies.
- Keep tools in `scripts/checks/` and `scripts/packaging/`. Do not name a
  directory `build`. Git and the comment check both skip that name.
- Keep the runtime free of third-party dependencies for the local Skill path.
- Do not use chat summaries or browser caches as another learning authority.
- Preserve feedback history, stable operation IDs, and optimistic revision checks.
- Keep scope policies separate from learning rules. Enforce active scope in every
  path that allocates practice, including manual practice and retests.
- Keep policies, proposals, and approval records immutable. Tie approval to the
  exact proposal content hash. A model-written confirmation flag is not consent.
- Use global `latest_revision` for policy concurrency checks. Do not substitute
  a policy revision that is only effective on a particular date.
- Preview without publishing a plan or allocating attempts. Show paused work,
  shortfalls, policy changes, and fallback after expiry.
- Pause out-of-scope backlog and reviews without writing E, F, or completion.
- Keep published plans frozen. Report policy conflicts instead of rewriting them.
- Keep metadata import append-only and separate from private practice data.
- Support new workspaces and existing stores with the current schema only.
- Keep format conversion and schema upgrades outside the Skill and runtime.
- Validate external input at adapters and stored data at storage boundaries.
  Internal code should reuse validated values instead of repeating checks.
- Treat AC results and complexity entries as self-reports unless separate evidence
  supports a clearly scoped verification claim.
- Keep all tests and examples synthetic. Do not import private training records.
- Keep databases, backups, logs, credentials, and personal paths out of this tree.
- Do not publish, deploy, install global Skills, or change external accounts unless
  the user asks for that action.

Run these checks after a relevant change:

```sh
python3.12 -m unittest discover -s tests -v
python3.12 scripts/checks/check_comments.py
```

The optional React TypeScript and FastAPI panel is local-only. Its scope is saved
plans, feedback forms, database persistence, and derived topic scores. Keep the
Skill path independent of Web dependencies. Do not add accounts, offline queues,
policy management, or deployment unless the user requests them.
TypeScript components, helpers, and callbacks use English function contracts too.
Generated JSON lockfiles keep valid tool syntax; document their purpose in the
Web guide instead of inserting invalid comments.
Interactive session startup belongs in the runtime adapter. Keep plain planning
and feedback commands headless. Managed servers must verify store and instance
identity, keep control credentials private, and stop without PID-only signals.
