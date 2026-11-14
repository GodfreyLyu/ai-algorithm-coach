<!-- File purpose: Keep project changes aligned with the local training and documentation rules. -->

# Project rules

- Use short English sentences in comments and project documents.
- Start each maintained source or text file with a purpose comment.
- Keep required format markers in place. The Skill starts with YAML frontmatter.
- Give every Python function and method a docstring. Include `Inputs:`, `Outputs:`,
  `Logic:`, and `Dependencies:`. Include test helpers and private methods.
- Keep training decisions in the shared Python core. Adapters must call that core.
- Keep the runtime free of third-party dependencies for the local Skill path.
- Do not use chat summaries or browser caches as another learning authority.
- Preserve feedback history, stable operation IDs, and optimistic revision checks.
- Treat AC results and complexity entries as self-reports unless separate evidence
  supports a clearly scoped verification claim.
- Keep all tests and examples synthetic. Do not import private training records.
- Keep databases, backups, logs, credentials, and personal paths out of this tree.
- Do not publish, deploy, install global Skills, or change external accounts unless
  the user asks for that action.

Run these checks after a relevant change:

```sh
python3.12 -m unittest discover -s tests -v
python3.12 scripts/check_comments.py
```

The current milestone is the local Skill loop. The React TypeScript and FastAPI
feedback UI has a documented contract. It is not implemented yet.
