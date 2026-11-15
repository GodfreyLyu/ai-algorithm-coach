/** File purpose: Show topic evidence without treating one AC as stable mastery. */
import type { Scores, Topic } from "./types";

/**
 * Inputs: One topic score and its separate evidence counts.
 * Outputs: A readable topic row with a bounded score bar.
 * Logic: Keep absent data, independent success, and stable mastery distinct.
 * Dependencies: The topic score API contract.
 */
function TopicRow({ topic }: { topic: Topic }) {
  const width = Math.min(100, Math.max(0, topic.score ?? 0));
  return (
    <article className="topic-row" data-topic={topic.tag}>
      <div className="topic-name"><h3>{topic.tag.replaceAll("-", " ")}</h3>
        <p>A {topic.results.A} <span>·</span> B {topic.results.B} <span>·</span> C {topic.results.C} <span>·</span> D {topic.results.D}</p>
        {topic.sample_small && <span className="sample-badge">Small sample</span>}
      </div>
      <div className="topic-score"><div className="score-line"><strong>{topic.score === null ? "No data" : `${topic.score}%`}</strong><span>independent completion</span></div>
        {topic.score === null ? <div className="score-track empty" aria-hidden="true" /> : <div className="score-track" role="progressbar" aria-label={`${topic.tag} independent completion`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={topic.score}><span style={{ width: `${width}%` }} /></div>}
      </div>
      <div className="topic-count"><strong>{topic.problem_count}</strong><span>recorded problems</span></div>
      <div className="topic-count"><strong>{topic.independent_count}</strong><span>independent</span></div>
      <div className="topic-count"><strong>{topic.stable_count}</strong><span>stable</span></div>
    </article>
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
      <div className="view-heading"><div><p className="eyebrow">A view of your evidence</p><h1 id="scores-title">Topic scores</h1><p className="view-description">Independent completion, one problem at a time.</p></div>
        {scores && <span className="language-chip">{scores.language}</span>}
      </div>
      <div className="score-explainer"><span className="note-icon" aria-hidden="true">i</span><p>Scores use the latest A–D result for each problem: independent A results divided by recorded problems. All results are <strong>self-reported</strong>. Stable counts come from spaced practice, not this percentage.</p></div>
      {error && <div className="message error" role="alert"><strong>Scores could not be refreshed.</strong><p>{error}</p></div>}
      {loading && !scores && <div className="loading-panel" role="status">Reading your topic evidence…</div>}
      {scores && <div className="scores-panel"><div className="scores-panel-heading"><h2>{scores.topics.length} topics</h2><span>{loading ? "Refreshing…" : "Current saved records"}</span></div>
        {scores.topics.length ? scores.topics.map(renderTopic) : <div className="empty-state"><h2>No topic evidence yet</h2><p>Save a result from an existing plan to start building your record.</p></div>}
      </div>}
      <p className="quiet-note">A small sample has fewer than five recorded problems. E, F, and unanswered results do not count toward the score.</p>
    </section>
  );
}
