"""Scheduled personal messages and monthly owner briefing delivered by the main bot."""

import asyncio
import calendar
import logging
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from telegram.ext import ContextTypes

from attendance_utils import (
    collect_successful_attendance_weeks,
    current_attendance_snapshot,
    parse_kst_datetime,
)
from ai_utils import generate_card_routine_summary, generate_weekly_insight_briefing
from card_news import format_routine_title, generate_card_news
from db_utils import (
    async_get_all_values,
    insights_sheet,
    logs_sheet,
    users_sheet,
)
from notification_utils import (
    _private_user_id,
    _send_with_retry,
    _trim_message,
    get_personal_dm_recipients,
    send_media_group_notifications,
    send_text_notifications,
)


LOGGER = logging.getLogger("routine_bot.notifications")
KST = ZoneInfo("Asia/Seoul")
DEFAULT_OWNER_USER_ID = "1415330667"
_WEEKLY_CARD_LOCK = asyncio.Lock()


def get_owner_user_id() -> str:
    configured = os.environ.get("OWNER_USER_ID", DEFAULT_OWNER_USER_ID).strip()
    return _private_user_id(configured) or DEFAULT_OWNER_USER_ID


def _week_start(now: datetime | None = None) -> datetime:
    current = now or datetime.now(KST)
    return (current - timedelta(days=current.weekday())).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def _weekly_deadline_alert(now: datetime | None = None) -> str:
    current = now or datetime.now(KST)
    week_end = (_week_start(current) + timedelta(days=6)).replace(
        hour=23,
        minute=59,
        second=0,
        microsecond=0,
    )
    remaining = week_end - current
    if remaining.total_seconds() <= 0:
        return "이번 주 인증 마감이 지났습니다. 다음 주 루틴도 함께 이어가요."

    total_hours = int(remaining.total_seconds() // 3600)
    days, hours = divmod(total_hours, 24)
    remaining_text = f"{days}일 {hours}시간" if days else f"{hours}시간"
    return f"이번 주 인증 마감까지 {remaining_text} 남았습니다 (일요일 23:59)."


def _is_success(row) -> bool:
    return len(row) >= 5 and str(row[4]).strip().lower() == "success"


def _log_datetime(row):
    if len(row) < 4:
        return None
    return parse_kst_datetime(row[3])


def _nickname_map(users_records) -> dict[str, str]:
    return {
        str(row[0]).strip(): (str(row[1]).strip() or "회원")
        for row in (users_records or [])[1:]
        if len(row) >= 2 and row[0]
    }


def _registered_members(users_records) -> list[tuple[str, str]]:
    """Return deduplicated (user_id, nickname) pairs from the Users sheet."""
    members = []
    seen = set()
    for row in (users_records or [])[1:]:
        if not row:
            continue
        user_id = _private_user_id(row[0])
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        nickname = (str(row[1]).strip() if len(row) > 1 and row[1] else "") or f"회원({user_id[-4:]})"
        members.append((user_id, nickname))
    return members


def _attendance_reminder_text(user_id: str, attendance_weeks, now: datetime) -> str:
    """Build the annual attendance block appended to the nightly personal DM."""
    snapshot = current_attendance_snapshot(attendance_weeks.get(user_id, set()), now)
    if snapshot is None:
        return ""

    annual = snapshot.annual
    if snapshot.is_exception_week:
        return (
            f"📅 {annual.year}년 53주차는 연말 예외 주차입니다.\n"
            f"이번 주 인증은 기록되지만, {annual.year}년 누적 출석률과 "
            "80% 목표 계산에는 반영되지 않습니다."
        )

    lines = [
        f"📅 {annual.year}년 출석 현황",
        "이번 주: 출석 완료 (100%)" if snapshot.current_week_attended else "이번 주: 아직 미인증",
        f"올해 누적: {annual.rate_percent:.1f}% ({annual.attended_weeks}/{annual.denominator}주)",
    ]
    if annual.weeks_to_target == 0:
        lines.append(f"🎉 {annual.year}년 출석률 80% 기준을 달성했어요.")
    elif snapshot.target_reachable:
        lines.append(
            f"🎯 80% 기준까지 서로 다른 {annual.weeks_to_target}주에 "
            "1회 이상 인증이 더 필요해요."
        )
    else:
        lines.append(
            f"🎯 80% 기준까지 서로 다른 {annual.weeks_to_target}주에 "
            "1회 이상 인증이 더 필요해요."
        )
        lines.append(
            f"올해 남은 출석 가능 주차는 {snapshot.remaining_attendance_weeks}주입니다."
        )
    if not snapshot.current_week_attended:
        lines.append("오늘 인증하면 이번 주 출석이 100%로 기록됩니다.")
    return "\n".join(lines)


def _sanitize_briefing_text(text: str) -> str:
    if not text:
        return ""

    cleaned_lines = []
    previous_blank = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if cleaned_lines and not previous_blank:
                cleaned_lines.append("")
                previous_blank = True
            continue
        if stripped.startswith("```"):
            continue
        cleaned_lines.append(stripped.lstrip("#").strip())
        previous_blank = False
    return "\n".join(cleaned_lines).strip()


async def _daily_recipients(label: str):
    recipients = await get_personal_dm_recipients()
    if not recipients:
        LOGGER.info("Skipped %s: no registered direct-message recipients", label)
    return recipients


async def _weekly_recipients(label: str):
    recipients = await get_personal_dm_recipients()
    if not recipients:
        LOGGER.info("Skipped %s: no registered direct-message recipients", label)
    return recipients


async def morning_notification_job(context: ContextTypes.DEFAULT_TYPE):
    """Send a personalized morning prompt that nudges uncertified members."""
    try:
        recipients = await _daily_recipients("morning notification")
        if not recipients:
            return 0

        now = datetime.now(KST)
        week_start = _week_start(now)
        logs_records = await async_get_all_values(logs_sheet)
        weekly_counts = defaultdict(int)
        for row in (logs_records or [])[1:]:
            if not _is_success(row):
                continue
            log_time = _log_datetime(row)
            if log_time is not None and log_time >= week_start:
                weekly_counts[str(row[2]).strip()] += 1

        def make_message(recipient):
            user_id = recipient["user_id"]
            if weekly_counts[user_id] > 0:
                status_nudge = (
                    f"✅ 이번 주 벌써 {weekly_counts[user_id]}회 인증으로 주간 출석(100%)을 달성하셨네요!\n"
                    "오늘도 가벼운 루틴 하나로 기분 좋은 흐름을 이어가 보세요."
                )
            else:
                status_nudge = (
                    "🎯 이번 주 아직 첫 인증 전이시네요!\n"
                    "주 1회만 인증해도 이번 주 출석률 100%가 바로 인정됩니다.\n"
                    "오늘 사진+캡션이나 `/reg 오늘 실천할 루틴` 한 줄로 가볍게 출석을 챙겨보세요!"
                )
            return (
                "🌅 굿모닝! 산스 AI루틴클럽원분들 오늘도 파이팅입니다! 💪\n\n"
                "하루의 시작을 루틴과 함께하면 달라집니다.\n"
                f"{status_nudge}\n\n"
                "📸 사진+캡션 또는 `/reg [인증 내용]`으로 10초 만에 간편 인증할 수 있습니다!"
            )

        return await send_text_notifications(
            context,
            make_message,
            label="morning notification",
            recipients=recipients,
        )
    except Exception as error:
        LOGGER.error(
            "Morning personal notification failed",
            exc_info=(type(error), error, error.__traceback__),
        )
        return 0


async def daily_dashboard_notification_job(context: ContextTypes.DEFAULT_TYPE):
    """Build a private progress dashboard with social proof to boost certification rate."""
    try:
        recipients = await _daily_recipients("daily dashboard")
        if not recipients:
            return 0

        now = datetime.now(KST)
        week_start = _week_start(now)
        logs_records = await async_get_all_values(logs_sheet)
        users_records = await async_get_all_values(users_sheet)

        today_counts = defaultdict(int)
        weekly_counts = defaultdict(int)
        today_routines = defaultdict(list)
        weekly_active_users = set()

        for row in logs_records[1:]:
            if not _is_success(row):
                continue
            log_time = _log_datetime(row)
            if log_time is None:
                continue
            user_id = str(row[2]).strip()
            raw_title = (
                str(row[8]).strip()
                if len(row) > 8 and row[8]
                else (str(row[6]).strip() if len(row) > 6 and row[6] else "루틴")
            )
            routine_title = format_routine_title(raw_title, max_chars=25)
            if log_time.date() == now.date():
                today_counts[user_id] += 1
                if routine_title not in today_routines[user_id]:
                    today_routines[user_id].append(routine_title)
            if log_time >= week_start:
                weekly_counts[user_id] += 1
                weekly_active_users.add(user_id)

        nicknames = _nickname_map(users_records)
        active_member_count = len(weekly_active_users)

        def make_message(recipient):
            user_id = recipient["user_id"]
            nickname = nicknames.get(user_id, "회원")
            today_names = ", ".join(today_routines.get(user_id, [])[:3])
            progress_line = (
                f"오늘 인증 내용: {today_names}"
                if today_names
                else "오늘 인증 기록이 아직 없습니다."
            )
            week_status = "출석 달성 (100%)" if weekly_counts[user_id] > 0 else "아직 미인증"
            social_line = (
                f"🔥 이번 주 현재 {active_member_count}명의 클럽원이 출석을 완료했습니다!"
                if active_member_count > 0
                else "🌱 이번 주 첫 출석의 주인공이 되어보세요!"
            )

            if today_counts[user_id]:
                action_line = (
                    "오늘 기록을 잘 남기고 계세요. 남은 하루도 가볍게 이어가 봐요!\n\n"
                    "📸 사진+캡션 또는 /reg 로 언제든 추가 인증이 가능합니다."
                )
            elif weekly_counts[user_id] == 0:
                action_line = (
                    "⚡ 이번 주 아직 인증 기록이 없어요! 지금 딱 1번만 인증해도 이번 주 출석 100%가 달성됩니다.\n"
                    "사진 촬영이 번거롭다면 지금 바로 텍스트 한 줄로 인증해 보세요:\n"
                    "👉 `/reg 오늘 루틴 실천 완료`"
                )
            else:
                action_line = (
                    "🌅 퇴근/저녁 시간이 되었습니다! 오늘 실천한 루틴이 있다면 "
                    "지금 바로 1:1 대화방에서 가볍게 기록해 보세요! 🙌\n\n"
                    "📸 사진+캡션 또는 `/reg [내용]`으로 간편하게 인증할 수 있습니다! ✨"
                )

            return (
                f"📊 {nickname}님의 오늘 루틴 현황\n\n"
                f"오늘 인증: {today_counts[user_id]}건\n"
                f"이번 주 인증: {weekly_counts[user_id]}건 ({week_status})\n"
                f"{progress_line}\n\n"
                f"{social_line}\n"
                f"{_weekly_deadline_alert(now)}\n\n"
                f"{action_line}"
            )

        return await send_text_notifications(
            context,
            make_message,
            label="daily dashboard",
            recipients=recipients,
        )
    except Exception as error:
        LOGGER.error(
            "Daily personal dashboard failed",
            exc_info=(type(error), error, error.__traceback__),
        )
        return 0


async def evening_reminder_notification_job(context: ContextTypes.DEFAULT_TYPE):
    """Send a personalized end-of-day reminder to registered main-bot members."""
    try:
        recipients = await _daily_recipients("evening reminder")
        if not recipients:
            return 0

        now = datetime.now(KST)
        today = now.date()
        logs_records = await async_get_all_values(logs_sheet)
        attendance_weeks = collect_successful_attendance_weeks(logs_records)
        today_counts = defaultdict(int)
        for row in logs_records[1:]:
            if not _is_success(row):
                continue
            log_time = _log_datetime(row)
            if log_time and log_time.date() == today:
                today_counts[str(row[2]).strip()] += 1

        def make_message(recipient):
            user_id = recipient["user_id"]
            count = today_counts[user_id]
            attendance_text = _attendance_reminder_text(
                user_id,
                attendance_weeks,
                now,
            )
            reminder = (
                "🌙 오늘 하루도 정말 고생 많으셨어요!\n\n"
                "오늘 루틴 인증을 마감하기까지 얼마 남지 않았습니다. 🙌\n"
                "하루를 정리하며 딱 5분이라도 내 자신과의 약속을 지켜보는 것은 어떨까요?\n\n"
                "📸 사진+캡션 또는 `/reg [오늘 한 루틴]` 한 줄로 지금 바로 간편하게 기록을 남겨보세요! ✨"
            )
            if count:
                message = (
                    f"{reminder}\n\n"
                    f"오늘 {count}건의 루틴 인증을 남기셨네요. 하루 마무리도 정말 좋습니다.\n"
                    "남은 루틴이 있다면 지금 한 번 더 기록해 보세요."
                )
            else:
                message = reminder
            return f"{message}\n\n{attendance_text}" if attendance_text else message

        return await send_text_notifications(
            context,
            make_message,
            label="evening reminder",
            recipients=recipients,
        )
    except Exception as error:
        LOGGER.error(
            "Evening personal reminder failed",
            exc_info=(type(error), error, error.__traceback__),
        )
        return 0


async def weekly_top_notification_job(context: ContextTypes.DEFAULT_TYPE):
    """Deliver the weekly TOP 3 report to each main-bot personal chat."""
    try:
        recipients = await _weekly_recipients("weekly TOP 3")
        if not recipients:
            return 0

        week_start = _week_start()
        logs_records = await async_get_all_values(logs_sheet)
        users_records = await async_get_all_values(users_sheet)
        week_counts = defaultdict(int)
        week_routines = defaultdict(list)

        for row in logs_records[1:]:
            if not _is_success(row):
                continue
            log_time = _log_datetime(row)
            if log_time is None or log_time < week_start:
                continue
            user_id = str(row[2]).strip()
            week_counts[user_id] += 1
            raw_title = (
                str(row[8]).strip()
                if len(row) > 8 and row[8]
                else (str(row[6]).strip() if len(row) > 6 and row[6] else "")
            )
            if raw_title:
                short_title = format_routine_title(raw_title, max_chars=24)
                if short_title not in week_routines[user_id]:
                    week_routines[user_id].append(short_title)

        if not week_counts:
            LOGGER.info("Skipped weekly TOP 3: no successful verification this week")
            return 0

        nicknames = _nickname_map(users_records)
        ranked = sorted(week_counts.items(), key=lambda item: (-item[1], item[0]))
        ranks = {user_id: rank for rank, (user_id, _) in enumerate(ranked, start=1)}
        medals = ("1위", "2위", "3위")
        leaderboard_lines = []
        for index, (user_id, count) in enumerate(ranked[:3]):
            routine_names = ", ".join(week_routines[user_id][:3]) or "기록 없음"
            leaderboard_lines.append(
                f"{medals[index]} {nicknames.get(user_id, '회원')} - {count}회 인증\n"
                f"   루틴: {routine_names}"
            )
        leaderboard = "\n".join(leaderboard_lines)
        total_auths = sum(week_counts.values())

        def make_message(recipient):
            user_id = recipient["user_id"]
            if user_id in ranks:
                personal_line = (
                    f"나의 이번 주 기록: {week_counts[user_id]}회 인증, "
                    f"현재 {ranks[user_id]}위"
                )
            else:
                personal_line = "나의 이번 주 인증 기록은 아직 없습니다."
            return (
                "이번 주 루틴 TOP 3\n\n"
                f"{leaderboard}\n\n"
                f"이번 주 전체 인증: {total_auths}건\n"
                f"{personal_line}\n\n"
                "한 주 동안 정말 수고 많으셨습니다."
            )

        return await send_text_notifications(
            context,
            make_message,
            label="weekly TOP 3",
            recipients=recipients,
        )
    except Exception as error:
        LOGGER.error(
            "Weekly personal TOP 3 failed",
            exc_info=(type(error), error, error.__traceback__),
        )
        return 0


async def weekly_card_news_notification_job(context: ContextTypes.DEFAULT_TYPE):
    """Generate card news once, then deliver fresh uploads to each private DM."""
    if _WEEKLY_CARD_LOCK.locked():
        LOGGER.warning("Skipped weekly card news because another run is still active")
        return False

    async with _WEEKLY_CARD_LOCK:
        try:
            recipients = await _weekly_recipients("weekly card news")
            if not recipients:
                return False

            week_start = _week_start()
            logs_records = await async_get_all_values(logs_sheet)
            users_records = await async_get_all_values(users_sheet)
            nicknames = _nickname_map(users_records)
            user_stats = {}
            week_user_ids = set()
            total_auths = 0

            for row in logs_records[1:]:
                if not _is_success(row):
                    continue
                log_time = _log_datetime(row)
                if log_time is None or log_time < week_start:
                    continue
                user_id = str(row[2]).strip()
                raw_name = (
                    str(row[8]).strip()
                    if len(row) > 8 and row[8]
                    else (str(row[6]).strip() if len(row) > 6 and row[6] else "루틴")
                )
                routine_title = format_routine_title(raw_name, max_chars=28)
                caption = str(row[6]).strip() if len(row) > 6 and row[6] else raw_name
                image_url = str(row[5]).strip() if len(row) > 5 and row[5] else ""
                stats = user_stats.setdefault(
                    user_id,
                    {"routine_name": routine_title, "count": 0, "captions": [], "certs": []},
                )
                stats["count"] += 1
                stats["routine_name"] = routine_title
                if caption and caption != "내용 없음":
                    stats["captions"].append(caption)
                stats["certs"].append({"caption": caption, "image_url": image_url})
                week_user_ids.add(user_id)
                total_auths += 1

            if not user_stats:
                LOGGER.info("Skipped weekly card news: no successful verification this week")
                return False

            scored = []
            for user_id, stats in user_stats.items():
                scored.append(
                    {
                        "user_id": user_id,
                        "routine_name": stats["routine_name"],
                        "count": stats["count"],
                        "captions": stats["captions"],
                        "certs": stats["certs"],
                        "score": stats["count"] * 2 + len(stats["captions"]),
                    }
                )
            scored.sort(key=lambda item: (-item["score"], item["user_id"], item["routine_name"]))

            selected = scored[:4]

            top_routines = []
            for item in selected:
                nickname = nicknames.get(item["user_id"], "회원")
                try:
                    summary = await generate_card_routine_summary(
                        nickname,
                        item["routine_name"],
                        item["certs"],
                    )
                except Exception as error:
                    LOGGER.warning(
                        "Card-news AI summary failed for routine=%s: %s",
                        item["routine_name"],
                        error,
                    )
                    summary = "이번 주에도 꾸준히 루틴을 실천했습니다."
                top_routines.append(
                    {
                        "nickname": nickname,
                        "routine_name": item["routine_name"],
                        "summary": summary or "이번 주에도 꾸준히 루틴을 실천했습니다.",
                        "auth_count": item["count"],
                    }
                )

            card_images = await asyncio.to_thread(
                generate_card_news,
                top_routines,
                total_auths,
                len(week_user_ids),
            )
            delivered = await send_media_group_notifications(
                context,
                card_images,
                caption="산스 AI루틴클럽 주간 카드뉴스",
                label="weekly card news",
                recipients=recipients,
            )
            return delivered > 0
        except Exception as error:
            LOGGER.error(
                "Weekly personal card-news generation or delivery failed",
                exc_info=(type(error), error, error.__traceback__),
            )
            return False


async def weekly_insight_briefing_notification_job(context: ContextTypes.DEFAULT_TYPE):
    """Generate the weekly AI insight briefing once and deliver it by personal DM."""
    try:
        recipients = await _weekly_recipients("weekly insight briefing")
        if not recipients:
            return 0

        week_start = _week_start()
        insights_records = await async_get_all_values(insights_sheet)
        users_records = await async_get_all_values(users_sheet)
        nicknames = _nickname_map(users_records)
        collected = []

        for row in insights_records[1:]:
            if len(row) < 4:
                continue
            try:
                insight_time = datetime.strptime(
                    str(row[2])[:19],
                    "%Y-%m-%d %H:%M:%S",
                ).replace(tzinfo=KST)
            except ValueError:
                continue
            if insight_time < week_start:
                continue

            content = str(row[3]).strip()
            if not content:
                continue
            user_id = str(row[1]).strip()
            clipped_content = content if len(content) <= 300 else content[:300].rstrip() + "..."
            collected.append(
                f"- ({insight_time.strftime('%m-%d %H:%M')}) "
                f"{nicknames.get(user_id, '회원')}: {clipped_content}"
            )

        if not collected:
            LOGGER.info("Skipped weekly insight briefing: no insight this week")
            return 0

        briefing = await generate_weekly_insight_briefing("\n".join(collected[:80]))
        briefing = _sanitize_briefing_text(briefing)
        if not briefing:
            LOGGER.warning("Skipped weekly insight briefing because AI returned no content")
            return 0

        def make_message(_):
            return (
                "이번 주 인사이트 AI 브리핑\n\n"
                f"{briefing}\n\n"
                "다음 주에도 루틴과 함께 꾸준히 성장해 봐요!"
            )

        return await send_text_notifications(
            context,
            make_message,
            label="weekly insight briefing",
            recipients=recipients,
        )
    except Exception as error:
        LOGGER.error(
            "Weekly personal insight briefing failed",
            exc_info=(type(error), error, error.__traceback__),
        )
        return 0


def _month_weeks(year: int, month: int) -> list[dict]:
    """Build ordered ISO week buckets that overlap with the given calendar month."""
    _, last_day = calendar.monthrange(year, month)
    weeks_map: dict[tuple[int, int], dict] = {}
    for day in range(1, last_day + 1):
        current = date(year, month, day)
        iso = current.isocalendar()
        key = (int(iso.year), int(iso.week))
        if key not in weeks_map:
            weeks_map[key] = {
                "iso_year": int(iso.year),
                "iso_week": int(iso.week),
                "week_id": f"{int(iso.year)}-W{int(iso.week):02d}",
                "start_date": current,
                "end_date": current,
            }
        else:
            weeks_map[key]["end_date"] = current
    return list(weeks_map.values())


def build_monthly_owner_briefing(
    users_records,
    logs_records,
    target_year: int,
    target_month: int,
) -> str:
    """
    Construct the monthly certification rate briefing for the bot owner.

    Includes overall monthly participation/average weekly certification rate
    against the total Users sheet headcount, plus a week-by-week list of
    certified and uncertified members.
    """
    members = _registered_members(users_records)
    total_members = len(members)
    if total_members == 0:
        return (
            f"📊 {target_year}년 {target_month:02d}월 루틴클럽 월간 인증률 브리핑\n\n"
            "현재 Users 시트에 등록된 회원이 없습니다."
        )

    member_ids = {user_id for user_id, _ in members}
    weeks = _month_weeks(target_year, target_month)
    week_keys = {(w["iso_year"], w["iso_week"]) for w in weeks}

    certified_by_week: dict[tuple[int, int], set[str]] = defaultdict(set)
    monthly_certified_users: set[str] = set()
    monthly_total_logs = 0

    for row in (logs_records or [])[1:]:
        if not _is_success(row):
            continue
        user_id = _private_user_id(row[2] if len(row) > 2 else "")
        if not user_id or user_id not in member_ids:
            continue
        logged_at = _log_datetime(row)
        if logged_at is None:
            continue
        log_date = logged_at.date()
        iso = log_date.isocalendar()
        wk_key = (int(iso.year), int(iso.week))

        if log_date.year == target_year and log_date.month == target_month:
            monthly_certified_users.add(user_id)
            monthly_total_logs += 1
            if wk_key in week_keys:
                certified_by_week[wk_key].add(user_id)

    monthly_participation_rate = round(len(monthly_certified_users) * 100 / total_members, 1)
    weekly_rates = []
    week_sections = []

    for index, wk in enumerate(weeks, start=1):
        wk_key = (wk["iso_year"], wk["iso_week"])
        certified_set = certified_by_week.get(wk_key, set())
        certified_names = [name for uid, name in members if uid in certified_set]
        uncertified_names = [name for uid, name in members if uid not in certified_set]
        week_rate = round(len(certified_names) * 100 / total_members, 1)
        weekly_rates.append(week_rate)

        period_str = f"{wk['start_date'].strftime('%m/%d')}~{wk['end_date'].strftime('%m/%d')}"
        certified_str = ", ".join(certified_names) if certified_names else "없음"
        uncertified_str = ", ".join(uncertified_names) if uncertified_names else "없음"

        week_sections.append(
            f"📌 {index}주차 ({wk['week_id']} | {period_str}) — 인증률 {week_rate:.1f}% ({len(certified_names)}/{total_members}명)\n"
            f"✅ 인증한 사람 ({len(certified_names)}명): {certified_str}\n"
            f"❌ 인증하지 않은 사람 ({len(uncertified_names)}명): {uncertified_str}"
        )

    avg_weekly_rate = round(sum(weekly_rates) / len(weekly_rates), 1) if weekly_rates else 0.0

    header = (
        f"📊 [{target_year}년 {target_month:02d}월 산스 AI루틴클럽 월간 인증률 브리핑]\n\n"
        f"👥 Users 시트 기준 전체 인원: {total_members}명\n"
        f"📈 월간 전체 인증률 (1회 이상 인증 인원 비율): {monthly_participation_rate:.1f}% ({len(monthly_certified_users)}/{total_members}명)\n"
        f"📆 주차별 평균 인증률: {avg_weekly_rate:.1f}%\n"
        f"📝 월간 총 성공 인증 건수: {monthly_total_logs}건"
    )

    return f"{header}\n\n" + "\n\n".join(week_sections)


async def monthly_owner_briefing_job(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    target_year: int | None = None,
    target_month: int | None = None,
) -> bool:
    """Send the monthly certification briefing to the configured owner via DM."""
    try:
        owner_id = get_owner_user_id()
        bot = getattr(context, "bot", None)
        if bot is None:
            LOGGER.error("Main bot context is unavailable; skipped monthly owner briefing")
            return False

        now = datetime.now(KST)
        if target_year is None or target_month is None:
            # 익월 1일 00:15 실행 시 직전 월(전월)을 대상으로 집계
            last_day_prev_month = now.replace(day=1) - timedelta(days=1)
            target_year = last_day_prev_month.year
            target_month = last_day_prev_month.month

        users_records = await async_get_all_values(users_sheet)
        logs_records = await async_get_all_values(logs_sheet)
        report_text = build_monthly_owner_briefing(
            users_records,
            logs_records,
            target_year,
            target_month,
        )

        # 4096자 초과 시 안전하게 분할 발송
        max_len = 4000
        chunks = [report_text[i:i + max_len] for i in range(0, len(report_text), max_len)] or [report_text]
        for chunk in chunks:
            await _send_with_retry(
                lambda chunk=chunk: bot.send_message(chat_id=owner_id, text=_trim_message(chunk)),
                label="monthly owner briefing",
                user_id=owner_id,
            )

        LOGGER.info(
            "Delivered monthly owner briefing for %04d-%02d to owner_id=%s",
            target_year,
            target_month,
            owner_id,
        )
        return True
    except Exception as error:
        LOGGER.error(
            "Monthly owner briefing failed",
            exc_info=(type(error), error, error.__traceback__),
        )
        return False
