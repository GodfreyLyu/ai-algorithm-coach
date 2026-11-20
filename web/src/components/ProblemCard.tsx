/** File purpose: Show one planned problem's metadata and its attempt editor. */
import { RESULT_LABELS, reasonLabel, tagLabel } from "../constants";
import type { DraftStore } from "../drafts";
import type { PlanItem } from "../types";
import { AttemptEditor, type SaveSummary } from "./AttemptEditor";

/**
 * Inputs: A tag from this problem's metadata.
 * Outputs: A compact metadata label.
 * Logic: Render source tags without interpreting them as mastery.
 * Dependencies: tagLabel.
 */
function renderTag(tag: string) { return <span key={tag} className="tag">{tagLabel(tag)}</span>; }

/**
 * Inputs: A selected plan item, bound store ID, retained drafts, and shared callbacks.
 * Outputs: The problem header and its always-visible editor.
 * Logic: Show current evidence before editing a specific stable attempt.
 * Dependencies: AttemptEditor and the saved plan contract.
 */
export function ProblemCard({ item, storeId, drafts, planCurrent, workspaceLocked, onSaved, onPendingChange, onReload, onWorkspaceMismatch }: {
  item: PlanItem; storeId: string; drafts: DraftStore; planCurrent: boolean; workspaceLocked: boolean;
  onSaved: (summary: SaveSummary) => void; onPendingChange: (id: string | null) => void; onReload: () => void;
  onWorkspaceMismatch: () => void;
}) {
  const feedback = item.attempt.feedback;
  const result = feedback?.result;
  return (
    <article className="problem-card" data-attempt-id={item.attempt_id} aria-labelledby={`problem-${item.attempt_id}`}>
      <div className="problem-header">
        <div className="problem-content"><h2 id={`problem-${item.attempt_id}`}><span className="problem-id">{item.problem.id.replace("leetcode:", "#")}</span>{" "}<a href={item.problem.url} target="_blank" rel="noreferrer">{item.problem.title}<span aria-hidden="true"> ↗</span></a></h2>
          <div className="problem-meta"><span className={`chip difficulty ${item.problem.difficulty}`}>{item.problem.difficulty}</span><span className="chip reason-label">{reasonLabel(item.reason)}</span><span className="problem-tags">{item.problem.tags.map(renderTag)}</span></div>
        </div>
        <div className="problem-summary"><div className="problem-status"><span className={`result-letter ${result ? `result-${result}` : "empty"}`} aria-hidden="true">{result ?? "–"}</span>
          <span>{result ? `${result} · ${RESULT_LABELS[result]}` : "No result recorded"}</span></div>
          {feedback?.elapsed_minutes != null && <div className="problem-time">{feedback.elapsed_minutes} <span className="time-unit">min</span></div>}
        </div>
      </div>
      <AttemptEditor key={`${storeId}:${item.attempt_id}:${item.attempt.revision}`} item={item} storeId={storeId} drafts={drafts}
        planCurrent={planCurrent} workspaceLocked={workspaceLocked} onSaved={onSaved} onPendingChange={onPendingChange} onReload={onReload} onWorkspaceMismatch={onWorkspaceMismatch} />
    </article>
  );
}
