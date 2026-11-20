/** File purpose: Read existing plans and connect record forms with topic scores. */
import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { ApiError, errorMessage, request } from "./api";
import { FeedbackForm, type EditorDraft } from "./FeedbackForm";
import { ScoresView } from "./ScoresView";
import type { Context, Plan, PlanItem, Receipt, Scores } from "./types";

const RESULT_LABELS = { A: "Independent AC", B: "AC with hints", C: "AC after answer", D: "Not yet AC", E: "Deferred", F: "Skipped" };

interface SessionLink {
  date: string | null;
  storeId: string | null;
  error: string | null;
}

/**
 * Inputs: A candidate calendar date from a session link or date input.
 * Outputs: Whether the date is a real YYYY-MM-DD day supported by the core.
 * Logic: Reject malformed dates, year zero, and normalized invalid days.
 * Dependencies: The browser's ISO date parser.
 */
function isTrainingDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000-")) return false;
  const parsed = new Date(`${value}T12:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

/**
 * Inputs: None. Read the initial browser URL once.
 * Outputs: The optional bound date and store, or an explicit link error.
 * Logic: Reject duplicate, empty, or invalid values instead of changing their meaning.
 * Dependencies: URLSearchParams, the location, and isTrainingDate.
 */
function readSessionLink(): SessionLink {
  const parameters = new URLSearchParams(window.location.search);
  const date = parameters.get("date");
  const storeId = parameters.get("store");
  let error: string | null = null;
  if (parameters.getAll("date").length > 1 || parameters.getAll("store").length > 1) {
    error = "This link repeats its date or workspace. Start a new session in your Skill.";
  } else if (date !== null && !isTrainingDate(date)) {
    error = "This link has an invalid training date. Start a new session in your Skill.";
  } else if (storeId !== null && !/^[a-f0-9]{64}$/.test(storeId)) {
    error = "This link has an invalid workspace. Start a new session in your Skill.";
  }
  return { date, storeId, error };
}

/**
 * Inputs: A saved ISO training date.
 * Outputs: A locale-friendly day label without shifting its timezone.
 * Logic: Format the supplied date as calendar text, not a browser-local instant.
 * Dependencies: The standard date formatter.
 */
function displayDate(value: string): string {
  return new Intl.DateTimeFormat("en", { weekday: "long", month: "long", day: "numeric", year: "numeric", timeZone: "UTC" }).format(new Date(`${value}T12:00:00Z`));
}

/**
 * Inputs: None.
 * Outputs: The result reference for the plan sidebar.
 * Logic: Explain the six self-reported outcomes in one disclosure.
 * Dependencies: The core feedback meanings.
 */
function ResultGuide() {
  return <div className="guide-content"><p>Choose a result after each problem. Time and details are optional.</p>
    <dl className="result-guide"><div><dt>A</dt><dd>Independent AC</dd></div><div><dt>B</dt><dd>AC with a hint</dd></div><div><dt>C</dt><dd>AC after the answer</dd></div><div><dt>D</dt><dd>Not yet AC</dd></div><div><dt>E</dt><dd>Defer until later</dd></div><div><dt>F</dt><dd>Skip this attempt</dd></div></dl>
    <p className="guide-footnote">AC results are self-reported. Stable mastery needs spaced practice. E and F do not mean complete.</p></div>;
}

/**
 * Inputs: A saved plan item, its selection state, and the shared navigation lock.
 * Outputs: One sidebar button for a stable practice attempt.
 * Logic: Select the named attempt without closing the current editor.
 * Dependencies: The saved plan and the parent's selection callback.
 */
function PlanButton({ item, selected, locked, onSelect }: {
  item: PlanItem; selected: boolean; locked: boolean; onSelect: (id: string) => void;
}) {
  /**
   * Inputs: A click on this saved problem.
   * Outputs: This attempt's stable ID to the parent.
   * Logic: Preserve the pending-operation lock when changing problems.
   * Dependencies: The shared lock and onSelect callback.
   */
  function selectAttempt() { if (!locked) onSelect(item.attempt_id); }

  return <button type="button" className={`plan-item ${selected ? "selected" : ""}`} data-plan-attempt-id={item.attempt_id}
    aria-label={`Open ${item.problem.title}`} aria-current={selected ? "true" : undefined} disabled={locked} onClick={selectAttempt}>
    <span className="plan-item-number">{item.position}</span><span className="plan-item-title">{item.problem.title}</span>
  </button>;
}

/**
 * Inputs: A selected plan item, bound store ID, retained drafts, and shared callbacks.
 * Outputs: The selected problem and its always-visible editor.
 * Logic: Show current evidence before editing a specific stable attempt.
 * Dependencies: FeedbackForm and the saved plan contract.
 */
function ProblemCard({ item, storeId, drafts, workspaceLocked, onSaved, onPendingChange, onReload, onWorkspaceMismatch }: {
  item: PlanItem; storeId: string; drafts: Map<string, EditorDraft>; workspaceLocked: boolean;
  onSaved: (receipt: Receipt) => void; onPendingChange: (id: string | null) => void; onReload: () => void;
  onWorkspaceMismatch: () => void;
}) {
  const feedback = item.attempt.feedback;
  const result = feedback?.result;

  /**
   * Inputs: A tag from this problem's metadata.
   * Outputs: A compact metadata label.
   * Logic: Render source tags without interpreting them as mastery.
   * Dependencies: The saved problem metadata.
   */
  function renderTag(tag: string) { return <span key={tag} className="tag">{tag.replaceAll("-", " ")}</span>; }

  return (
    <article className="problem-card" data-attempt-id={item.attempt_id} aria-labelledby={`problem-${item.attempt_id}`}>
      <div className="problem-header">
        <div className="problem-content"><h2 id={`problem-${item.attempt_id}`}><span className="problem-id">{item.problem.id.replace("leetcode:", "#")}</span>{" "}<a href={item.problem.url} target="_blank" rel="noreferrer">{item.problem.title}<span aria-hidden="true"> ↗</span></a></h2>
          <div className="problem-meta"><span className={`difficulty ${item.problem.difficulty}`}>{item.problem.difficulty}</span><span className="problem-tags">{item.problem.tags.map(renderTag)}</span><span className="attempt-language">{item.attempt.language}</span><span className="reason-label">{item.reason.replaceAll("_", " ")}</span></div>
        </div>
        <div className="problem-summary"><div className="problem-status"><span className={`status-dot ${result ? `result-${result}` : ""}`} aria-hidden="true" />
          <span>{result ? `${result} · ${RESULT_LABELS[result]}` : "No result recorded"}</span></div>
          {feedback?.elapsed_minutes != null && <div className="problem-time">{feedback.elapsed_minutes} <span className="time-unit">min</span></div>}
        </div>
      </div>
      <FeedbackForm key={`${storeId}:${item.attempt_id}:${item.attempt.revision}`} item={item} storeId={storeId} drafts={drafts} workspaceLocked={workspaceLocked} onSaved={onSaved} onPendingChange={onPendingChange} onReload={onReload} onWorkspaceMismatch={onWorkspaceMismatch} />
    </article>
  );
}

/**
 * Inputs: None.
 * Outputs: The local application's plan and topic-score views.
 * Logic: Validate the session link, bind its store and date, and refresh after receipts.
 * Dependencies: React, browser fetch, FeedbackForm, and ScoresView.
 */
export function App() {
  const drafts = useRef(new Map<string, EditorDraft>());
  const [sessionLink] = useState<SessionLink>(readSessionLink);
  const [context, setContext] = useState<Context | null>(null);
  const [startupError, setStartupError] = useState<{ title: string; message: string } | null>(
    sessionLink.error ? { title: "This training link is invalid", message: sessionLink.error } : null,
  );
  const [workspaceLost, setWorkspaceLost] = useState(false);
  const [tab, setTab] = useState<"plan" | "scores">("plan");
  const [trainingDate, setTrainingDate] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [scores, setScores] = useState<Scores | null>(null);
  const [planLoading, setPlanLoading] = useState(true);
  const [scoresLoading, setScoresLoading] = useState(true);
  const [planError, setPlanError] = useState<string | null>(null);
  const [scoresError, setScoresError] = useState<string | null>(null);
  const [activeAttempt, setActiveAttempt] = useState<string | null>(null);
  const [blockingAttempt, setBlockingAttempt] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const locked = blockingAttempt !== null || workspaceLost;

  /**
   * Inputs: The initial component mount.
   * Outputs: Context from the authority, or a visible startup error.
   * Logic: Verify the linked store, prefer its date, and cancel obsolete reads.
   * Dependencies: The context endpoint and AbortController.
   */
  function loadContextEffect() {
    if (sessionLink.error) return;
    const controller = new AbortController();
    /**
     * Inputs: None.
     * Outputs: Saved workspace context in component state.
     * Logic: Avoid browser-date assumptions and ignore cancelled requests.
     * Dependencies: request and the effect's abort signal.
     */
    async function loadContext() {
      try {
        const saved = await request<Context>("/v1/context", { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (typeof saved.store_id !== "string" || !/^[a-f0-9]{64}$/.test(saved.store_id)) {
          setStartupError({ title: "The local service needs an update", message: "This service cannot identify its training database. Restart it through your Skill." });
          return;
        }
        if (sessionLink.storeId !== null && sessionLink.storeId !== saved.store_id) {
          setStartupError({ title: "This is a different training workspace", message: "This link points to another database. Start a new session in your Skill and use its feedback link." });
          return;
        }
        if (!isTrainingDate(saved.training_date)) {
          setStartupError({ title: "The local service returned an invalid date", message: "Check the service through your Skill before recording feedback." });
          return;
        }
        setContext(saved); setTrainingDate(sessionLink.date ?? saved.training_date);
      } catch (failure) {
        if (!controller.signal.aborted) setStartupError({ title: "The local service is unavailable", message: errorMessage(failure) });
      }
    }
    /**
     * Inputs: Component cleanup.
     * Outputs: Cancelled outstanding context request.
     * Logic: Prevent late state updates from an obsolete mount.
     * Dependencies: AbortController.
     */
    function cancelContext() { controller.abort(); }
    void loadContext();
    return cancelContext;
  }
  useEffect(loadContextEffect, [sessionLink]);

  /**
   * Inputs: The server context, selected date, and explicit refresh token.
   * Outputs: Fresh plan and score data or independent visible errors.
   * Logic: Retain drafts during refresh, read existing plans, and cancel obsolete reads.
   * Dependencies: The plan and scores endpoints.
   */
  function loadViewsEffect() {
    if (!context || workspaceLost) return;
    if (!trainingDate) {
      setPlanLoading(false); setScoresLoading(false); setPlanError(null);
      return;
    }
    const controller = new AbortController();
    setPlanLoading(true); setScoresLoading(true); setPlanError(null); setScoresError(null);
    /**
     * Inputs: None.
     * Outputs: The selected existing plan, or an empty-plan state.
     * Logic: Treat a missing plan as missing without generating one.
     * Dependencies: request and the selected training date.
     */
    async function loadPlan() {
      try {
        const saved = await request<Plan>(`/v1/plans/${encodeURIComponent(trainingDate)}`, { signal: controller.signal, headers: { "X-Coach-Store-Id": context!.store_id } });
        if (!controller.signal.aborted) setPlan(saved);
      } catch (failure) {
        if (!controller.signal.aborted) {
          if (failure instanceof ApiError && failure.code === "workspace_mismatch") handleWorkspaceMismatch();
          else if (failure instanceof ApiError && failure.status === 404) setPlan(null);
          else setPlanError(errorMessage(failure));
        }
      } finally {
        if (!controller.signal.aborted) setPlanLoading(false);
      }
    }
    /**
     * Inputs: None.
     * Outputs: Current topic evidence for the configured language.
     * Logic: Refresh scores independently from missing or failed plan reads.
     * Dependencies: request and the saved language.
     */
    async function loadScores() {
      try {
        const saved = await request<Scores>(`/v1/scores?language=${encodeURIComponent(context!.language)}`, { signal: controller.signal, headers: { "X-Coach-Store-Id": context!.store_id } });
        if (!controller.signal.aborted) setScores(saved);
      } catch (failure) {
        if (!controller.signal.aborted) {
          if (failure instanceof ApiError && failure.code === "workspace_mismatch") handleWorkspaceMismatch();
          else setScoresError(errorMessage(failure));
        }
      } finally {
        if (!controller.signal.aborted) setScoresLoading(false);
      }
    }
    /**
     * Inputs: An effect cleanup after a date or refresh change.
     * Outputs: Cancellation of both old reads.
     * Logic: Keep slower prior responses from replacing newer data.
     * Dependencies: AbortController.
     */
    function cancelViews() { controller.abort(); }
    void loadPlan(); void loadScores();
    return cancelViews;
  }
  useEffect(loadViewsEffect, [context, trainingDate, refreshToken, workspaceLost]);

  /**
   * Inputs: A plan-tab click.
   * Outputs: The plan and records view.
   * Logic: Keep an uncertain save mounted before allowing navigation.
   * Dependencies: The shared pending lock.
   */
  function showPlan() { if (!locked) setTab("plan"); }

  /**
   * Inputs: A scores-tab click.
   * Outputs: The topic scores view.
   * Logic: Keep an uncertain save mounted before allowing navigation.
   * Dependencies: The shared pending lock.
   */
  function showScores() { if (!locked) setTab("scores"); }

  /**
   * Inputs: An explicit calendar date selection.
   * Outputs: A different existing plan request.
   * Logic: Accept a real calendar date without using the browser clock.
   * Dependencies: The date input and pending lock.
   */
  function changeDate(event: ChangeEvent<HTMLInputElement>) {
    if (locked) return;
    const selected = event.currentTarget.value;
    if (selected !== "" && !isTrainingDate(selected)) return;
    setTrainingDate(selected); setPlan(null); setActiveAttempt(null); setNotice(null);
  }

  /**
   * Inputs: A clicked practice attempt ID.
   * Outputs: The selected editor in the detail area.
   * Logic: Keep one editor visible and preserve drafts for other attempts.
   * Dependencies: The pending lock and retained drafts.
   */
  function selectAttempt(id: string) { if (!locked) setActiveAttempt(id); }

  /**
   * Inputs: The attempt with an uncertain operation, or null after resolution.
   * Outputs: The shared navigation lock.
   * Logic: Prevent a pending request from being unmounted or replaced.
   * Dependencies: FeedbackForm save callbacks.
   */
  function handlePendingChange(id: string | null) { setBlockingAttempt(id); }

  /**
   * Inputs: A rejected request bound to the original training store.
   * Outputs: A workspace warning and locked navigation without adopting new data.
   * Logic: Keep the current draft visible and require a fresh Skill session link.
   * Dependencies: Store-bound API errors and shared navigation state.
   */
  function handleWorkspaceMismatch() { setWorkspaceLost(true); setNotice(null); }

  /**
   * Inputs: A verified committed feedback receipt.
   * Outputs: A saved notification and fresh plan and score requests.
   * Logic: Acknowledge persistence first, then read updated authority data.
   * Dependencies: The receipt and view-refresh state.
   */
  function handleSaved(receipt: Receipt) {
    setNotice(`Saved to your record · revision ${receipt.revision}`);
    setRefreshToken(refreshToken + 1);
  }

  /**
   * Inputs: A deliberate reload after a version conflict or read failure.
   * Outputs: Fresh authority data without an automatic conflict retry.
   * Logic: Discard stale editing context only after the user requests reload.
   * Dependencies: The shared pending lock and refresh token.
   */
  function reloadRecords() { if (!locked) { setNotice(null); setRefreshToken(refreshToken + 1); } }

  /**
   * Inputs: One published plan item.
   * Outputs: A keyed button in the daily problem navigation.
   * Logic: Compare the derived selection with the stable attempt identity.
   * Dependencies: PlanButton and the selected plan item.
   */
  function renderPlanButton(item: PlanItem) {
    return <PlanButton key={item.attempt_id} item={item} selected={selectedItem?.attempt_id === item.attempt_id} locked={locked} onSelect={selectAttempt} />;
  }

  let recordedCount = 0;
  if (plan) for (const item of plan.items) if (item.attempt.feedback?.result) recordedCount += 1;
  let selectedItem = plan?.items[0] ?? null;
  if (plan && activeAttempt) for (const item of plan.items) {
    if (item.attempt_id === activeAttempt) { selectedItem = item; break; }
  }

  return (
    <div className="app-shell">
      <header className="app-header"><div className="brand">Algorithm Coach</div>
        <div className="header-detail"><span className="local-dot" />Local workspace{context && <><span className="header-divider">/</span><span>{context.language}</span></>}</div>
      </header>
      <div className="navigation-row"><nav className="view-tabs" aria-label="Views"><button type="button" aria-current={tab === "plan" ? "page" : undefined} className={tab === "plan" ? "selected" : ""} onClick={showPlan} disabled={locked}>Training record</button><button type="button" aria-current={tab === "scores" ? "page" : undefined} className={tab === "scores" ? "selected" : ""} onClick={showScores} disabled={locked}>Topic scores</button></nav>
        {context && <span className="timezone-label">{context.timezone}</span>}
      </div>
      <main className="app-main">
        {startupError && <div className="empty-state startup-error" role="alert"><span className="empty-icon" aria-hidden="true">!</span><h1>{startupError.title}</h1><p>{startupError.message}</p></div>}
        {!context && !startupError && <div className="loading-panel" role="status">Opening your practice record…</div>}
        {workspaceLost && <div className="message error" role="alert"><strong>This is a different training workspace.</strong><p>Your draft remains here. Start a new session in your Skill and use its feedback link. This page will not switch databases.</p></div>}
        {context && tab === "scores" && <div className="scores-view"><ScoresView scores={scores} loading={scoresLoading} error={scoresError} /></div>}
        {context && tab === "plan" && <>
          <h1 className="sr-only">Training record</h1>
          <div className="plan-layout"><aside className="plan-sidebar" aria-label="Daily training plan">
              <label className="date-control"><span>Training date</span><input aria-label="Training date" type="date" min="0001-01-01" max="9999-12-31" value={trainingDate} onChange={changeDate} disabled={locked} /></label>
              <p className="sidebar-date">{trainingDate ? displayDate(trainingDate) : "Choose a training date"}</p>
              <div className="sidebar-heading"><h2>Saved plan</h2><p>{plan ? `${plan.items.length} problems · ${recordedCount} with a result` : "Your saved daily plan"}</p></div>
              {plan && plan.items.length > 0 && <nav className="problem-navigation" aria-label="Saved plan problems">{plan.items.map(renderPlanButton)}</nav>}
              <div className="sidebar-tools"><button type="button" className="text-button" onClick={reloadRecords} disabled={locked || planLoading || !trainingDate}>Refresh</button>
              <details className="result-help"><summary>Result guide <span>A–F</span></summary><ResultGuide /></details>
              </div>
            </aside><div className="plan-detail">
            {notice && <div className="message success" role="status"><span className="success-check" aria-hidden="true">✓</span>{notice}</div>}
            {planError && <div className="message error" role="alert"><strong>The plan could not be read.</strong><p>{planError}</p></div>}
            {planLoading && <div className="loading-panel" role="status">{plan ? "Refreshing the saved plan…" : "Reading the saved plan…"}</div>}
            {!trainingDate && !planLoading && <div className="empty-state"><h2>Choose a training date</h2><p>Select a date to read its existing plan.</p></div>}
            {trainingDate && !planLoading && !plan && !planError && <div className="empty-state"><h2>No saved plan for this date</h2><p>Ask your Algorithm Coach Skill to generate a plan.<br />Then refresh here to record your practice.</p></div>}
            {plan && <>
              {Boolean(plan.current_policy_conflicts?.length) && <div className="message warning"><strong>This saved plan has a scope conflict.</strong><p>Review it in your Skill. Its published items have been preserved.</p></div>}
              {!selectedItem && !planLoading && <div className="empty-state"><h2>No problems in this saved plan</h2><p>Review the plan in your Algorithm Coach Skill.</p></div>}
              {selectedItem && <ProblemCard key={selectedItem.attempt_id} item={selectedItem} storeId={context.store_id} drafts={drafts.current} workspaceLocked={workspaceLost}
                onSaved={handleSaved} onPendingChange={handlePendingChange} onReload={reloadRecords} onWorkspaceMismatch={handleWorkspaceMismatch} />}
            </>}
          </div></div>
        </>}
      </main>
      <footer className="app-footer"><span>Drafts stay in this page until you reload or close it</span><span>Local records · Self-reported evidence</span></footer>
    </div>
  );
}
