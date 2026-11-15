<!-- File purpose: Configure and diagnose the optional local feedback panel in a Skill bundle. -->

# Optional local Web panel

The Web bundle contains prebuilt React assets and the same Python core.
It starts one FastAPI process for both the form and API. Daily training does not
need Node, npm, an asset build, or package installation.

## One-time setup

Use the same initialized private data directory as the core. Install the Web
requirements in a private virtual environment with Python 3.12 or newer.
The bundle includes `requirements-web.txt`. A core-only bundle has no UI assets;
installing Python packages alone does not add its missing page.

Save optional settings in `web.toml` inside the private data directory:

```toml
# File purpose: Configure this private workspace's optional Web runtime.
[web]
enabled = true
python = "/path/to/private/coach-data/web-venv/bin/python"
port = 8765
```

The Python path must point to an environment with the Web requirements installed.
Do not put a user's paths, environment, logs, or runtime files in a public bundle.

## Daily use and diagnosis

Run `scripts/coach.py start-session` with the existing data directory. The command
returns `plan` and `web` separately. A Web failure leaves the plan usable.
Only `web.status = ready` establishes that the link is ready at that time.
Use the exact returned URL. The actual port can differ from the preferred port.

Run `scripts/coach.py web status` to inspect the managed instance. Run
`scripts/coach.py web stop` to request its verified graceful shutdown.
Do not kill a process based only on a saved PID or a familiar port number.

## UI-link-only requests

If the user only asks for the UI link, check `web status` for the intended store.
When it is ready, return its reported URL. Do not invent a fixed port or store ID.
That service URL is not a date-bound `start-session` link.
`web status` only inspects managed instances. It does not start a service or
generate a plan. The CLI has no separate managed start-only command.

`start-session` prepares a plan as well as the Web service. Use it when the user
requests daily training or plan creation. Do not use it only to open an empty UI.
For a source checkout, `scripts/serve_web.py` is an existing foreground option.
It serves the built UI and API without generating a plan. That script is outside
the standalone Skill bundle. It needs the Web environment and a running terminal.
Do not describe it as a detached or managed service. If this option is unavailable,
explain the limitation instead of claiming a new start-only command exists.

Service readiness does not mean that the selected date has a saved plan.
Without one, the page shows an empty state and has no per-problem feedback form.
When the user requests a plan, run `start-session` and check `plan` and `web`
separately. Return its exact ready URL. If the page is already open, ask the user
to click **Refresh** or reopen that URL. Do not submit feedback to create a plan.

## Store and host boundary

The page must match the expected store before editing. A copied database can
retain the same workspace UUID but has a different store identity. If a page
reports a store mismatch, obtain a new session link for the intended workspace.
Do not rebase or resend old edits to another store.

The local host must allow background processes. The browser must access that
computer's loopback interface. A detached process is not an operating-system
supervisor, a scheduler, or a promise of all-day availability. If the host removes
it, the next session can start it again. Chat feedback remains available.

Readiness is separate from persistence. The existing feedback revision,
idempotency, receipt, and correction rules still apply to browser saves.
