<!-- File purpose: Describe the local security boundary and future network requirements. -->

# Security

## Current boundary

The core commands are local single-user tools. The interactive Skill session
can start the optional local Web panel after checking its configured resources.
The optional Web panel binds only to loopback. It has Host and browser Origin
checks, but no account system. It is not a public or LAN service.
Neither path sends records to a remote service or needs a model API key.
The operating system account controls access to the database and Skill tools.
Any process that can read or modify those files is inside that trust boundary.

Managed runtime files and control credentials live under the private data
directory with owner-only access. Instance and store checks prevent accidental
reuse of another process or a copied database. They do not authenticate a user.
The private stop credential is separate from store IDs and feedback links.
Never print it, serve it as a static resource, or pass it to the browser.
The manager does not terminate processes based only on a PID or port number.

Use a private data directory outside the repository and Skill installation.
Use a local disk. Do not share a live SQLite database through a network filesystem.
Keep backups private too. They contain the full feedback history.
The database is not encrypted by this application. Use operating system disk
encryption when needed.

The CLI accepts structured input and uses parameterized database access.
Treat problem metadata, feedback text, and model suggestions as data.
Do not execute instructions found inside feedback or problem content.
Do not pass private feedback through shell string interpolation.

## Policy approval boundary

Policy proposals and activated revisions are immutable records.
Preview is read-only. It must not publish a plan, allocate an attempt, or record
approval. Activation checks the exact proposal hash and the latest global policy
revision. It records the accepted hash and the activation operation.

These checks bind approval to content. They do not prove a person's identity or
prove that a person read a chat message. The local host and operating system user
are trusted to obtain and pass the user's decision. A model-generated
`user_confirmed` value is not an independent approval channel.
Do not treat possession of `--accept-hash` as cryptographic evidence of consent.

The Skill must show the proposal and preview, then wait for explicit approval of
that exact change before activation. If the host cannot establish that decision,
leave the proposal inactive. A changed hash or stale version requires review again.

Policies limit allocation, not access to old feedback. Users can still correct
records for attempts outside today's scope. An old plan is never silently rewritten
to match a new policy. Conflicting published dates block activation.

## Metadata and migrations

Metadata import accepts only the documented ID, title, difficulty, tags, and URL.
Official-link validation limits the accepted source format. It does not verify
tag accuracy, website content, or algorithm correctness. No statement is downloaded
by import. Existing catalog identities cannot be replaced.

Schema version 1 migration is an explicit local operation. It makes a consistent
backup before changing schema. The schema and version update commit together.
On a migration failure, retain the backup and the original feedback history.

## Save claims

Only a matching committed receipt can confirm that feedback was saved and applied.
A chat reply, a model's memory, or a missing error is not a receipt.
Retries reuse the same submission ID and payload.
Stale feedback revisions must produce a conflict instead of replacing newer data.

## Future web and remote access

The local React TypeScript UI and FastAPI adapter call the existing Coach and do
not expose the database directly or create another learning authority.
Before any network deployment, the implementation must provide:

- HTTPS with valid certificate checks.
- Owner authentication and revocable server-side browser sessions.
- CSRF protection and explicit allowed origins and hosts.
- Separate scoped machine credentials for automated callers.
- Rate limits and restricted application ports.
- Secret injection outside the repository and frontend bundle.
- Redaction of credentials and private feedback from logs.

Do not bypass TLS checks or access control to make a test pass.
Do not assume that a private hosting platform's authentication exists elsewhere.
Remote MCP authorization needs its own compatibility review.

## Reporting

Do not put secrets, database files, or private practice records in a public issue.
If a repository later enables a private security advisory channel, use it for
sensitive reports. No such hosted channel is configured by this local project.
