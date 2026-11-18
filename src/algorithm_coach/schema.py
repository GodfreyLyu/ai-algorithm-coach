"""Define the complete current schema without older storage formats or upgrade paths."""


SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE config (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    revision INTEGER NOT NULL, body TEXT NOT NULL
);
CREATE TABLE problems (id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE attempts (
    id TEXT PRIMARY KEY, problem_id TEXT NOT NULL REFERENCES problems(id),
    language TEXT NOT NULL, kind TEXT NOT NULL,
    planned_date TEXT NOT NULL, source_attempt_id TEXT REFERENCES attempts(id),
    review_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE plans (
    id TEXT PRIMARY KEY, training_date TEXT NOT NULL UNIQUE,
    timezone TEXT NOT NULL, config_revision INTEGER NOT NULL,
    config_snapshot TEXT NOT NULL, state_version INTEGER NOT NULL,
    catalog_version TEXT NOT NULL, rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL, policy_revision INTEGER NOT NULL DEFAULT 0,
    policy_snapshot TEXT NOT NULL DEFAULT '{}', diagnostics TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE plan_items (
    plan_id TEXT NOT NULL REFERENCES plans(id), position INTEGER NOT NULL,
    attempt_id TEXT NOT NULL REFERENCES attempts(id), reason TEXT NOT NULL,
    PRIMARY KEY(plan_id, position), UNIQUE(plan_id, attempt_id)
);
CREATE TABLE feedback (
    attempt_id TEXT NOT NULL REFERENCES attempts(id), revision INTEGER NOT NULL,
    submission_id TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
    changes TEXT NOT NULL, snapshot TEXT NOT NULL,
    practice_date TEXT NOT NULL, occurred_at TEXT NOT NULL,
    received_at TEXT NOT NULL, PRIMARY KEY(attempt_id, revision)
);
CREATE TABLE submissions (
    id TEXT PRIMARY KEY, operation TEXT NOT NULL,
    payload_hash TEXT NOT NULL, receipt TEXT NOT NULL
);
CREATE TABLE learning_state (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    version INTEGER NOT NULL, body TEXT NOT NULL
);
CREATE TABLE reviews (
    id TEXT PRIMARY KEY,
    source_attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(id),
    problem_id TEXT NOT NULL REFERENCES problems(id), language TEXT NOT NULL,
    due_date TEXT NOT NULL, status TEXT NOT NULL,
    attempt_id TEXT UNIQUE REFERENCES attempts(id)
);
CREATE INDEX feedback_latest ON feedback(attempt_id, revision DESC);
CREATE INDEX attempts_problem ON attempts(problem_id, language);
CREATE TRIGGER feedback_no_update BEFORE UPDATE ON feedback
BEGIN SELECT RAISE(ABORT, 'Feedback history is immutable'); END;
CREATE TRIGGER feedback_no_delete BEFORE DELETE ON feedback
BEGIN SELECT RAISE(ABORT, 'Feedback history is immutable'); END;
CREATE TRIGGER submissions_no_update BEFORE UPDATE ON submissions
BEGIN SELECT RAISE(ABORT, 'Submission receipts are immutable'); END;
CREATE TRIGGER submissions_no_delete BEFORE DELETE ON submissions
BEGIN SELECT RAISE(ABORT, 'Submission receipts are immutable'); END;

CREATE TABLE policy_proposals (
    id TEXT PRIMARY KEY, body TEXT NOT NULL, content_hash TEXT NOT NULL,
    base_revision INTEGER NOT NULL, config_revision INTEGER NOT NULL,
    catalog_version TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE policies (
    revision INTEGER PRIMARY KEY,
    proposal_id TEXT UNIQUE REFERENCES policy_proposals(id),
    body TEXT NOT NULL, content_hash TEXT NOT NULL, activated_at TEXT NOT NULL
);
CREATE TRIGGER proposals_no_update BEFORE UPDATE ON policy_proposals
BEGIN SELECT RAISE(ABORT, 'Policy proposals are immutable'); END;
CREATE TRIGGER proposals_no_delete BEFORE DELETE ON policy_proposals
BEGIN SELECT RAISE(ABORT, 'Policy proposals are immutable'); END;
CREATE TRIGGER policies_no_update BEFORE UPDATE ON policies
BEGIN SELECT RAISE(ABORT, 'Policy activations are immutable'); END;
CREATE TRIGGER policies_no_delete BEFORE DELETE ON policies
BEGIN SELECT RAISE(ABORT, 'Policy activations are immutable'); END;

CREATE TABLE solution_evidence (
    id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL REFERENCES attempts(id),
    feedback_revision INTEGER NOT NULL, code_hash TEXT NOT NULL,
    body TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE complexity_reviews (
    id TEXT PRIMARY KEY, evidence_id TEXT NOT NULL REFERENCES solution_evidence(id),
    body TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE training_contexts (
    id INTEGER PRIMARY KEY, problem_id TEXT NOT NULL REFERENCES problems(id),
    attempt_id TEXT REFERENCES attempts(id), body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX evidence_attempt ON solution_evidence(attempt_id, created_at);
CREATE TRIGGER evidence_no_update BEFORE UPDATE ON solution_evidence
BEGIN SELECT RAISE(ABORT, 'Solution evidence is immutable'); END;
CREATE TRIGGER evidence_no_delete BEFORE DELETE ON solution_evidence
BEGIN SELECT RAISE(ABORT, 'Solution evidence is immutable'); END;
CREATE TRIGGER complexity_no_update BEFORE UPDATE ON complexity_reviews
BEGIN SELECT RAISE(ABORT, 'Complexity reviews are immutable'); END;
CREATE TRIGGER complexity_no_delete BEFORE DELETE ON complexity_reviews
BEGIN SELECT RAISE(ABORT, 'Complexity reviews are immutable'); END;
CREATE TRIGGER context_no_update BEFORE UPDATE ON training_contexts
BEGIN SELECT RAISE(ABORT, 'Training evidence is immutable'); END;
CREATE TRIGGER context_no_delete BEFORE DELETE ON training_contexts
BEGIN SELECT RAISE(ABORT, 'Training evidence is immutable'); END;

CREATE TABLE learning_checkpoints (
    problem_id TEXT NOT NULL REFERENCES problems(id), language TEXT NOT NULL,
    body TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(problem_id, language)
);
CREATE TABLE history_evidence (
    id TEXT PRIMARY KEY, problem_id TEXT REFERENCES problems(id),
    attempt_id TEXT REFERENCES attempts(id), occurred_at TEXT,
    kind TEXT NOT NULL, body TEXT NOT NULL
);
CREATE INDEX history_problem ON history_evidence(problem_id, occurred_at);
CREATE TRIGGER checkpoints_no_update BEFORE UPDATE ON learning_checkpoints
BEGIN SELECT RAISE(ABORT, 'Learning checkpoints are immutable'); END;
CREATE TRIGGER checkpoints_no_delete BEFORE DELETE ON learning_checkpoints
BEGIN SELECT RAISE(ABORT, 'Learning checkpoints are immutable'); END;
CREATE TRIGGER history_no_update BEFORE UPDATE ON history_evidence
BEGIN SELECT RAISE(ABORT, 'History evidence is immutable'); END;
CREATE TRIGGER history_no_delete BEFORE DELETE ON history_evidence
BEGIN SELECT RAISE(ABORT, 'History evidence is immutable'); END;
"""

CURRENT_TABLES = frozenset({
    "metadata", "config", "problems", "attempts", "plans", "plan_items",
    "feedback", "submissions", "learning_state", "reviews", "policy_proposals",
    "policies", "solution_evidence", "complexity_reviews", "training_contexts",
    "learning_checkpoints", "history_evidence",
})
