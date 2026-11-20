/** File purpose: Convert form drafts to API changes and verify save receipts. */
import type { ComplexityItem, Feedback, FeedbackRequest, SavedFeedback, SavedSolution, SolutionDocument, SolutionRequest } from "./types";

export type Field = Exclude<keyof Feedback, "assistance">;
export type Draft = Record<Field, string>;
export type Mode = "progress" | "correction";

export interface FeedbackDraft {
  values: Draft;
  touched: Set<Field>;
  mode: Mode;
}

export type SolutionDraft = Partial<Record<"code" | "input_definition", string>>;

export interface DraftStore {
  feedback: Map<string, FeedbackDraft>;
  solution: Map<string, SolutionDraft>;
}

export const DETAIL_FIELDS: Field[] = ["time_complexity", "space_complexity", "blocked_on", "explanation", "boundary_tests", "proficiency"];

/**
 * Inputs: None.
 * Outputs: Empty in-page draft maps.
 * Logic: Keep feedback and code drafts apart. Nothing is written to browser storage.
 * Dependencies: None.
 */
export function createDraftStore(): DraftStore {
  return { feedback: new Map(), solution: new Map() };
}

/**
 * Inputs: An optional saved feedback snapshot.
 * Outputs: String values for the controlled form.
 * Logic: Preserve false and zero while displaying unanswered fields as blank.
 * Dependencies: The feedback API contract.
 */
export function makeDraft(feedback: Feedback | null): Draft {
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
export function makeChanges(draft: Draft, touched: Set<Field>): Partial<Feedback> {
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
 * Inputs: A feedback save response, its request, and the attempt ID.
 * Outputs: The committed revision number.
 * Logic: Match identity, operation, revision, kind, and exact changes. Throw on mismatch.
 * Dependencies: sameChanges and the receipt contract.
 */
export function verifyFeedbackReceipt(saved: SavedFeedback, original: FeedbackRequest, attemptId: string): number {
  const receipt = saved.receipt;
  const revision = saved.feedback_revision;
  if (receipt.status !== "applied" || receipt.submission_id !== original.submission_id ||
      receipt.attempt_id !== attemptId || receipt.operation !== "submit_feedback" ||
      receipt.revision !== original.expected_revision + 1 || !revision ||
      revision.revision !== receipt.revision || revision.attempt_id !== attemptId ||
      revision.submission_id !== original.submission_id || revision.kind !== original.kind ||
      !sameChanges(original.changes, revision.changes) || !receipt.payload_hash) {
    throw new Error("The save receipt could not be matched.");
  }
  return receipt.revision;
}

/**
 * Inputs: A code save response, its request, and the attempt ID.
 * Outputs: The committed evidence ID and code hash.
 * Logic: Hash the submitted code and match it with the receipt. Throw on mismatch.
 * Dependencies: Web Crypto SHA-256 and the receipt contract.
 */
export async function verifySolutionReceipt(saved: SavedSolution, original: SolutionRequest, attemptId: string): Promise<{ evidenceId: string; codeHash: string }> {
  const receipt = saved.receipt;
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(original.document.code));
  let expectedHash = "";
  for (const byte of new Uint8Array(digest)) expectedHash += byte.toString(16).padStart(2, "0");
  if (receipt.status !== "applied" || receipt.operation !== "record_solution" ||
      receipt.submission_id !== original.submission_id || receipt.attempt_id !== attemptId ||
      receipt.feedback_revision !== original.expected_revision || !receipt.evidence_id ||
      receipt.code_hash !== expectedHash || !receipt.payload_hash) {
    throw new Error("The code save receipt could not be matched.");
  }
  return { evidenceId: receipt.evidence_id, codeHash: receipt.code_hash };
}

/**
 * Inputs: A saved review status and one conclusion field.
 * Outputs: The saved text when the field is present.
 * Logic: Read only known text fields from the structured review body.
 * Dependencies: The complexity status contract.
 */
export function conclusion(item: ComplexityItem | null, field: string): string | null {
  const body = item?.review?.body;
  if (!body || typeof body !== "object") return null;
  const value = (body as Record<string, unknown>)[field];
  return typeof value === "string" ? value : null;
}

/**
 * Inputs: One status response and the attempt's expected code language.
 * Outputs: A saved solution document and its bound feedback revision, or null.
 * Logic: Read known evidence fields without confusing their revision with the current attempt.
 * Dependencies: The solution evidence response contract.
 */
export function solutionFromStatus(item: ComplexityItem | null, language: string): { document: SolutionDocument; revision: number } | null {
  const evidence = item?.evidence;
  const body = evidence?.body;
  const revision = evidence?.feedback_revision;
  if (!body || typeof body !== "object" || Array.isArray(body) || typeof revision !== "number" || !Number.isInteger(revision) || revision < 0) return null;
  const saved = body as Record<string, unknown>;
  if (typeof saved.code !== "string" || saved.language !== language ||
      (saved.input_definition !== undefined && saved.input_definition !== null && typeof saved.input_definition !== "string")) return null;
  const document: SolutionDocument = { code: saved.code, language };
  if (saved.input_definition !== undefined) document.input_definition = saved.input_definition as string | null;
  return { document, revision };
}
