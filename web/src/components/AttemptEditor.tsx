/** File purpose: Edit code and feedback for one attempt and save both with one retry-safe action. */
import { useEffect, useReducer, useRef, useState, type ChangeEvent, type FormEvent, type KeyboardEvent } from "react";
import { ApiError, errorMessage, request } from "../api";
import { COMPLEXITIES, RESULT_LABELS, REVIEW_LABELS } from "../constants";
import { DETAIL_FIELDS, conclusion, makeChanges, makeDraft, solutionFromStatus, verifyFeedbackReceipt, verifySolutionReceipt,
  type Draft, type DraftStore, type Field, type Mode, type SolutionDraft } from "../drafts";
import type { ComplexityItem, ComplexityStatus, FeedbackRequest, PlanItem, Result, SavedFeedback, SavedSolution, SolutionDocument, SolutionRequest } from "../types";
import { ResultPicker } from "./ResultPicker";

export interface SaveSummary {
  attemptId: string;
  title: string;
  feedbackSaved: boolean;
  codeSaved: boolean;
  result: Result | null;
  codeError: string | null;
}

type SaveStep = "feedback" | "code";

type SaveState =
  | { phase: "idle" }
  | { phase: "saving"; step: SaveStep }
  | { phase: "uncertain"; step: SaveStep; message: string }
  | { phase: "failed"; message: string; conflict: boolean }
  | { phase: "saved" }
  | { phase: "mismatch" };

type SaveAction =
  | { type: "start"; step: SaveStep }
  | { type: "uncertain"; step: SaveStep; message: string }
  | { type: "fail"; message: string; conflict: boolean }
  | { type: "saved" }
  | { type: "mismatch" }
  | { type: "reset" };

type ReviewRead =
  | { item: PlanItem; phase: "ready"; status: ComplexityItem }
  | { item: PlanItem; phase: "failed"; message: string }
  | { item: PlanItem; phase: "changed" };

interface SavePlan {
  feedback: FeedbackRequest | null;
  feedbackDone: boolean;
  revision: number;
  document: SolutionDocument | null;
  solution: SolutionRequest | null;
  verifyFirst: boolean;
}

interface EditorProps {
  item: PlanItem;
  storeId: string;
  drafts: DraftStore;
  planCurrent: boolean;
  workspaceLocked: boolean;
  onSaved: (summary: SaveSummary) => void;
  onPendingChange: (attemptId: string | null) => void;
  onReload: () => void;
  onWorkspaceMismatch: () => void;
}

/**
 * Inputs: The current save state and one transition.
 * Outputs: The next save state.
 * Logic: Keep save phases explicit. A mismatch is final for this page.
 * Dependencies: The SaveState and SaveAction unions.
 */
function saveReducer(state: SaveState, action: SaveAction): SaveState {
  if (state.phase === "mismatch") return state;
  switch (action.type) {
    case "start": return { phase: "saving", step: action.step };
    case "uncertain": return { phase: "uncertain", step: action.step, message: action.message };
    case "fail": return { phase: "failed", message: action.message, conflict: action.conflict };
    case "saved": return { phase: "saved" };
    case "mismatch": return { phase: "mismatch" };
    case "reset": return state.phase === "saved" || (state.phase === "failed" && !state.conflict) ? { phase: "idle" } : state;
  }
}

/**
 * Inputs: A complexity field, its current value, and a change callback.
 * Outputs: A native select with presets and any existing custom value.
 * Logic: Preserve saved text exactly and leave untouched values unchanged.
 * Dependencies: The complexity presets and the shared field change handler.
 */
function ComplexitySelect({ name, label, value, onChange }: {
  name: "time_complexity" | "space_complexity"; label: string; value: string;
  onChange: (event: ChangeEvent<HTMLSelectElement>) => void;
}) {
  /**
   * Inputs: One supported complexity expression.
   * Outputs: A native option with its exact stored value.
   * Logic: Use the same text for display and feedback submission.
   * Dependencies: The complexity preset list.
   */
  function renderOption(complexity: string) { return <option key={complexity} value={complexity}>{complexity}</option>; }

  return <label className="field"><span>{label}</span><select name={name} aria-label={label} value={value} onChange={onChange}>
    <option value="">Not recorded</option>
    {value !== "" && !COMPLEXITIES.includes(value) && <option value={value}>{value}</option>}
    {COMPLEXITIES.map(renderOption)}
  </select></label>;
}

/**
 * Inputs: A keyboard event target.
 * Outputs: Whether the user is typing into a text control.
 * Logic: Treat text inputs, text areas, and selects as typing targets. Radios are not.
 * Dependencies: DOM element types.
 */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement || target.isContentEditable) return true;
  return target instanceof HTMLInputElement && !["radio", "checkbox", "button", "submit"].includes(target.type);
}

/**
 * Inputs: A feedback draft.
 * Outputs: Whether any optional detail field has a value.
 * Logic: Open the detail section when saved details exist.
 * Dependencies: The detail field list.
 */
function hasDetails(draft: Draft): boolean {
  for (const field of DETAIL_FIELDS) if (draft[field] !== "") return true;
  return false;
}

/**
 * Inputs: A key event.
 * Outputs: None.
 * Logic: Serve as the initial shortcut handler before the first render.
 * Dependencies: None.
 */
function ignoreKey(): void {}

/**
 * Inputs: Whether feedback and code will be saved, and the edit mode.
 * Outputs: A button label that names what the save includes.
 * Logic: Tell the user exactly which parts one click will write.
 * Dependencies: None.
 */
function saveLabel(feedback: boolean, code: boolean, mode: Mode): string {
  const first = mode === "correction" ? "correction" : "feedback";
  if (feedback && code) return `Save ${first} and code`;
  if (feedback) return `Save ${first}`;
  if (code) return "Save code";
  return mode === "correction" ? "Save correction" : "Save";
}

/**
 * Inputs: One attempt, its store, retained drafts, and shared lock callbacks.
 * Outputs: A code pane and a feedback pane that share one save action.
 * Logic: Save feedback first. Then bind code to the committed feedback revision.
 *   Keep uncertain steps for retry with the same submission IDs.
 * Dependencies: React, the feedback and solution APIs, and receipt validators.
 */
export function AttemptEditor({ item, storeId, drafts, planCurrent, workspaceLocked, onSaved, onPendingChange, onReload, onWorkspaceMismatch }: EditorProps) {
  const feedback = item.attempt.feedback;
  const [boundStoreId] = useState(storeId);
  const feedbackKey = `${boundStoreId}:${item.attempt_id}:${item.attempt.revision}`;
  const solutionKey = `${boundStoreId}:${item.attempt_id}`;
  const retained = drafts.feedback.get(feedbackKey);
  const [draft, setDraft] = useState<Draft>(retained?.values ?? makeDraft(feedback));
  const [touched, setTouched] = useState<Set<Field>>(retained?.touched ?? new Set());
  const [mode, setMode] = useState<Mode>(retained?.mode ?? "progress");
  const [codeDraft, setCodeDraft] = useState<SolutionDraft | null>(drafts.solution.get(solutionKey) ?? null);
  const [review, setReview] = useState<ReviewRead | null>(null);
  const [reviewRetry, setReviewRetry] = useState(0);
  const [approvedReview, setApprovedReview] = useState<ComplexityItem | null>(null);
  const [detailsOpen] = useState(hasDetails(draft));
  const [save, dispatch] = useReducer(saveReducer, workspaceLocked ? { phase: "mismatch" } : { phase: "idle" });
  const plan = useRef<SavePlan | null>(null);
  const tabEscape = useRef(false);
  const mismatch = workspaceLocked || save.phase === "mismatch";
  const editable = !mismatch && (save.phase === "idle" || save.phase === "saved" || (save.phase === "failed" && !save.conflict));
  const currentReview = review?.item === item ? review : null;
  const status = currentReview?.phase === "ready" ? currentReview.status : null;
  const reviewReady = planCurrent && status?.feedback_revision === item.attempt.revision;
  const savedCode = solutionFromStatus(status, item.attempt.language);
  const document = { ...(savedCode?.document ?? { code: "", language: item.attempt.language }), ...codeDraft };
  const codeDirty = codeDraft !== null;
  const hasCode = document.code.trim() !== "";
  const willSaveFeedback = touched.size > 0;
  const needsRebind = savedCode !== null && savedCode.revision !== item.attempt.revision && codeDraft?.code === undefined;
  const useEarlierCode = needsRebind && status === approvedReview;
  const willSaveCode = hasCode && (needsRebind ? useEarlierCode : codeDirty || willSaveFeedback);
  const canSave = editable && reviewReady && (willSaveFeedback || willSaveCode);

  /**
   * Inputs: Mount or a changed attempt.
   * Outputs: The latest review status and a cancellation handler.
   * Logic: Fetch saved evidence and its review together for the current plan.
   * Dependencies: AbortController and the status endpoint.
   */
  function loadReview() {
    if (!planCurrent || workspaceLocked) return;
    const controller = new AbortController();
    /**
     * Inputs: None.
     * Outputs: A validated saved snapshot, or a visible reload or read error.
     * Logic: Keep saved state separate from local edits. Check the plan revision.
     * Dependencies: request and solutionFromStatus.
     */
    async function readReview() {
      try {
        const data = await request<ComplexityStatus>(`/v1/attempts/${encodeURIComponent(item.attempt_id)}/complexity`, { headers: { "X-Coach-Store-Id": boundStoreId }, signal: controller.signal });
        if (controller.signal.aborted) return;
        const savedStatus = data.items[0];
        if (!savedStatus || savedStatus.attempt_id !== item.attempt_id ||
            (savedStatus.evidence !== null && !solutionFromStatus(savedStatus, item.attempt.language))) {
          setReview({ item, phase: "failed", message: "The local service returned an invalid code record." });
        } else if (savedStatus.feedback_revision !== item.attempt.revision) {
          setReview({ item, phase: "changed" });
        } else {
          setReview({ item, phase: "ready", status: savedStatus });
        }
      } catch (failure) {
        if (controller.signal.aborted) return;
        if (failure instanceof ApiError && failure.code === "workspace_mismatch") {
          dispatch({ type: "mismatch" });
          onWorkspaceMismatch();
        } else {
          setReview({ item, phase: "failed", message: errorMessage(failure) });
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
  useEffect(loadReview, [item, boundStoreId, planCurrent, workspaceLocked, reviewRetry]);

  /**
   * Inputs: A click after a failed review read.
   * Outputs: A new read of the same attempt.
   * Logic: Keep local drafts while retrying the read.
   * Dependencies: React state and loadReview.
   */
  function retryReview() {
    setReview(null);
    setReviewRetry(reviewRetry + 1);
  }

  /**
   * Inputs: A feedback field name and its new string value.
   * Outputs: Updated draft state and the retained in-page draft.
   * Logic: Track touched fields so untouched values are never sent.
   * Dependencies: The shared draft store.
   */
  function changeField(field: Field, value: string) {
    if (!editable) return;
    const values = { ...draft, [field]: value };
    const fields = new Set(touched).add(field);
    setDraft(values);
    setTouched(fields);
    drafts.feedback.set(feedbackKey, { values, touched: fields, mode });
    dispatch({ type: "reset" });
  }

  /**
   * Inputs: A change event from a named feedback control.
   * Outputs: One updated draft field.
   * Logic: Read the control name and value.
   * Dependencies: changeField.
   */
  function handleFieldChange(event: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) {
    changeField(event.currentTarget.name as Field, event.currentTarget.value);
  }

  /**
   * Inputs: A selected result.
   * Outputs: An updated result draft.
   * Logic: Forward to the shared field handler.
   * Dependencies: changeField.
   */
  function handleResultChange(result: Result) { changeField("result", result); }

  /**
   * Inputs: A clear click during correction.
   * Outputs: An explicit empty result in the draft.
   * Logic: Allow clearing only in correction mode.
   * Dependencies: changeField.
   */
  function clearResult() { if (mode === "correction") changeField("result", ""); }

  /**
   * Inputs: A correction toggle click.
   * Outputs: Correction mode, or restored saved values after cancel.
   * Logic: Cancel discards only the feedback draft. Code drafts stay.
   * Dependencies: makeDraft and the draft store.
   */
  function toggleCorrection() {
    if (!editable || !feedback) return;
    if (mode === "correction") {
      setMode("progress");
      setDraft(makeDraft(feedback));
      setTouched(new Set());
      drafts.feedback.delete(feedbackKey);
    } else {
      setMode("correction");
      drafts.feedback.set(feedbackKey, { values: draft, touched, mode: "correction" });
    }
    dispatch({ type: "reset" });
  }

  /**
   * Inputs: A solution field and its new value.
   * Outputs: A retained in-page code draft.
   * Logic: Keep only local field edits. Drop a field restored to its saved value.
   * Dependencies: The saved snapshot and draft store.
   */
  function changeSolutionField(field: keyof SolutionDraft, value: string) {
    if (!editable) return;
    const next = { ...codeDraft, [field]: value };
    if (status && value === (savedCode?.document[field] ?? "")) delete next[field];
    if (Object.keys(next).length > 0) {
      drafts.solution.set(solutionKey, next);
      setCodeDraft(next);
    } else {
      drafts.solution.delete(solutionKey);
      setCodeDraft(null);
    }
    dispatch({ type: "reset" });
  }

  /**
   * Inputs: A change event from a solution field.
   * Outputs: An updated draft field.
   * Logic: Forward the exact field value to the shared draft handler.
   * Dependencies: changeSolutionField.
   */
  function changeDocument(event: ChangeEvent<HTMLTextAreaElement | HTMLInputElement>) {
    changeSolutionField(event.currentTarget.name as keyof SolutionDraft, event.currentTarget.value);
  }

  /**
   * Inputs: A change to the earlier-code checkbox.
   * Outputs: User approval for this saved snapshot only.
   * Logic: Clear the approval when the checkbox is cleared.
   * Dependencies: The loaded review snapshot.
   */
  function toggleEarlierCode(event: ChangeEvent<HTMLInputElement>) {
    setApprovedReview(event.currentTarget.checked ? status : null);
  }

  /**
   * Inputs: A key press inside the code editor.
   * Outputs: An inserted indent for Tab, or normal focus movement.
   * Logic: Tab indents by four spaces. Escape lets the next Tab leave the editor.
   * Dependencies: The textarea selection API and changeSolutionField.
   */
  function handleCodeKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Escape") { tabEscape.current = true; return; }
    if (event.key !== "Tab" || event.shiftKey || event.metaKey || event.ctrlKey || event.altKey || tabEscape.current) {
      tabEscape.current = false;
      return;
    }
    event.preventDefault();
    const target = event.currentTarget;
    const start = target.selectionStart;
    const next = target.value.slice(0, start) + "    " + target.value.slice(target.selectionEnd);
    changeSolutionField("code", next);
    /**
     * Inputs: None.
     * Outputs: The caret placed after the inserted indent.
     * Logic: Wait for React to render the new value first.
     * Dependencies: requestAnimationFrame.
     */
    function placeCaret() { target.setSelectionRange(start + 4, start + 4); }
    requestAnimationFrame(placeCaret);
  }

  /**
   * Inputs: A submission path, request body, and whether to check first.
   * Outputs: The committed response data.
   * Logic: After an uncertain attempt, read the receipt before sending again.
   * Dependencies: request, ApiError, and the submissions endpoint.
   */
  async function confirmOrSend<T>(path: string, body: FeedbackRequest | SolutionRequest, verifyFirst: boolean): Promise<T> {
    const headers = { "X-Coach-Store-Id": boundStoreId };
    if (verifyFirst) {
      try {
        return await request<T>(`/v1/submissions/${encodeURIComponent(body.submission_id)}`, { headers });
      } catch (failure) {
        if (!(failure instanceof ApiError && failure.status === 404)) throw failure;
      }
    }
    return request<T>(path, { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(body) });
  }

  /**
   * Inputs: A finished save plan and an optional code error.
   * Outputs: Released navigation and a summary sent to the parent.
   * Logic: Report what was committed. The parent then reloads authority data.
   * Dependencies: onPendingChange and onSaved.
   */
  function finish(current: SavePlan, codeError: string | null) {
    plan.current = null;
    if (current.feedbackDone) setTouched(new Set());
    dispatch({ type: "saved" });
    onPendingChange(null);
    const result = current.feedback?.changes.result;
    onSaved({
      attemptId: item.attempt_id, title: item.problem.title, feedbackSaved: current.feedbackDone,
      codeSaved: current.document !== null && codeError === null, result: result ?? null, codeError,
    });
  }

  /**
   * Inputs: A failed step, its error, and the current plan.
   * Outputs: Mismatch, retry, failure, or partial-success state.
   * Logic: Never treat a lost response as failure. Report a rejected code step
   *   after committed feedback as a partial save.
   * Dependencies: ApiError, onWorkspaceMismatch, and finish.
   */
  function stop(failure: unknown, step: SaveStep, current: SavePlan) {
    if (failure instanceof ApiError && failure.code === "workspace_mismatch") {
      dispatch({ type: "mismatch" });
      onWorkspaceMismatch();
    } else if (failure instanceof ApiError && failure.status >= 400 && failure.status < 500) {
      if (step === "code" && current.feedbackDone) {
        finish(current, failure.message);
        return;
      }
      plan.current = null;
      onPendingChange(null);
      dispatch({ type: "fail", message: failure.message, conflict: failure.status === 409 });
    } else {
      current.verifyFirst = true;
      const message = failure instanceof Error && !(failure instanceof ApiError) && failure.message.includes("receipt") ? failure.message : errorMessage(failure);
      dispatch({ type: "uncertain", step, message: `Save not confirmed. ${message}` });
    }
  }

  /**
   * Inputs: A save plan.
   * Outputs: Committed feedback and code, or a stopped state.
   * Logic: Run the feedback step, then the code step with the committed revision.
   *   Completed steps are skipped on retry.
   * Dependencies: confirmOrSend, receipt validators, and the draft store.
   */
  async function run(current: SavePlan) {
    plan.current = current;
    onPendingChange(item.attempt_id);
    if (current.feedback && !current.feedbackDone) {
      dispatch({ type: "start", step: "feedback" });
      try {
        const saved = await confirmOrSend<SavedFeedback>(`/v1/attempts/${encodeURIComponent(item.attempt_id)}/feedback`, current.feedback, current.verifyFirst);
        current.revision = verifyFeedbackReceipt(saved, current.feedback, item.attempt_id);
        current.feedbackDone = true;
        current.verifyFirst = false;
        drafts.feedback.delete(feedbackKey);
      } catch (failure) {
        stop(failure, "feedback", current);
        return;
      }
    }
    if (current.document) {
      current.solution ??= { submission_id: crypto.randomUUID(), expected_revision: current.revision, document: current.document };
      dispatch({ type: "start", step: "code" });
      try {
        const saved = await confirmOrSend<SavedSolution>(`/v1/attempts/${encodeURIComponent(item.attempt_id)}/solution`, current.solution, current.verifyFirst);
        const evidence = await verifySolutionReceipt(saved, current.solution, item.attempt_id);
        drafts.solution.delete(solutionKey);
        setCodeDraft(null);
        setReview({ item, phase: "ready", status: {
          attempt_id: item.attempt_id, feedback_revision: current.revision, status: "pending",
          evidence: { id: evidence.evidenceId, code_hash: evidence.codeHash, feedback_revision: current.revision, body: current.document },
          review: null,
        } });
      } catch (failure) {
        stop(failure, "code", current);
        return;
      }
    }
    finish(current, null);
  }

  /**
   * Inputs: An explicit form submission or shortcut.
   * Outputs: A new save plan for the changed parts.
   * Logic: Include edits or eligible saved code only after a matching review read.
   * Dependencies: makeChanges, run, and the browser UUID generator.
   */
  function submit(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (save.phase === "uncertain") { void retry(); return; }
    if (!canSave) return;
    let feedbackRequest: FeedbackRequest | null = null;
    if (willSaveFeedback) {
      try {
        feedbackRequest = { submission_id: crypto.randomUUID(), expected_revision: item.attempt.revision, kind: mode, changes: makeChanges(draft, touched) };
      } catch (failure) {
        dispatch({ type: "fail", message: failure instanceof Error ? failure.message : "Check the entered values.", conflict: false });
        return;
      }
    }
    let body: SolutionDocument | null = null;
    if (willSaveCode) {
      body = { code: document.code, language: item.attempt.language };
      if (document.input_definition?.trim()) body.input_definition = document.input_definition;
    }
    void run({ feedback: feedbackRequest, feedbackDone: false, revision: item.attempt.revision, document: body, solution: null, verifyFirst: false });
  }

  /**
   * Inputs: A retry click after an uncertain step.
   * Outputs: The same plan continued from its uncertain step.
   * Logic: Reuse submission IDs and check receipts before sending again.
   * Dependencies: run and the retained plan.
   */
  async function retry() {
    if (save.phase !== "uncertain" || mismatch || !plan.current) return;
    await run(plan.current);
  }

  /**
   * Inputs: A reload click after a conflict.
   * Outputs: Discarded feedback draft and fresh authority data.
   * Logic: Keep code drafts. Ask the parent to reload.
   * Dependencies: The draft store and onReload.
   */
  function reloadRecord() {
    drafts.feedback.delete(feedbackKey);
    onReload();
  }

  const shortcut = useRef<(event: globalThis.KeyboardEvent) => void>(ignoreKey);
  /**
   * Inputs: A window key press.
   * Outputs: A selected result for A–F, or a save for Ctrl or Command with Enter.
   * Logic: Ignore letters while typing. Ignore everything while locked.
   * Dependencies: changeField, submit, and isTypingTarget.
   */
  shortcut.current = function handleShortcut(event: globalThis.KeyboardEvent) {
    if (event.defaultPrevented || mismatch) return;
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      if (canSave || save.phase === "uncertain") { event.preventDefault(); submit(); }
      return;
    }
    if (event.metaKey || event.ctrlKey || event.altKey || !editable || isTypingTarget(event.target)) return;
    const key = event.key.toUpperCase();
    if (key.length === 1 && "ABCDEF".includes(key)) {
      event.preventDefault();
      changeField("result", key);
    }
  };

  /**
   * Inputs: Mount.
   * Outputs: A window key listener and its removal on unmount.
   * Logic: Delegate to the latest handler through a ref.
   * Dependencies: The shortcut ref.
   */
  function listenShortcuts() {
    /**
     * Inputs: A window key event.
     * Outputs: The latest shortcut handler call.
     * Logic: Read the ref at event time.
     * Dependencies: The shortcut ref.
     */
    function forward(event: globalThis.KeyboardEvent) { shortcut.current(event); }
    window.addEventListener("keydown", forward);
    /**
     * Inputs: Effect cleanup.
     * Outputs: Removed key listener.
     * Logic: Avoid handlers from unmounted editors.
     * Dependencies: window.
     */
    function unlisten() { window.removeEventListener("keydown", forward); }
    return unlisten;
  }
  useEffect(listenShortcuts, []);

  let detailCount = 0;
  for (const field of DETAIL_FIELDS) if (draft[field] !== "") detailCount += 1;
  const lineCount = document.code === "" ? 0 : document.code.split("\n").length;
  let stateText = "No unsaved changes";
  if (mismatch) stateText = "Workspace changed · save unconfirmed";
  else if (save.phase === "saving") stateText = save.step === "feedback" ? "Saving feedback…" : "Saving code…";
  else if (save.phase === "uncertain") stateText = save.step === "code" && plan.current?.feedbackDone ? "Feedback saved · code awaiting confirmation" : "Save awaiting confirmation";
  else if (save.phase === "saved") stateText = "Saved to your record";
  else if (!reviewReady && (willSaveFeedback || codeDirty)) stateText = "Save waits for the current saved record";
  else if (willSaveFeedback && willSaveCode) stateText = "Unsaved feedback and code · kept in this page";
  else if (willSaveFeedback) stateText = "Unsaved feedback · kept in this page";
  else if (willSaveCode) stateText = "Unsaved code · kept in this page";
  else if (codeDirty) stateText = hasCode ? "Unsaved code draft · kept in this page" : "Add code before saving it";
  const label = save.phase === "saving" ? "Saving…" : save.phase === "saved" ? "Saved" : saveLabel(willSaveFeedback, willSaveCode, mode);
  const reviewUnavailable = currentReview?.phase === "failed" || currentReview?.phase === "changed";
  const reviewText = status ? `${codeDirty && status.evidence ? "Saved version · " : ""}${REVIEW_LABELS[status.status]}`
    : reviewUnavailable ? "Review status unavailable" : "Loading review status…";

  return (
    <form className="attempt-editor" onSubmit={submit} aria-label={`Record ${item.problem.title}`}>
      <section className="solution-pane" aria-labelledby={`code-${item.attempt_id}`}>
        <div className="pane-heading"><h3 id={`code-${item.attempt_id}`}>Solution code <span className="pane-subtle">{item.attempt.language}</span></h3>
          <span className={`review-pill review-${status?.status ?? "loading"}`} aria-live="polite">{reviewText}</span></div>
        <fieldset className="solution-fields" disabled={!editable}>
          <label className="field solution-code-field"><span className="sr-only">Solution code</span>
            <textarea className="solution-code" name="code" value={document.code} onChange={changeDocument} onKeyDown={handleCodeKey} rows={16} wrap="off" maxLength={200000} spellCheck={false} placeholder="Paste the code for this attempt" /></label>
          <div className="code-meta"><span>{lineCount} {lineCount === 1 ? "line" : "lines"}</span><span>Tab indents · Esc then Tab leaves</span></div>
          <label className="field"><span>Input sizes <small>optional</small></span><input name="input_definition" value={document.input_definition ?? ""} onChange={changeDocument} maxLength={4000} placeholder="For example, n is the array length" /></label>
          {needsRebind && <label className="toggle"><input type="checkbox" checked={useEarlierCode} onChange={toggleEarlierCode} disabled={!reviewReady} /> <span>Use code from the earlier feedback version</span></label>}
        </fieldset>
        {planCurrent && !mismatch && currentReview?.phase === "failed" && <div className="message error" role="alert">
          <strong>Saved code could not be read.</strong><p>{currentReview.message}</p>
          <button type="button" className="secondary-button" onClick={retryReview}>Retry loading saved code</button>
        </div>}
        {planCurrent && !mismatch && currentReview?.phase === "changed" && <div className="message warning" role="alert">
          <strong>This record changed elsewhere.</strong><p>Reload the saved plan before saving.</p>
          <button type="button" className="secondary-button" onClick={onReload}>Reload current record</button>
        </div>}
        {status?.review && <div className="review-summary"><strong>Time: {conclusion(status, "time_complexity") ?? "Not determined"} · Space: {conclusion(status, "space_complexity") ?? "Not determined"}</strong>
          {conclusion(status, "reasoning") && <p>{conclusion(status, "reasoning")}</p>}</div>}
        <p className="form-note">Your Skill session reviews saved code. AC remains self-reported.</p>
      </section>
      <section className="record-pane" aria-labelledby={`feedback-${item.attempt_id}`}>
        <div className="pane-heading"><h3 id={`feedback-${item.attempt_id}`}>Practice feedback</h3>
          {feedback && <button type="button" className="text-button correction-button" onClick={toggleCorrection} disabled={!editable}>{mode === "correction" ? "Cancel correction" : "Correct saved record"}</button>}</div>
        {feedback && <p className="saved-summary">Last saved: {feedback.result ? `${feedback.result} · ${RESULT_LABELS[feedback.result]}` : "no result"}{feedback.elapsed_minutes != null ? ` · ${feedback.elapsed_minutes} min` : ""}</p>}
        {mode === "correction" && <p className="message warning compact">Correction mode. Earlier answers stay in your history.</p>}
        <fieldset className="entry-fields" disabled={!editable}>
          <ResultPicker value={draft.result} onChange={handleResultChange} onClear={mode === "correction" ? clearResult : null} />
          {(draft.result === "E" || draft.defer_until !== "" || touched.has("defer_until")) && <label className="field schedule-field"><span>Defer until <small>optional</small></span><input type="date" name="defer_until" value={draft.defer_until} onChange={handleFieldChange} /></label>}
          {(draft.result === "F" || draft.skip_until !== "" || touched.has("skip_until")) && <label className="field schedule-field"><span>Eligible again <small>optional</small></span><input type="date" name="skip_until" value={draft.skip_until} onChange={handleFieldChange} /></label>}
          <label className="field time-field"><span>Total time <small>minutes, including earlier sessions</small></span>
            <input type="number" min="0" step="any" inputMode="decimal" name="elapsed_minutes" value={draft.elapsed_minutes} onChange={handleFieldChange} placeholder="Optional" /></label>
          <details className="optional-details" open={detailsOpen}><summary>More details <span>{detailCount ? `${detailCount} recorded` : "optional"}</span></summary>
            <div className="optional-grid">
              <ComplexitySelect name="time_complexity" label="Time complexity" value={draft.time_complexity} onChange={handleFieldChange} />
              <ComplexitySelect name="space_complexity" label="Space complexity" value={draft.space_complexity} onChange={handleFieldChange} />
              <label className="field full-width"><span>Where did you get stuck?</span><textarea name="blocked_on" value={draft.blocked_on} onChange={handleFieldChange} rows={2} maxLength={4000} placeholder="A brief note, if useful" /></label>
              <label className="field"><span>Explain the solution aloud</span><select name="explanation" value={draft.explanation} onChange={handleFieldChange}>
                <option value="">Not recorded</option><option value="not_tried">Not tried</option><option value="partial">Partly explained</option><option value="clear">Clearly explained</option><option value="uncertain">Uncertain</option></select></label>
              <label className="field"><span>Boundary tests checked?</span><select name="boundary_tests" value={draft.boundary_tests} onChange={handleFieldChange}>
                <option value="">Not recorded</option><option value="true">Yes</option><option value="false">No</option></select></label>
              <label className="field"><span>Familiarity</span><select name="proficiency" value={draft.proficiency} onChange={handleFieldChange}>
                <option value="">Not recorded</option><option value="1">1 · New to me</option><option value="2">2 · Needs support</option><option value="3">3 · Getting familiar</option><option value="4">4 · Comfortable</option><option value="5">5 · Very familiar</option></select></label>
            </div>
          </details>
        </fieldset>
        {(save.phase === "failed" || save.phase === "uncertain" || mismatch) && <div className={`message ${save.phase === "failed" && save.conflict ? "warning" : "error"}`} role="alert">
          <strong>{mismatch ? "This is a different training workspace." : save.phase === "failed" && save.conflict ? "This record changed elsewhere." : "Your input is still here."}</strong>
          <p>{mismatch ? "This service now uses another training database. Start a new session in your Skill and use its feedback link." : save.phase === "uncertain" ? `${save.message} Keep this page open. Retry checks the same submission before sending it again.` : save.phase === "failed" ? save.message : ""}</p>
          {save.phase === "failed" && save.conflict && <button type="button" className="secondary-button" onClick={reloadRecord}>Reload current record</button>}
        </div>}
        <div className="form-footer">
          {save.phase === "uncertain" && !mismatch
            ? <button type="button" className="primary-button" onClick={retry}>Retry save</button>
            : <button type="submit" className="primary-button" disabled={!canSave}>{label}</button>}
          <div className="footer-meta"><span className="save-state" aria-live="polite">{stateText}</span><span className="shortcut-hint"><kbd>Ctrl</kbd>/<kbd>⌘</kbd> + <kbd>Enter</kbd></span></div>
          <p className="form-note">Results and complexity entries are self-reported.</p>
        </div>
      </section>
    </form>
  );
}
