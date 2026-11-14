<!-- File purpose: Explain consistent local backups and a cautious recovery check. -->

# Backup and recovery

Backups contain private feedback history. Store them outside the repository.
Use a local disk and restrict access to the operating system owner.

## Back up

Choose a new destination. The backup command must not replace an existing file.

```sh
python3.12 skills/algorithm-coach/scripts/coach.py backup \
  --output /path/to/private/backups/coach-new.sqlite3
python3.12 skills/algorithm-coach/scripts/coach.py check
```

The backup uses SQLite's consistency mechanism.
Do not replace it with a copy of an active database file.
A successful write proves only that a backup exists. Recovery must be tested too.

## Test recovery

Stop writers before switching a live workspace to restored data.
Keep the original workspace and backup unchanged.
Restore into a new private directory. Do not overwrite a live database.
Place the restored copy at `NEW_DATA_DIRECTORY/coach.sqlite3`.

Point `--data-dir` at that isolated directory and run `check`.
Read a known synthetic submission receipt and its attempt history.
Run `rebuild-state`, then compare its learning evidence with the source.
Generate the same next-date plan in isolated copies under the same configuration
and rules. The selected problems and reasons should match.

Do not compare newly generated opaque IDs between copies.
Compare stable business evidence, selected problems, and due dates instead.
Only switch the configured live path after those checks pass.

## Failure cases

If a write failed before commit, no success receipt should exist.
If the process died after commit, query the original submission ID after restart.
Retrying the original content is safe. Creating a new operation before checking
the old one can create an unintended second action.

A disk-full error or failed integrity check must not be reported as saved.
Preserve the failing database for diagnosis and avoid destructive repair attempts.
