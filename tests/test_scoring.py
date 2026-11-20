"""Verify distinct-problem scores and read-only service behavior with synthetic data."""

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algorithm_coach.errors import CoachError
from algorithm_coach.scoring import derive_practice_progress, derive_topic_scores
from algorithm_coach.service import Coach


def _catalog(count: int = 8) -> list[dict]:
    """Create metadata for a shared topic plus one unpracticed topic.

    Inputs: The number of distinct synthetic problem references.
    Outputs: Catalog metadata without statements or personal records.
    Logic: Give every problem a shared tag and the first problem two tags.
    Dependencies: None.
    """
    result = []
    for number in range(1, count + 1):
        tags = ["shared"]
        if number == 1:
            tags.append("secondary")
        result.append({
            "id": f"leetcode:{number}", "title": f"Synthetic Metadata {number}",
            "difficulty": "easy", "tags": tags,
            "url": f"https://leetcode.com/problems/synthetic-metadata-{number}/",
        })
    result.append({
        "id": "leetcode:9999", "title": "Unpracticed Metadata", "difficulty": "easy",
        "tags": ["unpracticed"], "url": "https://leetcode.com/problems/unpracticed-metadata/",
    })
    return result


def _attempt(identifier: str, problem: int, result: str | None, day: str = "2026-01-01", language: str = "Java", **extra: object) -> dict:
    """Create one effective synthetic practice snapshot.

    Inputs: ID, problem number, result, practice day, language, and overrides.
    Outputs: An attempt record using the core read contract.
    Logic: Keep practice time separate from optional correction receipt time.
    Dependencies: None.
    """
    return {
        "id": identifier, "problem_id": f"leetcode:{problem}", "language": language,
        "planned_date": day, "practice_date": day,
        "occurred_at": f"{day}T12:00:00+00:00", "created_at": f"{day}T10:00:00+00:00",
        "feedback": {"result": result} if result is not None else None, **extra,
    }


def _topic(scores: dict, tag: str = "shared") -> dict:
    """Find a named topic in a score response.

    Inputs: A score response and a tag.
    Outputs: The matching topic record.
    Logic: Search returned data without depending on display order.
    Dependencies: None.
    """
    return next(topic for topic in scores["topics"] if topic["tag"] == tag)


class TopicScoreTests(unittest.TestCase):
    """Test the score definition independently of storage and UI."""

    def test_repeated_attempts_count_each_problem_once(self) -> None:
        """Use the newest valid result for each distinct problem.

        Inputs: Repeated A reports, a later D, and a separate A problem.
        Outputs: A 50 score with one A and one D in the denominator.
        Logic: Additional practice on one problem must not inflate its weight.
        Dependencies: derive_topic_scores.
        """
        attempts = [
            _attempt("first", 1, "A"), _attempt("again", 1, "A", "2026-01-02"),
            _attempt("later", 1, "D", "2026-01-03"), _attempt("different", 2, "A"),
        ]
        topic = _topic(derive_topic_scores(attempts, _catalog(), "Java", []))
        self.assertEqual(topic["score"], 50)
        self.assertEqual(topic["problem_count"], 2)
        self.assertEqual(topic["results"], {"A": 1, "B": 0, "C": 0, "D": 1})

    def test_defer_skip_and_unknown_preserve_earlier_valid_evidence(self) -> None:
        """Ignore later practice that makes no valid ability claim.

        Inputs: A C result followed by E, F, and unanswered attempts.
        Outputs: One C problem and a zero independent rate.
        Logic: Scheduling outcomes must not erase earlier A-D evidence.
        Dependencies: derive_topic_scores.
        """
        attempts = [
            _attempt("valid", 1, "C"), _attempt("defer", 1, "E", "2026-01-02"),
            _attempt("skip", 1, "F", "2026-01-03"), _attempt("unknown", 1, None, "2026-01-04"),
            _attempt("never-valid", 2, "F"),
        ]
        topic = _topic(derive_topic_scores(attempts, _catalog(), "Java", []))
        self.assertEqual(topic["problem_count"], 1)
        self.assertEqual(topic["results"], {"A": 0, "B": 0, "C": 1, "D": 0})
        self.assertEqual(topic["score"], 0)

    def test_correction_receipt_time_does_not_reorder_practice(self) -> None:
        """Keep actual practice chronology after an old report is corrected.

        Inputs: An old corrected A received after a newer D practice.
        Outputs: The newer D remains the latest evidence.
        Logic: received_at must never participate in score ordering.
        Dependencies: derive_topic_scores.
        """
        attempts = [
            _attempt("corrected-old", 1, "A", received_at="2026-12-01T00:00:00+00:00"),
            _attempt("newer-practice", 1, "D", "2026-01-02", received_at="2026-01-02T12:00:00+00:00"),
        ]
        topic = _topic(derive_topic_scores(attempts, _catalog(), "Java", []))
        self.assertEqual(topic["results"]["D"], 1)
        self.assertEqual(topic["score"], 0)

    def test_same_day_order_uses_occurrence_then_creation_then_id(self) -> None:
        """Use complete stable chronology for same-day evidence.

        Inputs: Same-day practices with reversed IDs and tied event times.
        Outputs: Occurrence and creation times take precedence over IDs.
        Logic: Evaluate each documented tie breaker without relying on input order.
        Dependencies: derive_topic_scores.
        """
        earlier = _attempt("z", 1, "A", occurred_at="2026-01-01T11:00:00+00:00")
        later = _attempt("a", 1, "D", occurred_at="2026-01-01T12:00:00+00:00")
        self.assertEqual(_topic(derive_topic_scores([later, earlier], _catalog(), "Java", []))["score"], 0)
        earlier["occurred_at"] = later["occurred_at"]
        later["created_at"] = "2026-01-01T11:00:00+00:00"
        self.assertEqual(_topic(derive_topic_scores([later, earlier], _catalog(), "Java", []))["score"], 0)
        earlier["created_at"] = later["created_at"]
        self.assertEqual(_topic(derive_topic_scores([later, earlier], _catalog(), "Java", []))["score"], 100)

    def test_languages_and_multiple_tags_do_not_duplicate_evidence(self) -> None:
        """Separate language evidence and count each problem once per tag.

        Inputs: Java A and Python D for a problem with two topic labels.
        Outputs: Java scores 100 for both tags and Python scores zero.
        Logic: Tags share the same evidence without multiplying the denominator.
        Dependencies: derive_topic_scores.
        """
        catalog = _catalog()
        catalog[0]["tags"].append("shared")
        attempts = [_attempt("java", 1, "A"), _attempt("python", 1, "D", language="Python")]
        java = derive_topic_scores(attempts, catalog, "Java", [])
        python = derive_topic_scores(attempts, catalog, "Python", [])
        for tag in ("shared", "secondary"):
            self.assertEqual(_topic(java, tag)["problem_count"], 1)
            self.assertEqual(_topic(java, tag)["score"], 100)
            self.assertEqual(_topic(python, tag)["score"], 0)

    def test_half_ties_round_up_and_small_samples_are_explicit(self) -> None:
        """Round the 12.5 percent tie upward using exact integer arithmetic.

        Inputs: One independent problem and seven valid assisted or unfinished ones.
        Outputs: Score 13, with a separate small-sample flag below five problems.
        Logic: Keep score rounding and evidence sufficiency separate.
        Dependencies: derive_topic_scores.
        """
        attempts = [_attempt(f"problem-{number}", number, "A" if number == 1 else "B") for number in range(1, 9)]
        topic = _topic(derive_topic_scores(attempts, _catalog(), "Java", []))
        self.assertEqual(topic["score"], 13)
        self.assertFalse(topic["sample_small"])
        self.assertTrue(_topic(derive_topic_scores(attempts[:4], _catalog(), "Java", []))["sample_small"])
        self.assertFalse(_topic(derive_topic_scores(attempts[:5], _catalog(), "Java", []))["sample_small"])

    def test_all_catalog_topics_include_unpracticed_and_unverified_results(self) -> None:
        """Return empty evidence explicitly without creating mastery claims.

        Inputs: A catalog with no valid attempts or stable problem states.
        Outputs: Null scores, zero distributions, and self-reported provenance.
        Logic: Missing practice is not a zero achievement score or verified failure.
        Dependencies: derive_topic_scores.
        """
        scores = derive_topic_scores([], _catalog(), "Java", [])
        self.assertEqual(scores["basis"], "self_reported")
        self.assertEqual(scores["metric"], "independent_completion_rate")
        self.assertEqual(scores["score_version"], "1")
        self.assertEqual({topic["tag"] for topic in scores["topics"]}, {"shared", "secondary", "unpracticed"})
        for topic in scores["topics"]:
            self.assertIsNone(topic["score"])
            self.assertEqual(topic["problem_count"], 0)
            self.assertEqual(topic["stable_count"], 0)
            self.assertTrue(topic["sample_small"])
            self.assertEqual(topic["results"], {"A": 0, "B": 0, "C": 0, "D": 0})

    def test_stable_count_reuses_existing_mastery_without_promotion(self) -> None:
        """Keep a perfect rate separate from stable mastery.

        Inputs: Two independent problems but only one existing stable problem state.
        Outputs: A perfect score and exactly one stable problem.
        Logic: Score calculation must not invent another mastery rule.
        Dependencies: derive_topic_scores and passed problem-state records.
        """
        attempts = [_attempt("one", 1, "A"), _attempt("two", 2, "A")]
        states = [
            {"problem_id": "leetcode:1", "language": "Java", "mastery_status": "stable"},
            {"problem_id": "leetcode:2", "language": "Java", "mastery_status": "independent"},
            {"problem_id": "leetcode:2", "language": "Python", "mastery_status": "stable"},
        ]
        originals = deepcopy((attempts, states))
        topic = _topic(derive_topic_scores(attempts, _catalog(), "Java", states))
        self.assertEqual(topic["score"], 100)
        self.assertEqual(topic["stable_count"], 1)
        self.assertEqual((attempts, states), originals)


class PracticeProgressTests(unittest.TestCase):
    """Verify read-only daily activity and per-problem progress rows."""

    def test_days_count_every_current_result_and_minutes(self) -> None:
        """Group current results and minutes by practice date.

        Inputs: A, D, E, and empty results on two days plus another language.
        Outputs: Daily A-F counts and summed minutes for the selected language.
        Logic: Count each attempt once and ignore unanswered or foreign attempts.
        Dependencies: derive_practice_progress.
        """
        attempts = [
            _attempt("a1", 1, "A", "2026-01-01", feedback={"result": "A", "elapsed_minutes": 20}),
            _attempt("a2", 2, "D", "2026-01-01", feedback={"result": "D", "elapsed_minutes": 15.5}),
            _attempt("a3", 3, "E", "2026-01-03"),
            _attempt("a4", 4, None, "2026-01-03"),
            _attempt("a5", 5, "A", "2026-01-02", language="Python"),
        ]
        progress = derive_practice_progress(attempts, _catalog(), "Java", [])
        self.assertEqual([day["date"] for day in progress["days"]], ["2026-01-01", "2026-01-03"])
        self.assertEqual(progress["days"][0]["results"], {"A": 1, "B": 0, "C": 0, "D": 1, "E": 0, "F": 0})
        self.assertEqual(progress["days"][0]["minutes"], 35.5)
        self.assertEqual(progress["days"][1]["results"]["E"], 1)
        self.assertEqual(progress["basis"], "self_reported")

    def test_problem_rows_reuse_latest_valid_result_and_saved_mastery(self) -> None:
        """Report the newest A-D result per problem with saved stability.

        Inputs: Two attempts on one problem, a later skip, and one stable state.
        Outputs: One row with the newest A-D result, attempt count, and stability.
        Logic: Match topic score evidence rules without creating mastery.
        Dependencies: derive_practice_progress and synthetic catalog metadata.
        """
        attempts = [
            _attempt("p1", 1, "D", "2026-01-01"),
            _attempt("p2", 1, "A", "2026-01-02"),
            _attempt("p3", 1, "F", "2026-01-03"),
            _attempt("p4", 2, "E", "2026-01-03"),
        ]
        states = [{"problem_id": "leetcode:1", "language": "Java", "mastery_status": "stable"}]
        progress = derive_practice_progress(attempts, _catalog(), "Java", states)
        self.assertEqual(len(progress["problems"]), 1)
        row = progress["problems"][0]
        self.assertEqual((row["problem_id"], row["result"], row["practice_date"]), ("leetcode:1", "A", "2026-01-02"))
        self.assertEqual(row["attempt_count"], 3)
        self.assertTrue(row["stable"])
        self.assertEqual(row["tags"], ["secondary", "shared"])

    def test_invalid_language_is_rejected(self) -> None:
        """Reject an empty language with the shared error.

        Inputs: A blank language.
        Outputs: A validation error.
        Logic: Reuse the score language rule.
        Dependencies: derive_practice_progress and CoachError.
        """
        with self.assertRaises(CoachError):
            derive_practice_progress([], _catalog(), " ", [])


class TopicScoreServiceTests(unittest.TestCase):
    """Verify score reads against the real local SQLite authority."""

    def setUp(self) -> None:
        """Initialize a private synthetic store.

        Inputs: None.
        Outputs: A temporary directory and Coach instance.
        Logic: Avoid accessing any user training records.
        Dependencies: tempfile, pathlib, and Coach.
        """
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "private" / "coach.sqlite3"
        self.coach = Coach(self.path)
        self.coach.initialize({"language": "Java", "timezone": "UTC"})

    def tearDown(self) -> None:
        """Release synthetic storage.

        Inputs: The temporary fixture.
        Outputs: None.
        Logic: Close the authority before removing temporary files.
        Dependencies: Coach and tempfile.
        """
        self.coach.close()
        self.temp.cleanup()

    def test_score_reads_do_not_write_or_advance_state(self) -> None:
        """Keep repeated score queries read-only and version-aligned.

        Inputs: One independent report and repeated score reads.
        Outputs: Stable database contents, state version, and SQL change count.
        Logic: Compare the authority before and after derived score queries.
        Dependencies: Coach, SQLite dump and total_changes.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        self.coach.submit_feedback(item["attempt_id"], "score-read-only", 0, {"result": "A"}, occurred_at="2026-01-01T12:00:00+00:00")
        connection = self.coach._db()
        before = tuple(connection.iterdump())
        changes = connection.total_changes
        state = self.coach._state()
        first = self.coach.get_topic_scores()
        self.assertEqual(first, self.coach.get_topic_scores(" Java "))
        self.assertEqual(first["state_version"], state["state_version"])
        self.assertEqual(connection.total_changes, changes)
        self.assertEqual(tuple(connection.iterdump()), before)
        self.assertEqual(self.coach._state(), state)
        self.assertFalse(connection.in_transaction)

    def test_service_uses_current_corrections_but_keeps_actual_order(self) -> None:
        """Apply a correction without making its old practice newest.

        Inputs: An old A, a newer D, and a correction to the old report.
        Outputs: The newer D controls the score and no mastery is promoted.
        Logic: Read effective revisions while ordering by preserved practice time.
        Dependencies: Coach practice, feedback, history, and score operations.
        """
        first = self.coach.start_practice("leetcode:1", "score-first", training_date="2026-01-01")
        self.coach.submit_feedback(first["attempt_id"], "score-first-feedback", 0, {"result": "A"}, occurred_at="2026-01-01T12:00:00+00:00")
        second = self.coach.start_practice("leetcode:1", "score-second", training_date="2026-01-02")
        self.coach.submit_feedback(second["attempt_id"], "score-second-feedback", 0, {"result": "D"}, occurred_at="2026-01-02T12:00:00+00:00")
        self.coach.submit_feedback(first["attempt_id"], "score-old-correction", 1, {"result": "B"}, kind="correction")
        scores = self.coach.get_topic_scores()
        for tag in ("array", "hash-table"):
            topic = _topic(scores, tag)
            self.assertEqual(topic["score"], 0)
            self.assertEqual(topic["problem_count"], 1)
            self.assertEqual(topic["stable_count"], 0)
            self.assertEqual(topic["results"], {"A": 0, "B": 0, "C": 0, "D": 1})

    def test_correction_to_skip_does_not_resurrect_superseded_result(self) -> None:
        """Ignore superseded revisions of the same practice attempt.

        Inputs: An A report corrected to F with no other valid practice.
        Outputs: No valid problem evidence for its topics.
        Logic: An ignored current outcome cannot restore a retracted older revision.
        Dependencies: Coach effective feedback snapshots and score derivation.
        """
        attempt = self.coach.start_practice("leetcode:1", "score-retracted", training_date="2026-01-01")
        self.coach.submit_feedback(attempt["attempt_id"], "score-retracted-a", 0, {"result": "A"}, occurred_at="2026-01-01T12:00:00+00:00")
        self.coach.submit_feedback(attempt["attempt_id"], "score-retracted-f", 1, {"result": "F"}, kind="correction")
        topic = _topic(self.coach.get_topic_scores(), "array")
        self.assertIsNone(topic["score"])
        self.assertEqual(topic["problem_count"], 0)

    def test_progress_reads_do_not_write_and_match_scores(self) -> None:
        """Keep progress reads read-only and consistent with topic scores.

        Inputs: One independent report and a progress read.
        Outputs: Unchanged storage and one matching problem row.
        Logic: Compare the authority before and after the derived query.
        Dependencies: Coach.get_practice_progress and SQLite dump.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        self.coach.submit_feedback(item["attempt_id"], "progress-read-only", 0, {"result": "A", "elapsed_minutes": 12}, occurred_at="2026-01-01T12:00:00+00:00")
        connection = self.coach._db()
        before = tuple(connection.iterdump())
        progress = self.coach.get_practice_progress()
        self.assertEqual(tuple(connection.iterdump()), before)
        self.assertFalse(connection.in_transaction)
        self.assertEqual(progress["state_version"], self.coach._state()["state_version"])
        self.assertEqual(progress["days"], [{"date": "2026-01-01", "results": {"A": 1, "B": 0, "C": 0, "D": 0, "E": 0, "F": 0}, "minutes": 12}])
        self.assertEqual([row["problem_id"] for row in progress["problems"]], [item["problem"]["id"]])

    def test_default_language_and_invalid_overrides(self) -> None:
        """Use saved defaults and validate optional language overrides.

        Inputs: The default language, a valid override, and invalid values.
        Outputs: Normalized languages or shared validation errors.
        Logic: Reuse core language rules without updating configuration.
        Dependencies: Coach.get_topic_scores and CoachError.
        """
        self.assertEqual(self.coach.get_topic_scores()["language"], "Java")
        self.assertEqual(self.coach.get_topic_scores("Python")["language"], "Python")
        for language in ("", " ", True, 123):
            with self.subTest(language=language):
                with self.assertRaises(CoachError) as caught:
                    self.coach.get_topic_scores(language)
                self.assertEqual(caught.exception.code, "validation_error")
                self.assertFalse(self.coach._db().in_transaction)
        self.assertEqual(self.coach.get_config()["config"]["language"], "Java")


if __name__ == "__main__":
    unittest.main()
