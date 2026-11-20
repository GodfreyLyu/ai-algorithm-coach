/** File purpose: Show the date controls, plan progress, and per-problem status rail. */
import type { ChangeEvent } from "react";
import { RESULT_LABELS, RESULTS, type ResultOption } from "../constants";
import { displayDate } from "../dates";
import type { Plan, PlanItem } from "../types";

interface SidebarProps {
  trainingDate: string;
  today: string;
  plan: Plan | null;
  selectedId: string | null;
  locked: boolean;
  loading: boolean;
  autoAdvance: boolean;
  onDateChange: (value: string) => void;
  onShiftDate: (days: number) => void;
  onToday: () => void;
  onSelect: (attemptId: string) => void;
  onRefresh: () => void;
  onAutoAdvanceChange: (value: boolean) => void;
}

/**
 * Inputs: A saved plan item, its selection state, and the shared navigation lock.
 * Outputs: One rail button with a result badge for a stable practice attempt.
 * Logic: Show the current result so progress is visible without opening each problem.
 * Dependencies: The saved plan and the parent's selection callback.
 */
function PlanButton({ item, selected, locked, onSelect }: {
  item: PlanItem; selected: boolean; locked: boolean; onSelect: (id: string) => void;
}) {
  const result = item.attempt.feedback?.result ?? null;
  /**
   * Inputs: A click on this saved problem.
   * Outputs: This attempt's stable ID to the parent.
   * Logic: Preserve the pending-operation lock when changing problems.
   * Dependencies: The shared lock and onSelect callback.
   */
  function selectAttempt() { if (!locked) onSelect(item.attempt_id); }

  return <button type="button" className={`plan-item ${selected ? "selected" : ""}`} data-plan-attempt-id={item.attempt_id}
    aria-label={`Open ${item.problem.title}, ${result ? `result ${result} ${RESULT_LABELS[result]}` : "no result"}`}
    aria-current={selected ? "true" : undefined} disabled={locked} onClick={selectAttempt}>
    <span className={`plan-item-status ${result ? `result-${result}` : "empty"}`} aria-hidden="true">{result ?? item.position}</span>
    <span className="plan-item-title">{item.problem.title}</span>
  </button>;
}

/**
 * Inputs: One plan item.
 * Outputs: One progress segment colored by result.
 * Logic: Empty segments mean no result yet.
 * Dependencies: Result CSS classes.
 */
function ProgressSegment({ item }: { item: PlanItem }) {
  const result = item.attempt.feedback?.result;
  return <span className={`progress-segment ${result ? `result-${result}` : ""}`} />;
}

/**
 * Inputs: One result option.
 * Outputs: One guide row.
 * Logic: Show the letter badge, label, and short detail.
 * Dependencies: Result CSS classes.
 */
function GuideRow({ option }: { option: ResultOption }) {
  return <div><dt><span className={`result-letter result-${option.value}`}>{option.value}</span></dt><dd>{option.label} <span>· {option.detail}</span></dd></div>;
}

/**
 * Inputs: Date, plan, selection, lock state, and navigation callbacks.
 * Outputs: The plan sidebar.
 * Logic: Offer quick date steps, plan progress, and the result guide in one rail.
 * Dependencies: PlanButton, ProgressSegment, and date helpers.
 */
export function PlanSidebar(props: SidebarProps) {
  const { trainingDate, today, plan, selectedId, locked, loading, autoAdvance } = props;
  let recorded = 0;
  if (plan) for (const item of plan.items) if (item.attempt.feedback?.result) recorded += 1;

  /**
   * Inputs: A date input change.
   * Outputs: The selected date to the parent.
   * Logic: The parent validates the value.
   * Dependencies: onDateChange.
   */
  function changeDate(event: ChangeEvent<HTMLInputElement>) { props.onDateChange(event.currentTarget.value); }
  /**
   * Inputs: A previous-day click.
   * Outputs: A one-day backward shift.
   * Logic: Delegate to the parent.
   * Dependencies: onShiftDate.
   */
  function previousDay() { props.onShiftDate(-1); }
  /**
   * Inputs: A next-day click.
   * Outputs: A one-day forward shift.
   * Logic: Delegate to the parent.
   * Dependencies: onShiftDate.
   */
  function nextDay() { props.onShiftDate(1); }
  /**
   * Inputs: A checkbox change.
   * Outputs: The new auto-advance setting.
   * Logic: Keep the setting in page memory only.
   * Dependencies: onAutoAdvanceChange.
   */
  function toggleAdvance(event: ChangeEvent<HTMLInputElement>) { props.onAutoAdvanceChange(event.currentTarget.checked); }
  /**
   * Inputs: One plan item.
   * Outputs: A keyed rail button.
   * Logic: Compare with the selected attempt ID.
   * Dependencies: PlanButton.
   */
  function renderItem(item: PlanItem) {
    return <PlanButton key={item.attempt_id} item={item} selected={selectedId === item.attempt_id} locked={locked} onSelect={props.onSelect} />;
  }
  /**
   * Inputs: One plan item.
   * Outputs: A keyed progress segment.
   * Logic: Keep plan order.
   * Dependencies: ProgressSegment.
   */
  function renderSegment(item: PlanItem) { return <ProgressSegment key={item.attempt_id} item={item} />; }
  /**
   * Inputs: One result option.
   * Outputs: A keyed guide row.
   * Logic: Keep the A–F order.
   * Dependencies: GuideRow.
   */
  function renderGuide(option: ResultOption) { return <GuideRow key={option.value} option={option} />; }

  return (
    <aside className="plan-sidebar" aria-label="Daily training plan">
      <div className="date-control">
        <label htmlFor="training-date">Training date</label>
        <div className="date-row">
          <button type="button" className="icon-button" aria-label="Previous day" onClick={previousDay} disabled={locked || !trainingDate}>‹</button>
          <input id="training-date" aria-label="Training date" type="date" min="0001-01-01" max="9999-12-31" value={trainingDate} onChange={changeDate} disabled={locked} />
          <button type="button" className="icon-button" aria-label="Next day" onClick={nextDay} disabled={locked || !trainingDate}>›</button>
        </div>
        <div className="date-caption"><span>{trainingDate ? displayDate(trainingDate) : "Choose a training date"}</span>
          {trainingDate !== today && <button type="button" className="text-button" onClick={props.onToday} disabled={locked}>Today</button>}</div>
      </div>
      <div className="sidebar-heading"><h2>Saved plan</h2>
        <p>{plan ? `${recorded} of ${plan.items.length} recorded` : "Your saved daily plan"}</p>
        {plan && plan.items.length > 0 && <div className="plan-progress" role="img" aria-label={`${recorded} of ${plan.items.length} problems have a result`}>{plan.items.map(renderSegment)}</div>}
      </div>
      {plan && plan.items.length > 0 && <nav className="problem-navigation" aria-label="Saved plan problems">{plan.items.map(renderItem)}</nav>}
      <div className="sidebar-tools">
        <label className="toggle"><input type="checkbox" checked={autoAdvance} onChange={toggleAdvance} /> <span>Open next problem after saving</span></label>
        <button type="button" className="text-button" onClick={props.onRefresh} disabled={locked || loading || !trainingDate}>Refresh</button>
        <details className="result-help"><summary>Result guide <span>A–F</span></summary>
          <div className="guide-content"><dl className="result-guide">{RESULTS.map(renderGuide)}</dl>
            <p>Time and details are optional. Result changes use the current time. Corrections and detail updates keep the saved practice time.</p>
            <p className="guide-footnote">AC results are self-reported. Stable mastery needs spaced practice. E and F do not mean complete.</p></div>
        </details>
      </div>
    </aside>
  );
}
