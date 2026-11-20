/** File purpose: Share result labels, review labels, and plan reason text across views. */
import type { ComplexityItem, Result } from "./types";

export interface ResultOption {
  value: Result;
  label: string;
  detail: string;
}

export const RESULTS: ResultOption[] = [
  { value: "A", label: "Independent AC", detail: "No hints" },
  { value: "B", label: "AC with hints", detail: "Some help" },
  { value: "C", label: "AC after answer", detail: "Read a solution" },
  { value: "D", label: "Not yet AC", detail: "Keep working" },
  { value: "E", label: "Defer", detail: "Do it later" },
  { value: "F", label: "Skip", detail: "End this attempt" },
];

export const RESULT_LABELS: Record<Result, string> = {
  A: "Independent AC", B: "AC with hints", C: "AC after answer",
  D: "Not yet AC", E: "Defer", F: "Skip",
};

export const SCORED_RESULTS = ["A", "B", "C", "D"] as const;

export const COMPLEXITIES = ["O(1)", "O(log n)", "O(n)", "O(n log n)", "O(n²)", "O(n³)", "O(2ⁿ)", "O(n!)", "O(n+m)", "O(nm)"];

export const REVIEW_LABELS: Record<ComplexityItem["status"], string> = {
  awaiting_code: "No code submitted",
  pending: "Code saved · awaiting review",
  supported: "Analysis supports this version",
  issues: "Review found an issue",
  insufficient_information: "More information needed",
  stale: "Review belongs to an earlier feedback version",
};

const REASON_LABELS: Record<string, string> = {
  continue: "Continue",
  retest: "Retest",
  weakness: "Weak topic",
  preferred_topic: "Preferred topic",
  foundation: "Foundation",
  representative: "Representative",
};

/**
 * Inputs: A saved plan item reason code.
 * Outputs: Short readable text for the reason.
 * Logic: Use a known label or turn underscores into spaces.
 * Dependencies: The reason label table.
 */
export function reasonLabel(reason: string): string {
  return REASON_LABELS[reason] ?? reason.replaceAll("_", " ");
}

/**
 * Inputs: A topic tag from catalog metadata.
 * Outputs: Display text for the tag.
 * Logic: Replace hyphens with spaces. Keep the original wording.
 * Dependencies: None.
 */
export function tagLabel(tag: string): string {
  return tag.replaceAll("-", " ");
}
