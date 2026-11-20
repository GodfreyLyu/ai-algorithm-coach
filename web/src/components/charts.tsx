/** File purpose: Draw dependency-free result bars, legends, and a daily activity chart. */
import { useState } from "react";
import { RESULT_LABELS, SCORED_RESULTS } from "../constants";
import { formatMinutes, shiftDate, shortDate } from "../dates";
import type { ProgressDay, Result, ResultCounts } from "../types";

type SeriesKey = Result | "other";

const SERIES_LABELS: Record<SeriesKey, string> = { ...RESULT_LABELS, other: "Deferred or skipped" };

/**
 * Inputs: A list of series keys.
 * Outputs: A legend with one swatch and label per key.
 * Logic: Keep identity readable without relying on color alone.
 * Dependencies: Series CSS classes and labels.
 */
export function ResultLegend({ keys }: { keys: readonly SeriesKey[] }) {
  /**
   * Inputs: One series key.
   * Outputs: One legend item.
   * Logic: Pair a swatch with the letter and label.
   * Dependencies: SERIES_LABELS.
   */
  function renderKey(key: SeriesKey) {
    return <li key={key}><span className={`swatch series-${key}`} aria-hidden="true" />{key === "other" ? "E/F" : key} · {SERIES_LABELS[key]}</li>;
  }
  return <ul className="chart-legend" aria-label="Legend">{keys.map(renderKey)}</ul>;
}

/**
 * Inputs: A–D result counts and the topic name.
 * Outputs: A full-width stacked bar of the latest results.
 * Logic: Each segment width is its share of recorded problems. Empty counts are omitted.
 * Dependencies: Series CSS classes and SCORED_RESULTS.
 */
export function ResultBar({ counts, total, label }: { counts: Record<"A" | "B" | "C" | "D", number>; total: number; label: string }) {
  if (!total) return <div className="result-bar empty" aria-hidden="true" />;
  const parts: string[] = [];
  for (const key of SCORED_RESULTS) if (counts[key]) parts.push(`${key} ${counts[key]}`);
  /**
   * Inputs: One A–D key.
   * Outputs: A sized segment, or nothing for zero.
   * Logic: Use percentages so the bar fills the row.
   * Dependencies: counts and total.
   */
  function renderSegment(key: typeof SCORED_RESULTS[number]) {
    if (!counts[key]) return null;
    return <span key={key} className={`bar-segment series-${key}`} style={{ flexGrow: counts[key] }} title={`${key} · ${RESULT_LABELS[key]}: ${counts[key]}`} />;
  }
  return <div className="result-bar" role="img" aria-label={`${label}: ${parts.join(", ")} of ${total}`}>{SCORED_RESULTS.map(renderSegment)}</div>;
}

interface Column {
  date: string;
  day: ProgressDay | null;
  total: number;
}

/**
 * Inputs: One day's result counts.
 * Outputs: Counts for A–D and a merged E/F value.
 * Logic: Merge E and F because neither counts toward scores.
 * Dependencies: None.
 */
function seriesCounts(results: ResultCounts): Record<SeriesKey, number> {
  return { ...results, other: results.E + results.F };
}

/**
 * Inputs: One chart column and the largest daily total.
 * Outputs: One stacked column with a hover description.
 * Logic: Stack A at the bottom so stronger results form the base.
 * Dependencies: seriesCounts and series CSS classes.
 */
function ActivityColumn({ column, max }: { column: Column; max: number }) {
  const counts = column.day ? seriesCounts(column.day.results) : null;
  const keys: SeriesKey[] = ["A", "B", "C", "D", "other"];
  const details: string[] = [];
  if (counts) for (const key of keys) if (counts[key]) details.push(`${key === "other" ? "E/F" : key} ${counts[key]}`);
  const title = column.day ? `${shortDate(column.date)} · ${column.total} ${column.total === 1 ? "result" : "results"} (${details.join(", ")})${column.day.minutes ? ` · ${formatMinutes(column.day.minutes)}` : ""}` : `${shortDate(column.date)} · no results`;
  /**
   * Inputs: One series key.
   * Outputs: A sized segment, or nothing for zero.
   * Logic: Height is the count share of the largest day.
   * Dependencies: counts and max.
   */
  function renderSegment(key: SeriesKey) {
    if (!counts || !counts[key]) return null;
    return <span key={key} className={`column-segment series-${key}`} style={{ height: `${(counts[key] / max) * 100}%` }} />;
  }
  return <div className="activity-column" title={title} data-date={column.date}><div className="column-stack">{keys.map(renderSegment)}</div></div>;
}

/**
 * Inputs: One active day.
 * Outputs: One table row.
 * Logic: Show every result count for the table view.
 * Dependencies: shortDate and formatMinutes.
 */
function DayRow({ column }: { column: Column }) {
  const results = column.day!.results;
  return <tr><th scope="row">{shortDate(column.date)}</th><td>{results.A}</td><td>{results.B}</td><td>{results.C}</td><td>{results.D}</td><td>{results.E + results.F}</td><td>{column.day!.minutes ? formatMinutes(column.day!.minutes) : "–"}</td></tr>;
}

/**
 * Inputs: Saved daily progress and the last calendar day to show.
 * Outputs: A stacked daily column chart with a range toggle and a table view.
 * Logic: Fill missing days with empty columns. Scale to the busiest day in range.
 * Dependencies: ActivityColumn, ResultLegend, and date helpers.
 */
export function ActivityChart({ days, endDate }: { days: ProgressDay[]; endDate: string }) {
  const [span, setSpan] = useState(28);
  const byDate = new Map<string, ProgressDay>();
  for (const day of days) byDate.set(day.date, day);
  const columns: Column[] = [];
  let max = 1;
  let results = 0;
  let minutes = 0;
  let active = 0;
  for (let offset = span - 1; offset >= 0; offset -= 1) {
    const date = shiftDate(endDate, -offset);
    const day = byDate.get(date) ?? null;
    let total = 0;
    if (day) for (const value of Object.values(day.results)) total += value;
    if (day && total) { active += 1; results += total; minutes += day.minutes; }
    max = Math.max(max, total);
    columns.push({ date, day: total ? day : null, total });
  }
  /**
   * Inputs: A four-week click.
   * Outputs: A 28-day range.
   * Logic: Store the range in component state.
   * Dependencies: setSpan.
   */
  function showMonth() { setSpan(28); }
  /**
   * Inputs: A twelve-week click.
   * Outputs: An 84-day range.
   * Logic: Store the range in component state.
   * Dependencies: setSpan.
   */
  function showQuarter() { setSpan(84); }
  /**
   * Inputs: One column.
   * Outputs: A keyed chart column.
   * Logic: Share the range maximum.
   * Dependencies: ActivityColumn.
   */
  function renderColumn(column: Column) { return <ActivityColumn key={column.date} column={column} max={max} />; }
  /**
   * Inputs: One column.
   * Outputs: A table row for active days only.
   * Logic: Skip empty days in the table.
   * Dependencies: DayRow.
   */
  function renderRow(column: Column) { return column.day ? <DayRow key={column.date} column={column} /> : null; }

  return (
    <section className="activity-panel" aria-labelledby="activity-title">
      <div className="panel-heading">
        <div><h2 id="activity-title">Practice activity</h2>
          <p>{results ? `${results} ${results === 1 ? "result" : "results"} on ${active} ${active === 1 ? "day" : "days"}${minutes ? ` · ${formatMinutes(minutes)}` : ""}` : "No results in this range"}</p></div>
        <div className="segmented" role="group" aria-label="Activity range">
          <button type="button" aria-pressed={span === 28} onClick={showMonth}>4 weeks</button>
          <button type="button" aria-pressed={span === 84} onClick={showQuarter}>12 weeks</button>
        </div>
      </div>
      <div className="activity-chart" role="img" aria-label={`Daily results for the last ${span} days. The busiest day had ${max} results.`}>
        <div className="activity-axis" aria-hidden="true"><span>{max}</span><span>0</span></div>
        <div className="activity-plot"><div className="activity-columns">{columns.map(renderColumn)}</div>
          <div className="activity-dates" aria-hidden="true"><span>{shortDate(columns[0].date)}</span><span>{shortDate(columns[Math.floor(columns.length / 2)].date)}</span><span>{shortDate(columns[columns.length - 1].date)}</span></div></div>
      </div>
      <ResultLegend keys={["A", "B", "C", "D", "other"]} />
      {results > 0 && <details className="table-view"><summary>Show as table</summary>
        <div className="table-scroll"><table className="data-table"><caption className="sr-only">Daily results in range</caption>
          <thead><tr><th scope="col">Date</th><th scope="col">A</th><th scope="col">B</th><th scope="col">C</th><th scope="col">D</th><th scope="col">E/F</th><th scope="col">Time</th></tr></thead>
          <tbody>{columns.map(renderRow)}</tbody></table></div></details>}
    </section>
  );
}
