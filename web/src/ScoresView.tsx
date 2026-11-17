/** File purpose: Show topic evidence without treating one AC as stable mastery. */
import type { Scores, Topic } from "./types";

/**
 * Inputs: One topic score and its separate evidence counts.
 * Outputs: One table row with the rate and its supporting evidence.
 * Logic: Keep absent data, independent success, and stable mastery distinct.
 * Dependencies: The topic score API contract.
 */
function TopicRow({ topic }: { topic: Topic }) {
  const width = Math.min(100, Math.max(0, topic.score ?? 0));
  return (
    <tr className="topic-row" data-topic={topic.tag} role="row">
      <th className="topic-name" scope="row" role="rowheader"><h3>{topic.tag.replaceAll("-", " ")}</h3>
        <p className="topic-results">A {topic.results.A} <span>·</span> B {topic.results.B} <span>·</span> C {topic.results.C} <span>·</span> D {topic.results.D}</p>
        {topic.sample_small && <span className="sample-badge">Small sample</span>}
      </th>
      <td className="topic-score" role="cell"><div className="score-line"><strong>{topic.score === null ? "No data" : `${topic.score}%`}</strong>
        <span className="score-evidence">{topic.score === null ? "No recorded A–D results" : `${topic.independent_count}/${topic.problem_count} independent`}</span></div>
        {topic.score !== null && <div className="score-track" aria-hidden="true"><span style={{ width: `${width}%` }} /></div>}
      </td>
      <td className="topic-count" role="cell"><strong>{topic.problem_count}</strong><span className="count-label">Recorded problems</span></td>
      <td className="topic-count" role="cell"><strong>{topic.stable_count}</strong><span className="count-label">Stable</span></td>
    </tr>
  );
}

/**
 * Inputs: A score response, loading state, and optional request error.
 * Outputs: The topic score view for the selected language.
 * Logic: Explain the score basis and render each topic without inventing values.
 * Dependencies: TopicRow and the scores API.
 */
export function ScoresView({ scores, loading, error }: { scores: Scores | null; loading: boolean; error: string | null }) {
  /**
   * Inputs: One topic from the score response.
   * Outputs: A keyed topic row.
   * Logic: Preserve the server's topic order and evidence.
   * Dependencies: TopicRow.
   */
  function renderTopic(topic: Topic) { return <TopicRow key={topic.tag} topic={topic} />; }
  return (
    <section aria-labelledby="scores-title">
      <div className="view-heading"><div><h1 id="scores-title">Topic scores</h1><p className="view-description">Independent completion and the evidence behind it</p></div>
        {scores && <span className="language-chip">{scores.language}</span>}
      </div>
      <div className="score-explainer"><p>The rate is independent A results divided by problems with A–D evidence, using each problem's latest valid result. Results are <strong>self-reported</strong>. Stable counts come from spaced practice.</p></div>
      {error && <div className="message error" role="alert"><strong>Scores could not be refreshed</strong><p>{error}</p></div>}
      {loading && !scores && <div className="loading-panel" role="status">Reading your topic evidence…</div>}
      {scores && <div className="scores-panel"><div className="scores-panel-heading"><h2>{scores.topics.length} topics</h2><span>{loading ? "Refreshing…" : "Current saved records"}</span></div>
        {scores.topics.length ? <div className="scores-table-scroll"><table className="scores-table" role="table">
          <caption className="sr-only">Topic completion rates and saved evidence for {scores.language}</caption>
          <thead role="rowgroup"><tr role="row"><th scope="col" role="columnheader">Topic</th><th scope="col" role="columnheader">Independent completion</th><th scope="col" role="columnheader">Recorded problems</th><th scope="col" role="columnheader">Stable</th></tr></thead>
          <tbody role="rowgroup">{scores.topics.map(renderTopic)}</tbody>
        </table></div> : <div className="empty-state"><h2>No topic evidence yet</h2><p>Save a result from an existing plan to start building your record.</p></div>}
      </div>}
      <p className="quiet-note">A small sample has fewer than five recorded problems. E, F, and unanswered results do not count toward the score.</p>
    </section>
  );
}
