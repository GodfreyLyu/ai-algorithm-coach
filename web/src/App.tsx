/** File purpose: Bind the session link to a store and connect plan, editor, and score views. */
import { useEffect, useRef, useState } from "react";
import { errorMessage, request } from "./api";
import { ProblemCard } from "./components/ProblemCard";
import { PlanSidebar } from "./components/PlanSidebar";
import { ScoresView } from "./components/ScoresView";
import type { SaveSummary } from "./components/AttemptEditor";
import { isTrainingDate, shiftDate } from "./dates";
import { createDraftStore } from "./drafts";
import { useStoreResource } from "./hooks";
import type { Context, Plan, PlanItem, Progress, Scores } from "./types";

interface SessionLink {
  date: string | null;
  storeId: string | null;
  error: string | null;
}

interface Notice {
  tone: "success" | "warning";
  text: string;
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
 * Inputs: A plan and the attempt that was just saved.
 * Outputs: The next item without a result, or null.
 * Logic: Search forward from the saved item and wrap around once.
 * Dependencies: The saved plan order.
 */
function nextOpenItem(plan: Plan, savedId: string): PlanItem | null {
  const start = plan.items.findIndex(matchesId);
  /**
   * Inputs: One plan item.
   * Outputs: Whether it is the saved attempt.
   * Logic: Compare stable attempt IDs.
   * Dependencies: savedId.
   */
  function matchesId(item: PlanItem) { return item.attempt_id === savedId; }
  for (let step = 1; step < plan.items.length; step += 1) {
    const item = plan.items[(start + step) % plan.items.length];
    if (!item.attempt.feedback?.result) return item;
  }
  return null;
}

/**
 * Inputs: None.
 * Outputs: The local application's plan and topic-score views.
 * Logic: Validate the session link, bind its store and date, and refresh after saves.
 *   Scores load only when their view is open.
 * Dependencies: React, PlanSidebar, ProblemCard, ScoresView, and useStoreResource.
 */
export function App() {
  const drafts = useRef(createDraftStore());
  const [sessionLink] = useState<SessionLink>(readSessionLink);
  const [context, setContext] = useState<Context | null>(null);
  const [startupError, setStartupError] = useState<{ title: string; message: string } | null>(
    sessionLink.error ? { title: "This training link is invalid", message: sessionLink.error } : null,
  );
  const [workspaceLost, setWorkspaceLost] = useState(false);
  const [tab, setTab] = useState<"plan" | "scores">("plan");
  const [trainingDate, setTrainingDate] = useState("");
  const [activeAttempt, setActiveAttempt] = useState<string | null>(null);
  const [blockingAttempt, setBlockingAttempt] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [autoAdvance, setAutoAdvance] = useState(true);
  const [advanceFrom, setAdvanceFrom] = useState<{ id: string; title: string; token: number } | null>(null);
  const locked = blockingAttempt !== null || workspaceLost;
  const storeId = context?.store_id ?? null;

  /**
   * Inputs: None.
   * Outputs: A locked page that keeps drafts and refuses the new store.
   * Logic: Require a fresh Skill session link.
   * Dependencies: Shared navigation state.
   */
  function handleWorkspaceMismatch() { setWorkspaceLost(true); setNotice(null); }

  const plan = useStoreResource<Plan>({
    path: trainingDate ? `/v1/plans/${encodeURIComponent(trainingDate)}` : null, storeId,
    enabled: tab === "plan" && !workspaceLost, refreshToken, onMismatch: handleWorkspaceMismatch,
  });
  const scores = useStoreResource<Scores>({
    path: context ? `/v1/scores?language=${encodeURIComponent(context.language)}` : null, storeId,
    enabled: tab === "scores" && !workspaceLost, refreshToken, onMismatch: handleWorkspaceMismatch,
  });
  const progress = useStoreResource<Progress>({
    path: context ? `/v1/progress?language=${encodeURIComponent(context.language)}` : null, storeId,
    enabled: tab === "scores" && !workspaceLost, refreshToken, onMismatch: handleWorkspaceMismatch,
  });

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
   * Inputs: A refreshed plan after a save.
   * Outputs: The next open problem selected when auto-advance is on.
   * Logic: Wait for the refresh that follows the save before moving.
   * Dependencies: nextOpenItem and the plan resource.
   */
  function advanceEffect() {
    if (!advanceFrom || plan.loading || !plan.data || advanceFrom.token !== refreshToken) return;
    const next = nextOpenItem(plan.data, advanceFrom.id);
    if (next) {
      setActiveAttempt(next.attempt_id);
      setNotice({ tone: "success", text: `Saved ${advanceFrom.title} · Now on ${next.problem.title}` });
    }
    setAdvanceFrom(null);
  }
  useEffect(advanceEffect, [advanceFrom, plan.loading, plan.data, refreshToken]);

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
   * Inputs: A selected calendar date or an empty value.
   * Outputs: A different existing plan request.
   * Logic: Accept a real calendar date without using the browser clock.
   * Dependencies: isTrainingDate and the pending lock.
   */
  function changeDate(selected: string) {
    if (locked || (selected !== "" && !isTrainingDate(selected))) return;
    setTrainingDate(selected); setActiveAttempt(null); setNotice(null); setAdvanceFrom(null);
  }

  /**
   * Inputs: A number of days.
   * Outputs: The shifted training date.
   * Logic: Shift the calendar date, not a browser-local time.
   * Dependencies: shiftDate and changeDate.
   */
  function shiftTrainingDate(days: number) { if (trainingDate) changeDate(shiftDate(trainingDate, days)); }

  /**
   * Inputs: A Today click.
   * Outputs: The workspace's current training date.
   * Logic: Use the server's configured timezone date.
   * Dependencies: The loaded context.
   */
  function goToday() { if (context) changeDate(context.training_date); }

  /**
   * Inputs: A clicked practice attempt ID.
   * Outputs: The selected editor in the detail area.
   * Logic: Keep one editor visible and preserve drafts for other attempts.
   * Dependencies: The pending lock and retained drafts.
   */
  function selectAttempt(id: string) { if (!locked) { setActiveAttempt(id); setNotice(null); } }

  /**
   * Inputs: The attempt with an uncertain operation, or null after resolution.
   * Outputs: The shared navigation lock.
   * Logic: Prevent a pending request from being unmounted or replaced.
   * Dependencies: AttemptEditor save callbacks.
   */
  function handlePendingChange(id: string | null) { setBlockingAttempt(id); }

  /**
   * Inputs: A verified save summary.
   * Outputs: A notice, fresh data, and an optional move to the next problem.
   * Logic: Acknowledge what was committed first, then read updated authority data.
   * Dependencies: Refresh state and the auto-advance setting.
   */
  function handleSaved(summary: SaveSummary) {
    const token = refreshToken + 1;
    const parts = [summary.feedbackSaved ? "feedback" : "", summary.codeSaved ? "code" : ""].filter(Boolean).join(" and ");
    if (summary.codeError) setNotice({ tone: "warning", text: `Feedback saved. Code was not saved: ${summary.codeError} Review the code in the editor before saving again.` });
    else setNotice({ tone: "success", text: `Saved ${parts} for ${summary.title}` });
    if (autoAdvance && summary.feedbackSaved && summary.result && !summary.codeError) setAdvanceFrom({ id: summary.attemptId, title: summary.title, token });
    setRefreshToken(token);
  }

  /**
   * Inputs: A deliberate reload after a version conflict or read failure.
   * Outputs: Fresh authority data without an automatic conflict retry.
   * Logic: Discard stale editing context only after the user requests reload.
   * Dependencies: The shared pending lock and refresh token.
   */
  function reloadRecords() {
    if (locked) return;
    setNotice(null);
    setRefreshToken(nextToken);
  }

  /**
   * Inputs: The previous refresh token.
   * Outputs: The next token.
   * Logic: Use a functional update so rapid clicks are not lost.
   * Dependencies: None.
   */
  function nextToken(previous: number) { return previous + 1; }

  const planData = plan.data;
  let selectedItem = planData?.items[0] ?? null;
  if (planData && activeAttempt) for (const item of planData.items) {
    if (item.attempt_id === activeAttempt) { selectedItem = item; break; }
  }
  const planMissing = Boolean(trainingDate) && plan.missing && !plan.loading;

  return (
    <div className="app-shell">
      <header className="app-header"><div className="brand">Algorithm Coach</div>
        <div className="header-detail"><span className="local-dot" />Local workspace{context && <><span className="header-divider">/</span><span>{context.language}</span><span className="header-divider">/</span><span>{context.timezone}</span></>}</div>
      </header>
      <div className="navigation-row"><nav className="view-tabs" aria-label="Views"><button type="button" aria-current={tab === "plan" ? "page" : undefined} className={tab === "plan" ? "selected" : ""} onClick={showPlan} disabled={locked}>Training record</button><button type="button" aria-current={tab === "scores" ? "page" : undefined} className={tab === "scores" ? "selected" : ""} onClick={showScores} disabled={locked}>Topic scores</button></nav></div>
      <main className="app-main">
        {startupError && <div className="empty-state startup-error" role="alert"><span className="empty-icon" aria-hidden="true">!</span><h1>{startupError.title}</h1><p>{startupError.message}</p></div>}
        {!context && !startupError && <div className="loading-panel" role="status">Opening your practice record…</div>}
        {workspaceLost && <div className="message error" role="alert"><strong>This is a different training workspace.</strong><p>Your draft remains here. Start a new session in your Skill and use its feedback link. This page will not switch databases.</p></div>}
        {context && tab === "scores" && <div className="scores-view"><ScoresView scores={scores} progress={progress} today={context.training_date} /></div>}
        {context && tab === "plan" && <>
          <h1 className="sr-only">Training record</h1>
          <div className="plan-layout">
            <PlanSidebar trainingDate={trainingDate} today={context.training_date} plan={planData} selectedId={selectedItem?.attempt_id ?? null}
              locked={locked} loading={plan.loading} autoAdvance={autoAdvance} onDateChange={changeDate} onShiftDate={shiftTrainingDate}
              onToday={goToday} onSelect={selectAttempt} onRefresh={reloadRecords} onAutoAdvanceChange={setAutoAdvance} />
            <div className="plan-detail">
              {notice && <div className={`message ${notice.tone}`} role="status">{notice.tone === "success" && <span className="success-check" aria-hidden="true">✓</span>}{notice.text}</div>}
              {plan.error && <div className="message error" role="alert"><strong>The plan could not be read.</strong><p>{plan.error}</p></div>}
              {plan.loading && <div className="loading-panel compact" role="status">{planData ? "Refreshing the saved plan…" : "Reading the saved plan…"}</div>}
              {!trainingDate && !plan.loading && <div className="empty-state"><h2>Choose a training date</h2><p>Select a date to read its existing plan.</p></div>}
              {planMissing && <div className="empty-state"><h2>No saved plan for this date</h2><p>Ask your Algorithm Coach Skill to generate a plan.<br />Then refresh here to record your practice.</p></div>}
              {planData && <>
                {Boolean(planData.current_policy_conflicts?.length) && <div className="message warning"><strong>This saved plan has a scope conflict.</strong><p>Review it in your Skill. Its published items have been preserved.</p></div>}
                {!selectedItem && !plan.loading && <div className="empty-state"><h2>No problems in this saved plan</h2><p>Review the plan in your Algorithm Coach Skill.</p></div>}
                {selectedItem && <ProblemCard key={selectedItem.attempt_id} item={selectedItem} storeId={context.store_id} drafts={drafts.current}
                  planCurrent={plan.dataToken === refreshToken && planData.training_date === trainingDate} workspaceLocked={workspaceLost}
                  onSaved={handleSaved} onPendingChange={handlePendingChange} onReload={reloadRecords} onWorkspaceMismatch={handleWorkspaceMismatch} />}
              </>}
            </div>
          </div>
        </>}
      </main>
      <footer className="app-footer"><span>Drafts stay in this page until you reload or close it</span><span>Local records · Self-reported evidence</span></footer>
    </div>
  );
}
