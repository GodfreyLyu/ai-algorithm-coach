/** File purpose: Show topic evidence, overall progress, and practice activity as charts. */
import { useState } from "react";
import { RESULT_LABELS, tagLabel } from "../constants";
import { formatMinutes, shortDate } from "../dates";
import type { Resource } from "../hooks";
import type { Progress, ProgressProblem, Scores, Topic } from "../types";
import { ActivityChart, ResultBar, ResultLegend } from "./charts";

type SortKey = "weakest" | "practiced" | "name";

/**
 * Inputs: A label, a main value, and supporting text.
 * Outputs: One summary tile.
 * Logic: Show one headline number with its evidence.
 * Dependencies: None.
 */
function StatTile({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="stat-tile"><span className="stat-label">{label}</span><strong>{value}</strong><span className="stat-detail">{detail}</span></div>;
}

/**
 * Inputs: One problem row from the progress API.
 * Outputs: One drill-down table row.
 * Logic: Show the latest result, practice date, attempts, and saved stability.
 * Dependencies: Result CSS classes and date helpers.
 */
function ProblemRow({ problem }: { problem: ProgressProblem }) {
  return <tr>
    <th scope="row"><a href={problem.url} target="_blank" rel="noreferrer">{problem.title}</a></th>
    <td><span className={`chip difficulty ${problem.difficulty}`}>{problem.difficulty}</span></td>
    <td><span className={`result-letter result-${problem.result}`} aria-hidden="true">{problem.result}</span><span className="sr-only">{RESULT_LABELS[problem.result]}</span></td>
    <td>{shortDate(problem.practice_date)}</td>
    <td>{problem.attempt_count}</td>
    <td>{problem.stable ? "Stable" : "–"}</td>
  </tr>;
}

/**
 * Inputs: One topic, its problems, expansion state, and a toggle callback.
 * Outputs: A topic row with a stacked bar and an optional problem list.
 * Logic: Mark small samples. Problem rows come from the progress API.
 * Dependencies: ResultBar and ProblemRow.
 */
function TopicRow({ topic, problems, progressReady, expanded, onToggle }: {
  topic: Topic; problems: ProgressProblem[]; progressReady: boolean; expanded: boolean; onToggle: (tag: string) => void;
}) {
  /**
   * Inputs: A row click.
   * Outputs: The topic tag to the parent.
   * Logic: Expand or collapse this topic.
   * Dependencies: onToggle.
   */
  function toggle() { onToggle(topic.tag); }
  /**
   * Inputs: One problem.
   * Outputs: A keyed problem row.
   * Logic: Keep server order.
   * Dependencies: ProblemRow.
   */
  function renderProblem(problem: ProgressProblem) { return <ProblemRow key={problem.problem_id} problem={problem} />; }
  const name = tagLabel(topic.tag);
  return (
    <li className={`topic-row ${expanded ? "expanded" : ""}`} data-topic={topic.tag}>
      <button type="button" className="topic-toggle" aria-expanded={expanded} onClick={toggle}>
        <span className="topic-name"><strong>{name}</strong>
          <span className="topic-count">{topic.problem_count} {topic.problem_count === 1 ? "problem" : "problems"}{topic.sample_small && <span className="sample-badge">Small sample</span>}</span></span>
        <span className="topic-bar"><ResultBar counts={topic.results} total={topic.problem_count} label={name} /></span>
        <span className="topic-score"><strong>{topic.score}%</strong><span>{topic.independent_count}/{topic.problem_count} independent</span></span>
        <span className="topic-stable"><strong>{topic.stable_count}</strong><span>stable</span></span>
      </button>
      {expanded && <div className="topic-detail">
        {!progressReady ? <p className="quiet-note">Problem details are unavailable right now.</p>
          : problems.length ? <div className="table-scroll"><table className="data-table"><caption className="sr-only">Problems in {name}</caption>
            <thead><tr><th scope="col">Problem</th><th scope="col">Difficulty</th><th scope="col">Latest</th><th scope="col">Practiced</th><th scope="col">Attempts</th><th scope="col">Mastery</th></tr></thead>
            <tbody>{problems.map(renderProblem)}</tbody></table></div>
          : <p className="quiet-note">No problem rows for this topic.</p>}
      </div>}
    </li>
  );
}

/**
 * Inputs: Two topics and a sort key.
 * Outputs: A comparison number for Array.sort.
 * Logic: Weakest sorts by rate, then by evidence. Practiced sorts by evidence count.
 * Dependencies: None.
 */
function compareTopics(left: Topic, right: Topic, key: SortKey): number {
  if (key === "weakest" && left.score !== right.score) return (left.score ?? 0) - (right.score ?? 0);
  if (key !== "name" && left.problem_count !== right.problem_count) return right.problem_count - left.problem_count;
  return left.tag.localeCompare(right.tag);
}

/**
 * Inputs: Score and progress resources and the current training date.
 * Outputs: Summary tiles, activity chart, and sortable topic bars.
 * Logic: Explain the score basis and render saved evidence without inventing values.
 *   Topics without evidence are folded into one line.
 * Dependencies: ActivityChart, TopicRow, and the score and progress APIs.
 */
export function ScoresView({ scores, progress, today }: { scores: Resource<Scores>; progress: Resource<Progress>; today: string }) {
  const [sort, setSort] = useState<SortKey>("weakest");
  const [expanded, setExpanded] = useState<string | null>(null);
  const data = scores.data;
  const progressData = progress.data;
  const practiced: Topic[] = [];
  const untouched: Topic[] = [];
  if (data) for (const topic of data.topics) (topic.problem_count ? practiced : untouched).push(topic);
  /**
   * Inputs: Two topics.
   * Outputs: Their order under the current sort key.
   * Logic: Delegate to compareTopics.
   * Dependencies: compareTopics and sort state.
   */
  function byCurrentSort(left: Topic, right: Topic) { return compareTopics(left, right, sort); }
  practiced.sort(byCurrentSort);
  const problemsByTag = new Map<string, ProgressProblem[]>();
  if (progressData) for (const problem of progressData.problems) for (const tag of problem.tags) {
    const list = problemsByTag.get(tag) ?? [];
    list.push(problem);
    problemsByTag.set(tag, list);
  }
  let independent = 0;
  let stable = 0;
  let minutes = 0;
  if (progressData) {
    for (const problem of progressData.problems) { if (problem.result === "A") independent += 1; if (problem.stable) stable += 1; }
    for (const day of progressData.days) minutes += day.minutes;
  }
  const problemTotal = progressData?.problems.length ?? 0;

  /**
   * Inputs: A sort button click.
   * Outputs: The weakest-first order.
   * Logic: Store the key in component state.
   * Dependencies: setSort.
   */
  function sortWeakest() { setSort("weakest"); }
  /**
   * Inputs: A sort button click.
   * Outputs: The most-practiced order.
   * Logic: Store the key in component state.
   * Dependencies: setSort.
   */
  function sortPracticed() { setSort("practiced"); }
  /**
   * Inputs: A sort button click.
   * Outputs: Alphabetical order.
   * Logic: Store the key in component state.
   * Dependencies: setSort.
   */
  function sortName() { setSort("name"); }
  /**
   * Inputs: A topic tag.
   * Outputs: That topic expanded, or collapsed when already open.
   * Logic: Keep one topic open at a time.
   * Dependencies: setExpanded.
   */
  function toggleTopic(tag: string) { setExpanded(expanded === tag ? null : tag); }
  /**
   * Inputs: One practiced topic.
   * Outputs: A keyed topic row.
   * Logic: Attach the topic's problem rows.
   * Dependencies: TopicRow and problemsByTag.
   */
  function renderTopic(topic: Topic) {
    return <TopicRow key={topic.tag} topic={topic} problems={problemsByTag.get(topic.tag) ?? []} progressReady={progressData !== null} expanded={expanded === topic.tag} onToggle={toggleTopic} />;
  }
  /**
   * Inputs: One topic without evidence.
   * Outputs: A keyed tag chip.
   * Logic: Show the name only.
   * Dependencies: tagLabel.
   */
  function renderUntouched(topic: Topic) { return <li key={topic.tag} className="chip" data-topic={topic.tag}>{tagLabel(topic.tag)}</li>; }

  return (
    <section aria-labelledby="scores-title">
      <div className="view-heading"><div><h1 id="scores-title">Topic scores</h1><p className="view-description">Independent completion, practice activity, and the evidence behind them</p></div>
        {data && <span className="language-chip">{data.language}</span>}
      </div>
      {scores.error && <div className="message error" role="alert"><strong>Scores could not be refreshed</strong><p>{scores.error}</p></div>}
      {progress.error && <div className="message warning" role="alert"><strong>Practice activity could not be refreshed</strong><p>{progress.error}</p></div>}
      {progressData && <div className="stat-row">
        <StatTile label="Recorded problems" value={String(problemTotal)} detail="Latest A–D result per problem" />
        <StatTile label="Independent AC" value={problemTotal ? `${Math.round((100 * independent) / problemTotal)}%` : "No data"} detail={`${independent} of ${problemTotal} ${problemTotal === 1 ? "problem" : "problems"}`} />
        <StatTile label="Stable" value={String(stable)} detail="From spaced practice" />
        <StatTile label="Practice days" value={String(progressData.days.length)} detail={minutes ? `${formatMinutes(minutes)} recorded` : "No time recorded"} />
        {data && <StatTile label="Topics practiced" value={`${practiced.length}/${data.topics.length}`} detail="Topics with A–D evidence" />}
      </div>}
      {progressData && today && <ActivityChart days={progressData.days} endDate={today} />}
      {scores.loading && !data && <div className="loading-panel" role="status">Reading your topic evidence…</div>}
      {data && <section className="scores-panel" aria-labelledby="topics-title">
        <div className="panel-heading">
          <div><h2 id="topics-title">{data.topics.length} topics</h2><p>{scores.loading ? "Refreshing…" : "Rate = independent A results ÷ problems with A–D evidence"}</p></div>
          {practiced.length > 1 && <div className="segmented" role="group" aria-label="Sort topics">
            <button type="button" aria-pressed={sort === "weakest"} onClick={sortWeakest}>Weakest first</button>
            <button type="button" aria-pressed={sort === "practiced"} onClick={sortPracticed}>Most practiced</button>
            <button type="button" aria-pressed={sort === "name"} onClick={sortName}>Name</button>
          </div>}
        </div>
        {practiced.length ? <><ResultLegend keys={["A", "B", "C", "D"]} /><ul className="topic-list">{practiced.map(renderTopic)}</ul></>
          : <div className="empty-state"><h2>No topic evidence yet</h2><p>Save a result from an existing plan to start building your record.</p></div>}
        {untouched.length > 0 && <div className="untouched"><h3>Not practiced yet <span>{untouched.length}</span></h3><ul className="chip-list">{untouched.map(renderUntouched)}</ul></div>}
      </section>}
      <p className="quiet-note">Results are self-reported. Each problem counts once with its latest valid A–D result. A small sample has fewer than five problems. E, F, and unanswered results do not count toward the score. Stable counts come from spaced practice.</p>
    </section>
  );
}
