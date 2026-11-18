/** File purpose: Edit one practice record with explicit modes and retry-safe saves. */
import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";
import { ApiError, errorMessage, request } from "./api";
import type { ComplexityItem, ComplexityStatus, Feedback, FeedbackRequest, PlanItem, Receipt, Result, SavedFeedback, SavedSolution, SolutionDocument, SolutionRequest } from "./types";

type Field = Exclude<keyof Feedback, "assistance">;
type Draft = Record<Field, string>;
type Mode = "" | "progress" | "correction";

export interface EditorDraft {
  values: Draft;
  touched: Set<Field>;
  mode: Mode;
  solution?: SolutionDocument;
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

const REVIEW_LABELS = {
  awaiting_code: "No code submitted",
  pending: "Code saved · awaiting review",
  supported: "Analysis supports this version",
  issues: "Review found an issue",
  insufficient_information: "More information needed",
  stale: "Review belongs to an earlier feedback version",
};

/**
 * Inputs: A saved review status and one conclusion field.
 * Outputs: The saved text when the field is present.
 * Logic: Read only known text fields from the structured review body.
 * Dependencies: The complexity status contract.
 */
function conclusion(item: ComplexityItem | null, field: string): string | null {
  const body = item?.review?.body;
  if (!body || typeof body !== "object") return null;
  const value = (body as Record<string, unknown>)[field];
  return typeof value === "string" ? value : null;
}

/**
 * Inputs: One attempt, its store, retained drafts, and shared lock callbacks.
 * Outputs: A code evidence form and the latest scoped review.
 * Logic: Save code without calling a model and retain uncertain submissions for retry.
 * Dependencies: React, the solution API, and immutable submission receipts.
 */
function SolutionForm({ item, storeId, drafts, disabled, onPendingChange, onReload, onWorkspaceMismatch }: {
  item: PlanItem; storeId: string; drafts: Map<string, EditorDraft>; disabled: boolean;
  onPendingChange: (id: string | null) => void; onReload: () => void; onWorkspaceMismatch: () => void;
}) {
  const draftKey = `${storeId}:${item.attempt_id}:solution`;
  const retained = drafts.get(draftKey)?.solution;
  const [document, setDocument] = useState<SolutionDocument>(retained ?? { code: "", language: item.attempt.language });
  const [dirty, setDirty] = useState(retained !== undefined);
  const [status, setStatus] = useState<ComplexityItem | null>(null);
  const [sending, setSending] = useState(false);
  const [pending, setPending] = useState<SolutionRequest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [workspaceMismatch, setWorkspaceMismatch] = useState(false);
  const locked = disabled || sending || pending !== null || conflict || workspaceMismatch;

  /**
   * Inputs: Mount or a changed attempt revision.
   * Outputs: The latest status and a cancellation handler.
   * Logic: Read only the bound attempt and ignore a response after unmount.
   * Dependencies: AbortController, the status endpoint, and current identity.
   */
  function loadReview() {
    const controller = new AbortController();
    /**
     * Inputs: None.
     * Outputs: A saved status or a visible read error.
     * Logic: Keep an unavailable review distinct from an unreviewed solution.
     * Dependencies: The bound request and effect cancellation signal.
     */
    async function readReview() {
      try {
        const data = await request<ComplexityStatus>(`/v1/attempts/${encodeURIComponent(item.attempt_id)}/complexity`, { headers: { "X-Coach-Store-Id": storeId }, signal: controller.signal });
        if (!controller.signal.aborted) setStatus(data.items[0] ?? null);
      } catch (failure) {
        if (!controller.signal.aborted) {
          setError(errorMessage(failure));
          if (failure instanceof ApiError && failure.code === "workspace_mismatch") {
            setWorkspaceMismatch(true);
            onWorkspaceMismatch();
          }
        }
      }
    }
    void readReview();
    /**
     * Inputs: Effect cleanup.
     * Outputs: Cancellation of an obsolete read.
     * Logic: Prevent late results from changing a different editor.
     * Dependencies: This effect's controller.
     */
    function cancelRead() { controller.abort(); }
    return cancelRead;
  }
  useEffect(loadReview, [item, storeId]);

  /**
   * Inputs: A changed code or input-size field.
   * Outputs: A retained in-page code draft.
   * Logic: Preserve exact source code without writing it until the user submits.
   * Dependencies: Controlled document state and the store-bound draft map.
   */
  function changeDocument(event: ChangeEvent<HTMLTextAreaElement | HTMLInputElement>) {
    const next = { ...document, [event.currentTarget.name]: event.currentTarget.value };
    setDocument(next);
    setDirty(true);
    drafts.set(draftKey, { values: makeDraft(null), touched: new Set(), mode: "", solution: next });
    setError(null);
  }

  /**
   * Inputs: A core receipt and the exact request being acknowledged.
   * Outputs: A confirmed code save and released navigation lock.
   * Logic: Match code identity, attempt, and feedback version before showing saved.
   * Dependencies: Immutable receipt fields and the retained operation.
   */
  async function acceptSolution(saved: SavedSolution, original: SolutionRequest) {
    const receipt = saved.receipt;
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(original.document.code));
    let expectedHash = "";
    for (const byte of new Uint8Array(digest)) expectedHash += byte.toString(16).padStart(2, "0");
    if (receipt.status !== "applied" || receipt.operation !== "record_solution" ||
        receipt.submission_id !== original.submission_id || receipt.attempt_id !== item.attempt_id ||
        receipt.feedback_revision !== original.expected_revision || !receipt.evidence_id || receipt.code_hash !== expectedHash || !receipt.payload_hash) {
      throw new Error("The code save receipt could not be matched.");
    }
    setPending(null);
    setDirty(false);
    setError(null);
    drafts.delete(draftKey);
    onPendingChange(null);
    setStatus({ attempt_id: item.attempt_id, feedback_revision: original.expected_revision, status: "pending", evidence: { id: receipt.evidence_id, code_hash: receipt.code_hash }, review: null });
  }

  /**
   * Inputs: A failed write or receipt lookup.
   * Outputs: A visible error and the appropriate retry or reload state.
   * Logic: Keep uncertain writes pending and never switch their bound database.
   * Dependencies: ApiError, shared navigation state, and the original draft.
   */
  function failSolution(failure: unknown) {
    if (failure instanceof ApiError && failure.code === "workspace_mismatch") {
      setWorkspaceMismatch(true);
      onWorkspaceMismatch();
    } else if (failure instanceof ApiError && failure.status >= 400 && failure.status < 500) {
      setPending(null);
      onPendingChange(null);
      setConflict(failure.status === 409);
    }
    setError(`Code save not confirmed. ${errorMessage(failure)}`);
  }

  /**
   * Inputs: One immutable solution operation.
   * Outputs: Its committed receipt or a retained uncertain operation.
   * Logic: Keep the same submission identity for network and response-loss retries.
   * Dependencies: The store-bound solution endpoint and receipt validator.
   */
  async function sendSolution(original: SolutionRequest) {
    setSending(true);
    setPending(original);
    setError(null);
    onPendingChange(item.attempt_id);
    try {
      const saved = await request<SavedSolution>(`/v1/attempts/${encodeURIComponent(item.attempt_id)}/solution`, {
        method: "POST", headers: { "Content-Type": "application/json", "X-Coach-Store-Id": storeId }, body: JSON.stringify(original),
      });
      await acceptSolution(saved, original);
    } catch (failure) {
      failSolution(failure);
    } finally {
      setSending(false);
    }
  }

  /**
   * Inputs: An explicit code form submission.
   * Outputs: One operation bound to the currently saved feedback revision.
   * Logic: Never submit unsaved feedback changes as part of code evidence.
   * Dependencies: The current document, revision, and browser UUID generator.
   */
  function submitSolution(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (locked || !dirty || !document.code.trim()) return;
    const body: SolutionDocument = { code: document.code, language: item.attempt.language };
    if (document.input_definition?.trim()) body.input_definition = document.input_definition;
    void sendSolution({ submission_id: crypto.randomUUID(), expected_revision: item.attempt.revision, document: body });
  }

  /**
   * Inputs: A retry click after an uncertain save.
   * Outputs: Confirmation from the receipt or the identical operation retried.
   * Logic: Read before resending; a timeout never establishes that a write failed.
   * Dependencies: The pending request, receipt endpoint, and sendSolution.
   */
  async function retrySolution() {
    if (!pending || sending || disabled || workspaceMismatch) return;
    const original = pending;
    setSending(true);
    try {
      const saved = await request<SavedSolution>(`/v1/submissions/${encodeURIComponent(original.submission_id)}`, { headers: { "X-Coach-Store-Id": storeId } });
      await acceptSolution(saved, original);
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 404) await sendSolution(original);
      else failSolution(failure);
    } finally {
      setSending(false);
    }
  }

  return <form className="feedback-form solution-form" onSubmit={submitSolution}>
    <details className="solution-details">
      <summary>Code and complexity review</summary>
      <p className="form-note" aria-live="polite">{status ? REVIEW_LABELS[status.status] : "Loading review status…"}</p>
      {status?.review && <div className="saved-summary"><span>Time: {conclusion(status, "time_complexity") ?? "Not determined"} · Space: {conclusion(status, "space_complexity") ?? "Not determined"}</span></div>}
      {status?.review && <p className="form-note">{conclusion(status, "reasoning")}</p>}
      <p className="form-note">Save your feedback changes first. Code is reviewed when your Skill session runs; saving code does not confirm AC or independent mastery.</p>
      <fieldset className="optional-grid" disabled={locked}>
        <label className="field full-width"><span>Solution code <small>{item.attempt.language}</small></span><textarea name="code" value={document.code} onChange={changeDocument} rows={8} maxLength={200000} spellCheck={false} placeholder="Paste the code for this attempt" /></label>
        <label className="field full-width"><span>Input sizes <small>optional</small></span><input name="input_definition" value={document.input_definition ?? ""} onChange={changeDocument} maxLength={4000} placeholder="For example, n is the array length" /></label>
      </fieldset>
      {error && <div className="message error" role="alert"><p>{error}</p>{conflict && <button type="button" className="secondary-button" onClick={onReload}>Reload current record</button>}</div>}
      <div className="form-footer"><span className="save-state" aria-live="polite">{sending ? "Saving code…" : pending ? "Code save awaiting confirmation" : dirty ? "Unsaved code · kept in this page" : "Code and feedback stay separate"}</span>
        {pending && !sending && !workspaceMismatch ? <button type="button" className="primary-button" disabled={disabled} onClick={retrySolution}>Retry code save</button> : <button type="submit" className="primary-button" disabled={locked || !dirty || !document.code.trim()}>Save code for review</button>}
      </div>
    </details>
  </form>;
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
  const [solutionPending, setSolutionPending] = useState(false);
  const workspaceMismatch = workspaceLocked || error?.workspaceMismatch === true;
  const locked = sending || pending !== null || acknowledged || solutionPending || error?.conflict === true || workspaceMismatch;
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

  /**
   * Inputs: The attempt with an uncertain code write, or null after resolution.
   * Outputs: Shared navigation and feedback locks.
   * Logic: Prevent feedback changes from racing a code evidence submission.
   * Dependencies: The parent's pending callback and local lock state.
   */
  function handleSolutionPending(id: string | null) {
    setSolutionPending(id !== null);
    onPendingChange(id);
  }

  return (
    <>
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
    <SolutionForm item={item} storeId={boundStoreId} drafts={drafts} disabled={sending || pending !== null || error?.conflict === true || workspaceMismatch || touched.size > 0}
      onPendingChange={handleSolutionPending} onReload={onReload} onWorkspaceMismatch={onWorkspaceMismatch} />
    </>
  );
}
