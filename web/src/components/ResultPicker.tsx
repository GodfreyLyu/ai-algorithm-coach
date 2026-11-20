/** File purpose: Offer the six self-reported results as a compact keyboard-friendly grid. */
import { RESULTS, type ResultOption } from "../constants";
import type { Result } from "../types";

/**
 * Inputs: One result option, its selection state, and a selection handler.
 * Outputs: An accessible single-choice result card.
 * Logic: Forward a deliberate choice without setting an implicit default.
 * Dependencies: React and the parent picker.
 */
function ResultChoice({ option, selected, onSelect }: {
  option: ResultOption; selected: boolean; onSelect: (result: Result) => void;
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
      <input type="radio" name="result" value={option.value} checked={selected} onChange={selectResult} />
      <span className={`result-letter result-${option.value}`} aria-hidden="true">{option.value}</span>
      <span className="result-text"><strong>{option.label}</strong><small>{option.detail}</small></span>
    </label>
  );
}

/**
 * Inputs: The selected result, a change handler, and an optional clear action.
 * Outputs: A fieldset with six result cards and a shortcut hint.
 * Logic: Keep native radio semantics so arrow keys still move the choice.
 * Dependencies: ResultChoice and the shared result options.
 */
export function ResultPicker({ value, onChange, onClear }: {
  value: string; onChange: (result: Result) => void; onClear: (() => void) | null;
}) {
  /**
   * Inputs: One result option.
   * Outputs: A keyed result card.
   * Logic: Compare the option with the current draft value.
   * Dependencies: ResultChoice.
   */
  function renderChoice(option: ResultOption) {
    return <ResultChoice key={option.value} option={option} selected={value === option.value} onSelect={onChange} />;
  }
  return (
    <fieldset className="result-fieldset">
      <legend>Result <span className="shortcut-hint">Press A–F</span></legend>
      <div className="result-grid">{RESULTS.map(renderChoice)}</div>
      {onClear && value !== "" && <button type="button" className="text-button" onClick={onClear}>Clear reported result</button>}
    </fieldset>
  );
}
