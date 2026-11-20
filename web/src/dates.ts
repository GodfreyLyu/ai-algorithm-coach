/** File purpose: Validate, shift, and format calendar dates without browser timezones. */

/**
 * Inputs: A candidate calendar date from a session link or date input.
 * Outputs: Whether the date is a real YYYY-MM-DD day supported by the core.
 * Logic: Reject malformed dates, year zero, and normalized invalid days.
 * Dependencies: The browser's ISO date parser.
 */
export function isTrainingDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000-")) return false;
  const parsed = new Date(`${value}T12:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

/**
 * Inputs: A valid calendar date and a whole number of days.
 * Outputs: The shifted calendar date, or the input when the result is invalid.
 * Logic: Shift at UTC noon so local daylight changes cannot move the day.
 * Dependencies: isTrainingDate and the browser date type.
 */
export function shiftDate(value: string, days: number): string {
  const parsed = new Date(`${value}T12:00:00Z`);
  parsed.setUTCDate(parsed.getUTCDate() + days);
  const shifted = parsed.toISOString().slice(0, 10);
  return isTrainingDate(shifted) ? shifted : value;
}

/**
 * Inputs: A saved ISO training date.
 * Outputs: A long day label without shifting its timezone.
 * Logic: Format the supplied date as calendar text, not a browser-local instant.
 * Dependencies: The standard date formatter.
 */
export function displayDate(value: string): string {
  return new Intl.DateTimeFormat("en", { weekday: "long", month: "long", day: "numeric", year: "numeric", timeZone: "UTC" }).format(new Date(`${value}T12:00:00Z`));
}

/**
 * Inputs: A saved ISO training date.
 * Outputs: A short month and day label for chart axes.
 * Logic: Format at UTC noon to keep the calendar day.
 * Dependencies: The standard date formatter.
 */
export function shortDate(value: string): string {
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", timeZone: "UTC" }).format(new Date(`${value}T12:00:00Z`));
}

/**
 * Inputs: A number of minutes.
 * Outputs: Compact text such as "45 min" or "3 h 20 min".
 * Logic: Round to whole minutes and split hours when useful.
 * Dependencies: None.
 */
export function formatMinutes(minutes: number): string {
  const total = Math.round(minutes);
  if (total < 60) return `${total} min`;
  const rest = total % 60;
  return rest ? `${Math.floor(total / 60)} h ${rest} min` : `${total / 60} h`;
}
