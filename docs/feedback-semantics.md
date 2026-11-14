<!-- File purpose: Define feedback, attempt history, uncertainty, and learning claims. -->

# Feedback semantics

## Result and evidence

| Result | Reported outcome | Default training effect |
| --- | --- | --- |
| A | Independent AC without hints. | Positive evidence and an interval review. |
| B | AC after hints. | Record hint dependence and review sooner. |
| C | AC after reading an answer. | Record answer dependence and review sooner. |
| D | Not yet AC. | Continue this attempt. |
| E | Deferred. | Resume on its due date, or wait for explicit rescheduling. |
| F | Skipped for this attempt. | Stop carrying this attempt forward. |

An empty result is unknown. It is not D, E, F, or complete.
E and F do not add a completion or prove a weakness.
A–C are self-reports. None means a verified judge result.
Time and space complexity entries are also self-reports.
Model agreement cannot turn a report into verified evidence.

## Fields

Feedback can include cumulative elapsed minutes, a blocking point, explanation,
boundary tests, proficiency, time complexity, space complexity, and assistance.
E can include a defer date. F can include a future eligibility date.
Optional fields stay unknown until answered.

| Field | Accepted value |
| --- | --- |
| `result` | A–F, or `null`. |
| `elapsed_minutes` | A finite non-negative number, or `null`. |
| `blocked_on`, `time_complexity`, `space_complexity` | Text up to 4,000 characters, or `null`. |
| `explanation` | `not_tried`, `partial`, `clear`, `uncertain`, or `null`. |
| `boundary_tests` | `true`, `false`, or `null`. |
| `proficiency` | An integer from 1 to 5, or `null`. |
| `assistance` | `none`, `hint`, `solution`, or `null`. |
| `defer_until`, `skip_until` | A `YYYY-MM-DD` date, or `null`. |

Omitted update fields keep their previous value.
An explicit `null` clears an optional field to unanswered.
For a boolean field, `false` is an explicit answer. It is not missing.
Elapsed minutes are the total for this attempt. They are not an increment.
This prevents a retried request from adding time twice.
Ordinary progress cannot reduce or clear known time. Use a correction if it was wrong.
A, B, and C imply assistance values of `none`, `hint`, and `solution` respectively.

## Attempts and revisions

Continuing D on another day keeps the same attempt ID.
Finishing that attempt adds progress to its history.
It does not create a second independent completion.
A separate redo or review creates a new attempt.

A correction states that a previous report was wrong.
It adds a new revision and keeps the old one.
For example, correcting A to C reduces the independent evidence and changes future
review state. The old A remains visible in history.

Known hint or answer dependence cannot disappear through ordinary progress.
If that record was wrong, use an explicit correction.
Merely doing the final steps without a hint does not make the whole attempt A.

Skipping ends the current attempt. The default skip cooldown is seven days.
After that cooldown, or a supplied `skip_until`, the core may select a new attempt
for the problem. It never reopens the skipped attempt as unfinished work.

The feedback occurrence time and its receipt time are separate.
A late correction should preserve when the practice occurred.
Do not make an old performance appear recent by changing its receipt time.

## Mastery and review

One A means one reported independent success.
Stable performance requires independent attempts on separate dates and sufficient
spacing. The default review policy uses intervals of three and seven days after
independent success. Assisted results trigger earlier review.
The saved rules determine the exact due date and evidence count.

Mastery labels describe the result of those rules on recorded self-reports.
They do not prove that a solution or complexity claim is correct.
Weakness labels retain reasons so the user can inspect them.

## Submission lifecycle

Create one submission ID per user action.
Keep the same ID, payload, and expected revision when retrying that action.
Check its receipt after a timeout before creating another operation.

A new edit uses a new ID and the latest expected revision.
A revision conflict requires reading current history.
Do not silently overwrite another client or choose between conflicting A and E.

The local CLI has no browser queue. Its receipt means the authority committed and
applied the operation. The future UI must distinguish local draft persistence,
pending submission, committed application, and failure.
