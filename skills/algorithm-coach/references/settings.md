<!-- File purpose: Guide changes to the daily problem mix and the daily run time. -->

# Daily mix and run time

Read this when the user asks to change how many problems arrive each day, the
share of weak, new, review, or unfinished work, or the time a daily run starts.
Change only the setting the user asked about. Do not change both by default.

## Daily mix

`daily_mix` is optional. Without it, the profile keeps its original selection.
It is a learning setting in `config`, not a scope policy. Scope policies still
limit topics, difficulties, problems, and the shared daily cap.

| Category | Meaning |
| --- | --- |
| `weak` | A due retest with recorded weakness from explicit A–D feedback. |
| `new` | A problem with no attempt in any language, checkpoint, or practice evidence. |
| `review` | A due retest without recorded weakness. |
| `continue` | Unfinished work in its original attempt. |

Slot counts must sum to `daily_count`. The interview profile allows at most six.
Slot order is fill order. A policy cap trims from the last slot.
`continuation` is `dedicated` by default: unfinished work uses only `continue`
slots, and other backlog stays pending. `fill_unused` also lets unfinished work
take a slot that another category could not fill. That category still reports
its shortfall.

Unanswered, deferred, and skipped work is never weak. A weak problem waits for
its review date. Retests and continuations never fill a new slot. One problem
fills one slot. A configured mix keeps every scope, research, source, framework,
weekly repeat, and sixth-slot rule.

Preview first. Preview does not save, publish, or allocate:

```sh
python3.12 scripts/coach.py --data-dir /path/to/private/coach-data config --preview --date 2026-01-05 --changes '{"daily_count":3,"daily_mix":{"slots":[{"category":"weak","count":2},{"category":"new","count":1}]}}'
```

Show the user `daily_mix.categories`, any `category_shortfalls`, and
`unallocated_backlog`. Save only after the user agrees. Use the current revision:

```sh
python3.12 scripts/coach.py --data-dir /path/to/private/coach-data config --expected-revision 4 --changes '{"daily_count":3,"daily_mix":{"slots":[{"category":"weak","count":2},{"category":"new","count":1}]}}'
```

Restore the original selection with `{"daily_mix":null}`. Restore the previous
`daily_count` in the same change when the user wants it back.
A published plan keeps its items. A new mix applies to dates without a plan.
Report a shortfall by category and count. Do not add problems to cover it.

## Run time

`run_time` (HH:MM) and `timezone` (IANA) record the desired local time.
They do not start anything. The host or system scheduler is the actual trigger.
The training date is the local date in `timezone` when the command runs.

1. Save the new time: `config --changes '{"run_time":"09:00"}' --expected-revision N`.
2. Run `schedule show`. It returns the daily rrule, cron fields, next runs,
   `workspace_id`, and warnings such as `near_midnight` or `dst_affected_dates`.
3. Find the existing scheduled task that runs this workspace. Match it by the data
   path or `workspace_id` in its instructions, not by its time. Exactly one active
   task must match. Report zero or several matches and stop.
4. Edit that task in place when the host offers a supported tool for it. Never
   create a second task to change a time. Leave unrelated tasks unchanged.
5. Run `schedule check --observed-rrule RULE --observed-timezone ZONE` or
   `--observed-cron FIELDS` with the values the host now shows.
   Report `match` and the next run the host displays.

If the host cannot edit its task, say exactly what is done and what is not:
the saved setting changed, but the scheduler still uses the old time. Give the
user the manual step in the host's own scheduler. Do not claim the new time is
active until a check matches.

Do not put a fixed time or problem count in the scheduled task's instructions.
Ask the task to follow the saved configuration instead. Changing a run time never
rewrites a published plan or any history.
