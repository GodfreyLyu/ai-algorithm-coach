"""Test daily run time descriptions and host-rule checks with fixed synthetic clocks."""

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algorithm_coach.errors import CoachError
from algorithm_coach.core.schedule import check_schedule, describe_schedule
from algorithm_coach.service import Coach

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


class ScheduleRuleTests(unittest.TestCase):
    """Verify pure schedule calculations."""

    def test_tokyo_change_to_nine(self) -> None:
        """Describe a 09:00 Tokyo trigger and its next run.

        Inputs: A fixed clock after today's Tokyo run.
        Outputs: Daily expressions and the next local and UTC instants.
        Logic: The training date is the local date of the run.
        Dependencies: describe_schedule.
        """
        result = describe_schedule("09:00", "Asia/Tokyo", NOW)
        self.assertEqual(result["rrule"], "FREQ=DAILY;BYHOUR=9;BYMINUTE=0")
        self.assertEqual(result["cron"], "0 9 * * *")
        self.assertEqual(result["next_runs"][0], {"local": "2026-11-21T09:00:00+09:00", "utc": "2026-11-21T00:00:00+00:00", "training_date": "2026-11-21"})
        self.assertEqual(result["warnings"], [])
        self.assertFalse(result["scheduler_control"])

    def test_unset_time_leaves_the_host_in_charge(self) -> None:
        """Report that no preferred time is saved.

        Inputs: A null run_time.
        Outputs: configured false and no expressions.
        Logic: The default is not a hidden schedule.
        Dependencies: describe_schedule.
        """
        result = describe_schedule(None, "UTC", NOW)
        self.assertFalse(result["configured"])
        self.assertNotIn("rrule", result)

    def test_daylight_saving_gap_and_fold(self) -> None:
        """Shift a missing local time and flag a repeated one.

        Inputs: New York times inside the spring gap and the autumn fold.
        Outputs: dst_gap and dst_fold adjustments and warnings.
        Logic: Missing times move forward; repeated times use the first instance.
        Dependencies: describe_schedule.
        """
        spring = describe_schedule("02:30", "America/New_York", datetime(2026, 3, 7, 12, tzinfo=timezone.utc))
        self.assertEqual(spring["next_runs"][0]["local"], "2026-03-08T03:30:00-04:00")
        self.assertEqual(spring["next_runs"][0]["adjustment"], "dst_gap")
        self.assertEqual(spring["warnings"][0]["code"], "dst_affected_dates")
        autumn = describe_schedule("01:30", "America/New_York", datetime(2026, 10, 31, 12, tzinfo=timezone.utc))
        self.assertEqual(autumn["next_runs"][0]["local"], "2026-11-01T01:30:00-04:00")
        self.assertEqual(autumn["next_runs"][0]["adjustment"], "dst_fold")

    def test_near_midnight_warning(self) -> None:
        """Warn when a run may cross into the next local date.

        Inputs: A 23:45 run time.
        Outputs: A near_midnight warning.
        Logic: Training dates use the execution time, so late runs are risky.
        Dependencies: describe_schedule.
        """
        codes = [item["code"] for item in describe_schedule("23:45", "Asia/Tokyo", NOW)["warnings"]]
        self.assertEqual(codes, ["near_midnight"])

    def test_check_reports_time_rule_and_timezone_differences(self) -> None:
        """Compare observed host rules with the saved setting.

        Inputs: Matching, stale, weekly, and other-timezone host rules.
        Outputs: Matching or explicit differences with converted next runs.
        Logic: A check reports what is in effect without changing the host.
        Dependencies: check_schedule.
        """
        self.assertTrue(check_schedule("09:00", "Asia/Tokyo", NOW, observed_rrule="FREQ=DAILY;BYHOUR=9;BYMINUTE=0;BYSECOND=0")["match"])
        stale = check_schedule("09:00", "Asia/Tokyo", NOW, observed_rrule="FREQ=DAILY;BYHOUR=8;BYMINUTE=30")
        self.assertEqual(stale["differences"], [{"field": "run_time", "observed": "08:30", "expected": "09:00"}])
        weekly = check_schedule("09:00", "Asia/Tokyo", NOW, observed_rrule="FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0")
        self.assertEqual({item["field"] for item in weekly["differences"]}, {"frequency", "rule_parts"})
        moved = check_schedule("09:00", "Asia/Tokyo", NOW, observed_cron="0 9 * * *", observed_timezone="America/Los_Angeles")
        self.assertEqual(moved["differences"][0]["code"], "timezone_mismatch")
        self.assertEqual(moved["observed_next_runs"][0]["workspace_local"], "2026-11-21T02:00:00+09:00")

    def test_invalid_observed_values_are_rejected(self) -> None:
        """Reject ambiguous or malformed observed host rules.

        Inputs: Missing, duplicated, unfixed, and bad-timezone observations.
        Outputs: Validation errors.
        Logic: The checker never guesses a host setting.
        Dependencies: check_schedule.
        """
        for arguments in ({}, {"observed_rrule": "FREQ=DAILY;BYHOUR=9", "observed_cron": "0 9 * * *"},
                          {"observed_cron": "*/5 * * * *"}, {"observed_rrule": "FREQ=DAILY;BYHOUR=9", "observed_timezone": "JST"}):
            with self.subTest(arguments=arguments), self.assertRaises(CoachError):
                check_schedule("09:00", "Asia/Tokyo", NOW, **arguments)


class ScheduleServiceTests(unittest.TestCase):
    """Verify the read-only schedule service on a temporary store."""

    def test_schedule_status_is_read_only_and_identifies_the_workspace(self) -> None:
        """Describe the saved run time without changing configuration.

        Inputs: A temporary workspace with a 09:00 run time.
        Outputs: Schedule data with the workspace identity and an unchanged revision.
        Logic: Hosts match their task by workspace identity, not by time.
        Dependencies: Coach and tempfile.
        """
        with tempfile.TemporaryDirectory() as temp:
            coach = Coach(Path(temp) / "coach.sqlite3")
            try:
                coach.initialize({"timezone": "Asia/Tokyo", "run_time": "09:00"})
                revision = coach.get_config()["revision"]
                status = coach.schedule_status()
                self.assertEqual(status["workspace_id"], coach.get_workspace_identity()["workspace_id"])
                self.assertEqual(status["config_revision"], revision)
                self.assertEqual(coach.get_config()["revision"], revision)
                with self.assertRaises(CoachError):
                    coach.schedule_status(observed_timezone="Asia/Tokyo")
            finally:
                coach.close()


if __name__ == "__main__":
    unittest.main()
