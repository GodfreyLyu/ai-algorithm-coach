/** File purpose: Describe the narrow HTTP contracts used by the record UI. */
export type Result = "A" | "B" | "C" | "D" | "E" | "F";

export interface Context {
  workspace_id: string;
  store_id: string;
  training_date: string;
  timezone: string;
  language: string;
  api_version: string;
  app_version: string;
}

export interface Feedback {
  result: Result | null;
  elapsed_minutes: number | null;
  blocked_on: string | null;
  explanation: "not_tried" | "partial" | "clear" | "uncertain" | null;
  boundary_tests: boolean | null;
  proficiency: number | null;
  time_complexity: string | null;
  space_complexity: string | null;
  defer_until: string | null;
  skip_until: string | null;
  assistance?: "none" | "hint" | "solution" | null;
}

export interface Problem {
  id: string;
  title: string;
  difficulty: string;
  tags: string[];
  url: string;
}

export interface Attempt {
  id: string;
  language: string;
  revision: number;
  feedback: Feedback | null;
}

export interface PlanItem {
  position: number;
  reason: string;
  attempt_id: string;
  problem: Problem;
  attempt: Attempt;
}

export interface Plan {
  id: string;
  training_date: string;
  timezone: string;
  items: PlanItem[];
  current_policy_conflicts?: unknown[];
}

export interface Receipt {
  status: string;
  submission_id: string;
  attempt_id: string;
  revision: number;
  operation: string;
  payload_hash: string;
}

export interface SavedFeedback {
  receipt: Receipt;
  feedback_revision: {
    attempt_id: string;
    revision: number;
    submission_id: string;
    kind: "progress" | "correction";
    changes: Partial<Feedback>;
    snapshot: Feedback;
  };
}

export interface FeedbackRequest {
  submission_id: string;
  expected_revision: number;
  kind: "progress" | "correction";
  changes: Partial<Feedback>;
}

export interface Topic {
  tag: string;
  score: number | null;
  independent_count: number;
  problem_count: number;
  stable_count: number;
  sample_small: boolean;
  results: { A: number; B: number; C: number; D: number };
}

export interface Scores {
  language: string;
  basis: string;
  metric: string;
  score_version: string | number;
  state_version: number;
  topics: Topic[];
}

export interface SolutionDocument {
  code: string;
  language: string;
  input_definition?: string | null;
}

export interface SolutionRequest {
  submission_id: string;
  expected_revision: number;
  document: SolutionDocument;
}

export interface SolutionReceipt {
  status: string;
  submission_id: string;
  attempt_id: string;
  operation: string;
  feedback_revision?: number;
  revision?: number;
  evidence_id: string;
  code_hash: string;
  payload_hash: string;
}

export interface SavedSolution {
  receipt: SolutionReceipt;
}

export interface ComplexityItem {
  attempt_id: string;
  feedback_revision: number;
  status: "awaiting_code" | "pending" | "supported" | "issues" | "insufficient_information" | "stale";
  evidence: Record<string, unknown> | null;
  review: Record<string, unknown> | null;
}

export interface ComplexityStatus {
  items: ComplexityItem[];
}

export type ResultCounts = Record<Result, number>;

export interface ProgressDay {
  date: string;
  results: ResultCounts;
  minutes: number;
}

export interface ProgressProblem {
  problem_id: string;
  title: string;
  difficulty: string;
  url: string;
  tags: string[];
  result: "A" | "B" | "C" | "D";
  practice_date: string;
  attempt_count: number;
  stable: boolean;
}

export interface Progress {
  language: string;
  basis: string;
  progress_version: string;
  state_version: number;
  days: ProgressDay[];
  problems: ProgressProblem[];
}
