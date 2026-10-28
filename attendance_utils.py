"""Deterministic KST attendance calculations for routine verification logs."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from math import ceil
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
ATTENDANCE_START_DATE = date(2026, 7, 20)
ATTENDANCE_START_YEAR = 2026
ATTENDANCE_START_WEEK = 30
ATTENDANCE_2026_DENOMINATOR = 23
STANDARD_YEAR_DENOMINATOR = 52
ATTENDANCE_TARGET_RATE = 0.8


@dataclass(frozen=True)
class AnnualAttendanceSummary:
    year: int
    denominator: int
    attended_weeks: int
    rate_percent: float
    target_weeks: int
    weeks_to_target: int


@dataclass(frozen=True)
class CurrentAttendanceSnapshot:
    annual: AnnualAttendanceSummary
    week: int
    current_week_attended: bool
    is_exception_week: bool
    remaining_attendance_weeks: int
    target_reachable: bool


def _as_kst_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=KST).date()
        return value.astimezone(KST).date()
    return value


def parse_kst_datetime(value) -> datetime | None:
    """Parse stored log timestamps as KST without relying on Sheets formulas."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=KST)
        return value.astimezone(KST)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=KST)

    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def attendance_week_key(value: date | datetime) -> tuple[int, int]:
    iso = _as_kst_date(value).isocalendar()
    return int(iso.year), int(iso.week)


def attendance_week_id(year: int, week: int) -> str:
    return f"{year}-W{week:02d}"


def parse_attendance_week_id(value: str) -> tuple[int, int]:
    try:
        year_text, week_text = str(value).strip().split("-W", maxsplit=1)
        year = int(year_text)
        week = int(week_text)
        date.fromisocalendar(year, week, 1)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid ISO week ID: {value!r}") from error
    return year, week


def is_recorded_attendance_week(year: int, week: int) -> bool:
    """Return whether a week belongs to the attendance program history."""
    if year < ATTENDANCE_START_YEAR or not 1 <= week <= 53:
        return False
    if year == ATTENDANCE_START_YEAR:
        return week >= ATTENDANCE_START_WEEK
    return True


def is_exception_attendance_week(year: int, week: int) -> bool:
    """ISO week 53 is recorded but never changes an annual 52-week denominator."""
    return is_recorded_attendance_week(year, week) and week == 53


def is_scoring_attendance_week(year: int, week: int) -> bool:
    """Return whether a week contributes to the annual attendance percentage."""
    if not is_recorded_attendance_week(year, week) or week == 53:
        return False
    if year == ATTENDANCE_START_YEAR:
        return ATTENDANCE_START_WEEK <= week <= 52
    return 1 <= week <= STANDARD_YEAR_DENOMINATOR


def attendance_denominator(year: int) -> int:
    if year == ATTENDANCE_START_YEAR:
        return ATTENDANCE_2026_DENOMINATOR
    if year > ATTENDANCE_START_YEAR:
        return STANDARD_YEAR_DENOMINATOR
    return 0


def scoring_weeks_for_year(year: int) -> range:
    if year == ATTENDANCE_START_YEAR:
        return range(ATTENDANCE_START_WEEK, 53)
    if year > ATTENDANCE_START_YEAR:
        return range(1, STANDARD_YEAR_DENOMINATOR + 1)
    return range(0)


def annual_attendance_summary(attended_week_keys, year: int) -> AnnualAttendanceSummary:
    """Calculate one member's annual attendance without Sheets formulas."""
    denominator = attendance_denominator(year)
    if denominator <= 0:
        raise ValueError(f"Attendance tracking has not started for year {year}")

    attended = set(attended_week_keys or ())
    attended_weeks = sum((year, week) in attended for week in scoring_weeks_for_year(year))
    target_weeks = ceil(denominator * ATTENDANCE_TARGET_RATE)
    return AnnualAttendanceSummary(
        year=year,
        denominator=denominator,
        attended_weeks=attended_weeks,
        rate_percent=round(attended_weeks * 100 / denominator, 1),
        target_weeks=target_weeks,
        weeks_to_target=max(0, target_weeks - attended_weeks),
    )


def remaining_scoring_week_slots(attended_week_keys, reference: date | datetime) -> int:
    """Count still-available, not-yet-attended scoring weeks in the current ISO year."""
    current_date = _as_kst_date(reference)
    if current_date < ATTENDANCE_START_DATE:
        return 0
    year, current_week = attendance_week_key(current_date)
    attended = set(attended_week_keys or ())
    return sum(
        (year, week) not in attended
        for week in scoring_weeks_for_year(year)
        if week >= current_week
    )


def current_attendance_snapshot(
    attended_week_keys,
    reference: date | datetime,
) -> CurrentAttendanceSnapshot | None:
    """Build the attendance state shown in a member's daily reminder."""
    current_date = _as_kst_date(reference)
    if current_date < ATTENDANCE_START_DATE:
        return None

    year, week = attendance_week_key(current_date)
    if not is_recorded_attendance_week(year, week):
        return None

    attended = set(attended_week_keys or ())
    annual = annual_attendance_summary(attended, year)
    remaining = remaining_scoring_week_slots(attended, current_date)
    return CurrentAttendanceSnapshot(
        annual=annual,
        week=week,
        current_week_attended=(year, week) in attended,
        is_exception_week=is_exception_attendance_week(year, week),
        remaining_attendance_weeks=remaining,
        target_reachable=(annual.weeks_to_target == 0 or annual.weeks_to_target <= remaining),
    )


def collect_successful_attendance_weeks(log_records) -> dict[str, set[tuple[int, int]]]:
    """Return one attended-week key per member from successful routine logs."""
    weeks_by_user: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for row in (log_records or [])[1:]:
        if len(row) < 5 or str(row[4]).strip().lower() != "success":
            continue
        user_id = str(row[2]).strip()
        logged_at = parse_kst_datetime(row[3])
        if not user_id or logged_at is None or logged_at.date() < ATTENDANCE_START_DATE:
            continue
        year, week = attendance_week_key(logged_at)
        if is_recorded_attendance_week(year, week):
            weeks_by_user[user_id].add((year, week))
    return dict(weeks_by_user)
