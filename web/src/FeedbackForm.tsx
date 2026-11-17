/** File purpose: Edit one practice record with explicit modes and retry-safe saves. */
import { useState, type ChangeEvent, type FormEvent } from "react";
import { ApiError, errorMessage, request } from "./api";
import type { Feedback, FeedbackRequest, PlanItem, Receipt, Result, SavedFeedback } from "./types";

type Field = Exclude<keyof Feedback, "assistance">;
type Draft = Record<Field, string>;
type Mode = "" | "progress" | "correction";

export interface EditorDraft {
  values: Draft;
  touched: Set<Field>;
  mode: Mode;
}

const RESULTS: { value: Result; label: string; detail: string }[] = [
  { value: "A", label: "Independent AC", detail: "No hints" },
  { value: "B", label: "AC with hints", detail: "Some help" },
  { value: "C", label: "AC after answer", detail: "Read a solution" },
  { value: "D", label: "Not yet AC", detail: "Keep working" },
  { value: "E", label: "Defer", detail: "Do it later" },
  { value: "F", label: "Skip", detail: "End this attempt" },
];

interface FormProps {
  item: PlanItem;
  storeId: string;
  drafts: Map<string, EditorDraft>;
  workspaceLocked: boolean;
  onSaved: (receipt: Receipt) => void;
  onPendingChange: (attemptId: string | null) => void;
  onReload: () => void;
  onWorkspaceMismatch: () => void;
}

/**
 * Inputs: An optional saved feedback snapshot.
 * Outputs: String values for the controlled form.
 * Logic: Preserve false and zero while displaying unanswered fields as blank.
 * Dependencies: The feedback API contract.
 */
function makeDraft(feedback: Feedback | null): Draft {
  return {
    result: feedback?.result ?? "",
    elapsed_minutes: feedback?.elapsed_minutes == null ? "" : String(feedback.elapsed_minutes),
    blocked_on: feedback?.blocked_on ?? "",
    explanation: feedback?.explanation ?? "",
    boundary_tests: feedback?.boundary_tests == null ? "" : String(feedback.boundary_tests),
    proficiency: feedback?.proficiency == null ? "" : String(feedback.proficiency),
    time_complexity: feedback?.time_complexity ?? "",
    space_complexity: feedback?.space_complexity ?? "",
    defer_until: feedback?.defer_until ?? "",
    skip_until: feedback?.skip_until ?? "",
  };
}

/**
 * Inputs: Current form strings and the explicitly changed fields.
 * Outputs: A partial feedback change object.
 * Logic: Convert only touched values. Keep null distinct from false and zero.
 * Dependencies: The feedback field types.
 */
function makeChanges(draft: Draft, touched: Set<Field>): Partial<Feedback> {
  const changes: Record<string, unknown> = {};
  for (const field of touched) {
    const value = draft[field].trim();
    if (value === "") {
      changes[field] = null;
    } else if (field === "elapsed_minutes" || field === "proficiency") {
      const number = Number(value);
      if (!Number.isFinite(number) || number < 0) throw new Error("Enter a valid non-negative number.");
      if (field === "proficiency" && (!Number.isInteger(number) || number < 1 || number > 5)) {
        throw new Error("Proficiency must be a whole number from 1 to 5.");
      }
      changes[field] = number;
    } else if (field === "boundary_tests") {
      changes[field] = value === "true";
    } else {
      changes[field] = value;
    }
  }
  return changes as Partial<Feedback>;
}

/**
 * Inputs: Submitted changes and the immutable saved change record.
 * Outputs: Whether both describe exactly the same primitive field changes.
 * Logic: Compare keys and values without relying on JSON key order.
 * Dependencies: The flat feedback field contract.
 */
function sameChanges(expected: Partial<Feedback>, saved: Partial<Feedback>): boolean {
  const keys = Object.keys(expected) as (keyof Feedback)[];
  if (keys.length !== Object.keys(saved).length) return false;
  for (const key of keys) if (!Object.hasOwn(saved, key) || expected[key] !== saved[key]) return false;
  return true;
}

/**
 * Inputs: One result option, its selection state, and a selection handler.
 * Outputs: An accessible single-choice outcome.
 * Logic: Forward a deliberate choice without setting an implicit default.
 * Dependencies: React and the parent form.
 */
function ResultChoice({ option, selected, onSelect }: {
  option: typeof RESULTS[number]; selected: boolean; onSelect: (result: Result) => void;
}) {
  /**
   * Inputs: A native radio selection.
   * Outputs: The explicit result value to the parent.
   * Logic: Select only the value belonging to this radio.
   * Dependencies: The onSelect prop.
   */
  function selectResult() { onSelect(option.value); }
  return (
    <label className={`result-choice ${selected ? "selected" : ""}`} data-result={option.value}>
      <span className="result-letter">{option.value}</span>
      <span><strong>{option.label}</strong><small>{option.detail}</small></span>
      <input type="radio" name="result" value={option.value} checked={selected} onChange={selectResult} />
    </label>
  );
}

/**
 * Inputs: A saved item, bound store, workspace lock, and shared callbacks.
 * Outputs: A feedback form for one stable practice attempt.
 * Logic: Send changed fields, match committed receipts, and retain unknown saves.
 * Dependencies: React state, the local API, and browser UUID generation.
 */
export function FeedbackForm({ item, storeId, drafts, workspaceLocked, onSaved, onPendingChange, onReload, onWorkspaceMismatch }: FormProps) {
  const feedback = item.attempt.feedback;
  const [boundStoreId] = useState(storeId);
  const draftKey = `${boundStoreId}:${item.attempt_id}:${item.attempt.revision}`;
  const retained = drafts.get(draftKey);
  const isComplete = feedback?.result === "A" || feedback?.result === "B" || feedback?.result === "C";
  const [draft, setDraft] = useState<Draft>(retained?.values ?? makeDraft(feedback));
  const [touched, setTouched] = useState<Set<Field>>(retained?.touched ?? new Set());
  const [mode, setMode] = useState<Mode>(retained?.mode ?? (isComplete ? "" : "progress"));
  const [sending, setSending] = useState(false);
  const [pending, setPending] = useState<FeedbackRequest | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [error, setError] = useState<{ message: string; conflict: boolean; workspaceMismatch?: boolean } | null>(null);
  const workspaceMismatch = workspaceLocked || error?.workspaceMismatch === true;
  const locked = sending || pending !== null || acknowledged || error?.conflict === true || workspaceMismatch;
  const editDisabled = locked || mode === "";

  /**
   * Inputs: A field name and its explicit new string value.
   * Outputs: Updated local draft and touched-field set.
   * Logic: Preserve every other field and clear a prior validation message.
   * Dependencies: The controlled form state.
   */
  function changeField(field: Field, value: string) {
    if (editDisabled) return;
    const values = { ...draft, [field]: value };
    const fields = new Set(touched).add(field);
    setDraft(values);
    setTouched(fields);
    drafts.set(draftKey, { values, touched: fields, mode });
    setError(null);
  }

  /**
   * Inputs: A change from a named input, select, or textarea.
   * Outputs: One updated draft field.
   * Logic: Read the field name and retain its controlled value.
   * Dependencies: changeField and the known form input names.
   */
  function handleFieldChange(event: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) {
    changeField(event.currentTarget.name as Field, event.currentTarget.value);
  }

  /**
   * Inputs: An explicit outcome choice.
   * Outputs: An updated result field.
   * Logic: Mark the outcome as touched without changing optional answers.
   * Dependencies: changeField.
   */
  function handleResultChange(result: Result) { changeField("result", result); }

  /**
   * Inputs: A click to clear the reported outcome.
   * Outputs: An explicit null outcome on the next correction.
   * Logic: Clear only when correction mode is selected.
   * Dependencies: changeField and mode state.
   */
  function clearResult() { if (mode === "correction") changeField("result", ""); }

  /**
   * Inputs: An explicit choice of progress or correction mode.
   * Outputs: The selected editing mode.
   * Logic: Never infer correction from edits to a completed record.
   * Dependencies: The mode select and local state.
   */
  function handleModeChange(event: ChangeEvent<HTMLSelectElement>) {
    const nextMode = event.currentTarget.value as Mode;
    setMode(nextMode);
    if (touched.size) drafts.set(draftKey, { values: draft, touched, mode: nextMode });
    setError(null);
  }

  /**
   * Inputs: A server acknowledgment and the original pending request.
   * Outputs: A confirmed-save notification or an unmatched-receipt error.
   * Logic: Match identity and revision before releasing the pending operation.
   * Dependencies: The receipt contract and parent refresh handlers.
   */
  function acceptReceipt(saved: SavedFeedback, original: FeedbackRequest) {
    const receipt = saved.receipt;
    if (receipt.status !== "applied" || receipt.submission_id !== original.submission_id ||
        receipt.attempt_id !== item.attempt_id || receipt.operation !== "submit_feedback" ||
        receipt.revision !== original.expected_revision + 1 ||
        saved.feedback_revision.revision !== receipt.revision ||
        saved.feedback_revision.attempt_id !== item.attempt_id ||
        saved.feedback_revision.submission_id !== original.submission_id ||
        saved.feedback_revision.kind !== original.kind ||
        !sameChanges(original.changes, saved.feedback_revision.changes) || !receipt.payload_hash) {
      throw new Error("The save receipt could not be matched.");
    }
    setAcknowledged(true);
    setPending(null);
    setError(null);
    drafts.delete(draftKey);
    onPendingChange(null);
    onSaved(receipt);
  }

  /**
   * Inputs: A failed save or receipt lookup.
   * Outputs: A visible error while keeping the user's input.
   * Logic: Lock a changed workspace; retain uncertain requests and reject stale edits.
   * Dependencies: ApiError and parent pending state.
   */
  function handleSaveError(failure: unknown) {
    if (failure instanceof ApiError && failure.code === "workspace_mismatch") {
      setError({ message: "This service now uses another training database. Start a new session in your Skill and use its feedback link. Your draft is still here.", conflict: false, workspaceMismatch: true });
      onWorkspaceMismatch();
    } else if (failure instanceof ApiError && failure.status >= 400 && failure.status < 500) {
      setPending(null);
      onPendingChange(null);
      setError({ message: failure.message, conflict: failure.status === 409 });
    } else {
      setError({ message: `Save not confirmed. ${errorMessage(failure)}`, conflict: false });
    }
  }

  /**
   * Inputs: The immutable operation payload for this user action.
   * Outputs: A committed acknowledgment or a retained pending request.
   * Logic: Bind the store and keep operation identity stable across retries.
   * Dependencies: The feedback endpoint and receipt validation.
   */
  async function sendRequest(original: FeedbackRequest) {
    setSending(true);
    setError(null);
    setPending(original);
    onPendingChange(item.attempt_id);
    try {
      const saved = await request<SavedFeedback>(`/v1/attempts/${encodeURIComponent(item.attempt_id)}/feedback`, {
        method: "POST", headers: { "Content-Type": "application/json", "X-Coach-Store-Id": boundStoreId }, body: JSON.stringify(original),
      });
      acceptReceipt(saved, original);
    } catch (failure) {
      handleSaveError(failure);
    } finally {
      setSending(false);
    }
  }

  /**
   * Inputs: A submitted form event.
   * Outputs: One new save operation for explicitly changed fields.
   * Logic: Validate local values and retain the current expected server revision.
   * Dependencies: makeChanges, browser crypto, and sendRequest.
   */
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (editDisabled || touched.size === 0) return;
    try {
      const original: FeedbackRequest = {
        submission_id: crypto.randomUUID(), expected_revision: item.attempt.revision,
        kind: mode, changes: makeChanges(draft, touched),
      };
      void sendRequest(original);
    } catch (failure) {
      setError({ message: failure instanceof Error ? failure.message : "Check the entered values.", conflict: false });
    }
  }

  /**
   * Inputs: A retry click for an uncertain operation.
   * Outputs: Confirmation from its receipt or a retry of the exact original body.
   * Logic: Check the original store's receipt before resending the same operation.
   * Dependencies: pending state, the receipt endpoint, and sendRequest.
   */
  async function retryPending() {
    if (!pending || sending || workspaceMismatch) return;
    const original = pending;
    setSending(true);
    setError(null);
    try {
      const saved = await request<SavedFeedback>(`/v1/submissions/${encodeURIComponent(original.submission_id)}`, { headers: { "X-Coach-Store-Id": boundStoreId } });
      acceptReceipt(saved, original);
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === "workspace_mismatch") handleSaveError(failure);
      else if (failure instanceof ApiError && failure.status === 404) await sendRequest(original);
      else setError({ message: `Save not confirmed. ${errorMessage(failure)}`, conflict: false });
    } finally {
      setSending(false);
    }
  }

  /**
   * Inputs: A deliberate reload after a revision conflict.
   * Outputs: The current saved record without its stale draft.
   * Logic: Discard this revision's input only after the reload action.
   * Dependencies: The in-memory draft map and parent reload handler.
   */
  function reloadRecord() {
    drafts.delete(draftKey);
    onReload();
  }

  /**
   * Inputs: A result option from the fixed outcome list.
   * Outputs: A keyed outcome choice.
   * Logic: Pass only the explicit form result and selection callback.
   * Dependencies: ResultChoice and the local draft.
   */
  function renderResult(option: typeof RESULTS[number]) {
    return <ResultChoice key={option.value} option={option} selected={draft.result === option.value} onSelect={handleResultChange} />;
  }

  return (
    <form className="feedback-form" onSubmit={handleSubmit}>
      {feedback && <div className="saved-summary"><span className="tiny-label">Saved record · revision {item.attempt.revision}</span>
        <span>{feedback.result ? `Result ${feedback.result}` : "Result not recorded"}{feedback.elapsed_minutes != null ? ` · ${feedback.elapsed_minutes} min` : ""}</span></div>}
      {feedback && <label className="field mode-field"><span>How are you updating this record?</span>
        <select value={mode} onChange={handleModeChange} disabled={locked}>
          <option value="">Choose an update</option><option value="progress">Add progress or details</option><option value="correction">Correct an earlier answer</option>
        </select></label>}
      {mode === "correction" && <p className="form-note">This adds a correction. Earlier answers stay in your history.</p>}
      <fieldset className="result-fieldset" disabled={editDisabled}>
        <legend>How did it go?</legend>
        <p className="result-group-label">Reported AC</p><div className="result-grid">{RESULTS.slice(0, 3).map(renderResult)}</div>
        <p className="result-group-label">Continue or set aside</p><div className="result-grid">{RESULTS.slice(3).map(renderResult)}</div>
        {mode === "correction" && draft.result !== "" && <button type="button" className="text-button" onClick={clearResult}>Clear reported result</button>}
      </fieldset>
      <fieldset className="entry-fields" disabled={editDisabled}>
        {(draft.result === "E" || draft.defer_until !== "" || touched.has("defer_until")) && <label className="field schedule-field"><span>Defer until <small>for E</small></span><input type="date" name="defer_until" value={draft.defer_until} onChange={handleFieldChange} /><small>Optional date for deferred practice</small></label>}
        {(draft.result === "F" || draft.skip_until !== "" || touched.has("skip_until")) && <label className="field schedule-field"><span>Eligible again <small>for F</small></span><input type="date" name="skip_until" value={draft.skip_until} onChange={handleFieldChange} /><small>Optional date for this skipped problem to become eligible again</small></label>}
        <label className="field time-field"><span>Total time <small>minutes</small></span>
          <input type="number" min="0" step="any" inputMode="decimal" name="elapsed_minutes" value={draft.elapsed_minutes} onChange={handleFieldChange} placeholder="Not recorded" />
          <small>Use the total for this attempt, including earlier sessions.</small></label>
        <p className="form-note">Result changes use the current time. Corrections and detail-only updates keep the recorded practice time.</p>
        <details className="optional-details"><summary>More details <span>optional</span></summary>
          <div className="optional-grid">
            <label className="field full-width"><span>Where did you get stuck?</span><textarea name="blocked_on" value={draft.blocked_on} onChange={handleFieldChange} rows={2} maxLength={4000} placeholder="A brief note, if useful" /></label>
            <label className="field"><span>Explain the solution aloud</span><select name="explanation" value={draft.explanation} onChange={handleFieldChange}>
              <option value="">Not recorded</option><option value="not_tried">Not tried</option><option value="partial">Partly explained</option><option value="clear">Clearly explained</option><option value="uncertain">Uncertain</option></select></label>
            <label className="field"><span>Boundary tests checked?</span><select name="boundary_tests" value={draft.boundary_tests} onChange={handleFieldChange}>
              <option value="">Not recorded</option><option value="true">Yes</option><option value="false">No</option></select></label>
            <label className="field"><span>Familiarity</span><select name="proficiency" value={draft.proficiency} onChange={handleFieldChange}>
              <option value="">Not recorded</option><option value="1">1 · New to me</option><option value="2">2 · Needs support</option><option value="3">3 · Getting familiar</option><option value="4">4 · Comfortable</option><option value="5">5 · Very familiar</option></select></label>
            <label className="field"><span>Time complexity</span><input name="time_complexity" value={draft.time_complexity} onChange={handleFieldChange} maxLength={4000} placeholder="For example, O(n)" /></label>
            <label className="field"><span>Space complexity</span><input name="space_complexity" value={draft.space_complexity} onChange={handleFieldChange} maxLength={4000} placeholder="For example, O(1)" /></label>
          </div>
        </details>
      </fieldset>
      {error && <div className={`message ${error.conflict ? "warning" : "error"}`} role="alert"><strong>{workspaceMismatch ? "This is a different training workspace." : error.conflict ? "This record changed elsewhere." : "Your input is still here."}</strong><p>{error.message}</p>
        {error.conflict && <button type="button" className="secondary-button" onClick={reloadRecord}>Reload current record</button>}
      </div>}
      <div className="form-footer"><span className="save-state" aria-live="polite">{workspaceMismatch ? "Workspace changed · save unconfirmed" : sending ? "Saving…" : acknowledged ? "Saved to your record" : pending ? "Awaiting confirmation" : touched.size ? "Unsaved changes · kept in this page" : "Choose a result or add details"}</span>
        {pending && !sending && !workspaceMismatch ? <button type="button" className="primary-button" onClick={retryPending}>Retry this save</button> : <button type="submit" className="primary-button" disabled={editDisabled || touched.size === 0}>{sending ? "Saving…" : acknowledged ? "Saved" : "Save feedback"}</button>}
      </div>
      {pending && !sending && !workspaceMismatch && <p className="form-note">Keep this page open. Retry checks the same submission before sending it again.</p>}
    </form>
  );
}
