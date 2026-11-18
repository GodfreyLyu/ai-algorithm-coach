<!-- File purpose: Guide interview training from current configuration and durable records. -->

# Interview profile

Read this when configuration selects `tokyo-interview-v1`. Use the configured
private database. A scheduled run reads current records; it does not initialize
or reconfigure a workspace. The standard profile keeps its own allocation rules.

Read `config`, `state --summary`, `review status --pending`, and the latest saved
plan before choosing work. Use `history --problem ID` for supporting evidence.
Only explicit feedback establishes practice outcomes. Recommendation, a correct
example, reading an answer, silence, and the passage of time do not establish
completion. Keep completion, independence, and stable performance separate.

## Research and selection

Prioritize confirmed gaps and independent interview performance. Use official
problem statements and constraints. Cross-check technical claims with original
authors, textbooks, university courses, or language documentation. Sources can
include labuladong Hot 100, public LeetCode lists, Tech Interview Handbook,
NeetCode, and official HackerRank, CodeSignal, or Codility preparation material.
Company engineering and interview guides can establish relevant scenarios.
Company tags and dated personal experiences are lower-weight context. They do
not establish company frequency by themselves. Skip unsupported marketing lists,
unverifiable frequency claims, leaked material, and inaccessible paid content.
Research may cover other platforms; assignments still need a verified LeetCode
ID, title, difficulty, and direct official link.

Use actual configured interview goals, language, and dates when available.
For Tokyo preparation, prefer transferable frameworks suited to international
technology companies, Japanese internet companies, and English interviews. Do
not invent a company's question history. Prefer Medium problems. Choose Hard
problems only when the framework value and time return justify them.

The core preserves unfinished work first, including its recommendation date,
round, order, identity, and learning due date. Daily roles do not change identity.
Use four base slots and one normal supplement. A sixth slot needs useful distinct
work or unfinished backlog. All allocations share the six-item ceiling and active
scope limits. Keep unselected backlog pending. Report source, framework, scope,
or capacity shortfalls without creating a replacement workspace or extra work.

For free slots, save researched metadata through catalog preview/import. Save
selection evidence with `training-context --submission ID --file FILE`:

```json
{
  "problem_id": "leetcode:1",
  "context": {
    "primary_framework": "hash-table",
    "source_verified": true,
    "source_verification": {"official": {"url": "https://leetcode.com/problems/two-sum/", "checked_date": "2026-01-01", "scope": "Checked the current public statement and constraints."}},
    "score": [30, 24, 12, 8, 4],
    "targeted_gap": "A recorded gap or an honest missing-coverage observation."
  }
}
```

The five score limits are 40, 30, 15, 10, and 5: confirmed gap repair, interview
value, framework transfer, time return, and source support. Scores are relative
research judgments. Keep candidate comparisons and concrete reasons in context.
They cannot override unfinished work or scope gates. `sixth_justification`
explains a sixth free slot. A missing response does not prove a personal weakness.
Separate language/API fluency, oral explanation gaps, and actual algorithm bugs.
Update a weakness when new evidence resolves it. Do not freeze old examples into
permanent defects or invent progress percentages from sparse feedback.

Daily primary frameworks must differ. New work should avoid this week's IDs and
frameworks. A necessary late-week framework repeat requires a different technique
and `weekly_repeat_justification`. Continuation and useful retests can repeat
weekly material. Mark retests explicitly; do not rename accidental repetition.
Transfer requires `transfer_from`, `transfer_change`, the same primary framework,
and two qualifying independent performances on separate dates. Keep original
retests when proof is missing. Do not impose a fixed new/retest/transfer ratio.

## Session and presentation

After research, run `start-session`. It freezes or reuses the chosen list and
starts or reuses the local feedback service. Return its exact date/store-bound
URL when `web.status` is `ready`. Report a service failure while retaining the
saved plan. The Skill cannot wake itself. An external scheduler needs a host
model session, tool execution, access to the store, and local networking.

Use compact Chinese output, normally about 800 Chinese characters excluding
links. Include the local date, base/supplement count, continuation and new count,
real total budget, one shared closed-book reminder, ordered problem links with
difficulty, identity and timebox, folded non-spoiler hints, and the local feedback
link. Keep full research, scores and history in records unless requested. Do not
generate PDFs or replacement attachments, or reveal answers before recall.

Every item starts with 2–3 minutes of independent recall: identify the framework;
define state, variables, pointers, and containers; state the invariant, stopping
condition and boundaries; explain correctness and derive time/space costs. Place
reference hints and explanations after this block. Include recall in the item's
box rather than adding another timer.

New work uses 20–30 minutes, original retests 10–15, and transfers 15–25. Sum the
actual item boxes for the total budget. New work uses graded help: try independently
for 8–10 minutes, use one non-spoiler framework hint if needed, then try roughly
5 more minutes before asking for explanation. Stop a timed retest at its box and
record the concrete blocking point. Answer-based same-day rewriting is learning
practice, not another independent stable result. Record remedial reading and the
actual total when supplied. A short comparison with an already practiced problem
can clarify a framework condition inside the same box without adding another item.

Keep one compact chat fallback:

```text
Problem: __ | Outcome: complete / not complete / defer / skip
Independent: yes / no | Total minutes: __ (recall __ + reading __)
Help: none / minor / key hint / answer | Error or blocking point: __
Can explain invariant, correctness and complexity: __ | Proficiency: 1–5
```

## Code and complexity evidence

The Web form saves feedback and code. It does not launch a model. During a host
session, process `review status --pending` before choosing new work. Review the
exact returned code and feedback version. Missing code stays missing; do not use
another attempt's code. The core does not call a model API.

Use `review evidence --attempt ID --expected-revision N --submission ID --file FILE`
for code supplied in chat. The document contains `code`, `language`, and optional
`input_definition`. Save analysis with `review submit --submission ID --file FILE`:

```json
{
  "evidence_id": "EVIDENCE_ID_FROM_RECEIPT",
  "status": "issues",
  "input_definition": "n is stored entries; Q is the operation count.",
  "time_complexity": "O(log n) per operation",
  "space_complexity": "O(n) persistent storage",
  "reasoning": "Explain state counts, operation costs, and the chosen scope.",
  "sources": ["Submitted code", "A checked language API source when needed"],
  "reviewer": "Actual host/model identity when available",
  "learning_evidence": {"complexity": false}
}
```

Use `supported`, `issues`, or `insufficient_information`. Check loops, recursion,
container APIs, sorting, amortization, intermediate expressions, output and
persistent state. Distinguish one operation from a whole sequence. Define every
size parameter and explain constraint-dependent bounds. Estimate numeric ranges
at the calculation site, not only at the return type. Browse primary language
documentation for uncertain API costs. Measurements alone do not prove Big-O.

Preserve self-reports. Analysis is scoped model evidence, not an online-judge
result. Correct code does not prove independent work or the user's oral ability.
Only set supported `learning_evidence` fields; unanswered proof stays unknown.
Review claims cannot change A–F. Check the committed receipt before claiming a
save. Changed code or feedback requires a current version binding.

## Learning decisions

The profile uses 1–3 days for unfinished or dependent work, 3–7 for overtime or
key errors, 7–14 for independent work with weak explanation/boundaries, and 14–30
for on-time independent work with full evidence. Record the selected interval's
reason. A stable pass needs no assistance, the original timebox, invariant,
correctness, complexity, and a checked boundary example. New errors reset the
streak. Two dated qualifying performances permit transfer; a high self-rating
or understanding an answer does not. Compare dependence, timing, explanation,
boundary checks and recurrence over roughly two weeks when evidence supports it.

Learning checkpoints preserve confirmed state with explicit versions and evidence
coverage. New feedback continues from that state. Report reconciliation needs
when older evidence cannot be replayed reliably. Do not invent missing rounds,
new completion counts, or future success.
