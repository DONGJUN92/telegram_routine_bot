import unittest
from datetime import date, datetime

from attendance_utils import (
    ATTENDANCE_START_DATE,
    annual_attendance_summary,
    collect_successful_attendance_weeks,
    current_attendance_snapshot,
    is_exception_attendance_week,
    is_scoring_attendance_week,
    parse_attendance_week_id,
)


class AttendanceUtilsTests(unittest.TestCase):
    def test_2026_start_week_and_eighty_percent_target(self):
        snapshot = current_attendance_snapshot(
            {(2026, 30)},
            date(2026, 7, 20),
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.annual.denominator, 23)
        self.assertEqual(snapshot.annual.attended_weeks, 1)
        self.assertEqual(snapshot.annual.rate_percent, 4.3)
        self.assertEqual(snapshot.annual.target_weeks, 19)
        self.assertEqual(snapshot.annual.weeks_to_target, 18)
        self.assertTrue(snapshot.current_week_attended)

    def test_multiple_successful_certifications_only_count_once_per_week(self):
        rows = [
            ["log_id", "routine_id", "user_id", "timestamp", "status"],
            ["0", "r1", "u1", "2026-07-19 23:59:00", "success"],
            ["1", "r1", "u1", "2026-07-20 08:00:00", "success"],
            ["2", "r2", "u1", "2026-07-26 22:00:00", "success"],
            ["3", "r1", "u1", "2026-07-21 08:00:00", "failed"],
        ]

        weeks = collect_successful_attendance_weeks(rows)
        summary = annual_attendance_summary(weeks["u1"], 2026)
        self.assertEqual(weeks["u1"], {(2026, 30)})
        self.assertEqual(summary.attended_weeks, 1)

    def test_2026_example_rate_and_weeks_needed_for_eighty_percent(self):
        summary = annual_attendance_summary(
            {(2026, week) for week in range(30, 38)},
            2026,
        )

        self.assertEqual(summary.attended_weeks, 8)
        self.assertEqual(summary.rate_percent, 34.8)
        self.assertEqual(summary.weeks_to_target, 11)

    def test_2026_week_53_is_recorded_but_excluded_from_annual_rate(self):
        weeks = {(2026, 30), (2026, 53)}
        summary = annual_attendance_summary(weeks, 2026)
        snapshot = current_attendance_snapshot(
            weeks,
            datetime(2026, 12, 30, 21, 0),
        )

        self.assertTrue(is_exception_attendance_week(2026, 53))
        self.assertFalse(is_scoring_attendance_week(2026, 53))
        self.assertEqual(summary.attended_weeks, 1)
        self.assertEqual(summary.rate_percent, 4.3)
        self.assertTrue(snapshot.is_exception_week)

    def test_2027_and_later_use_52_week_denominator(self):
        for year in (2027, 2028):
            with self.subTest(year=year):
                summary = annual_attendance_summary({(year, 1)}, year)
                self.assertEqual(summary.denominator, 52)
                self.assertEqual(summary.attended_weeks, 1)
                self.assertEqual(summary.rate_percent, 1.9)
                self.assertEqual(summary.target_weeks, 42)
                self.assertEqual(summary.weeks_to_target, 41)

    def test_before_start_date_has_no_reminder_snapshot(self):
        self.assertEqual(ATTENDANCE_START_DATE, date(2026, 7, 20))
        self.assertIsNone(current_attendance_snapshot(set(), date(2026, 7, 19)))

    def test_invalid_iso_week_is_rejected(self):
        for value in ("2026-W00", "2026-W54", "not-a-week"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_attendance_week_id(value)


if __name__ == "__main__":
    unittest.main()
