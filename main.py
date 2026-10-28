import asyncio
import base64
import logging
import os
import random
import socket
import uuid
import warnings
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from app_logging import configure_logging
from attendance_utils import (
    annual_attendance_summary,
    collect_successful_attendance_weeks,
    current_attendance_snapshot,
    is_recorded_attendance_week,
    parse_attendance_week_id,
    parse_kst_datetime,
)
from card_news import format_routine_title

load_dotenv()
configure_logging()
LOGGER = logging.getLogger("routine_bot")

from telegram import (
    Bot,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.warnings import PTBUserWarning

warnings.filterwarnings("ignore", category=PTBUserWarning)

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from db_utils import (
    async_append_row,
    async_append_rows,
    async_delete_rows,
    async_find_in_col,
    async_get_all_values,
    async_update_cells,
    attendance_sheet,
    logs_sheet,
    users_sheet,
)
from ai_utils import (
    ensure_ollama_ready,
    generate_image_analysis,
)
from personal_notifications import (
    daily_dashboard_notification_job,
    evening_reminder_notification_job,
    monthly_owner_briefing_job,
    morning_notification_job,
    weekly_card_news_notification_job,
    weekly_insight_briefing_notification_job,
    weekly_top_notification_job,
)

# ==========================================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", "").strip()
KST = ZoneInfo("Asia/Seoul")
TEXT_AUTH_ROUTINE_ID = "text_auth"
PHOTO_AUTH_ROUTINE_ID = "photo_auth"

# APScheduler defaults to a one-second misfire grace period. A short polling
# or OS scheduling delay must not silently discard a member notification.
SCHEDULED_JOB_KWARGS = {
    "misfire_grace_time": 300,
    "coalesce": True,
    "max_instances": 1,
}

_ATTENDANCE_SETTLEMENT_LOCK = asyncio.Lock()
_ATTENDANCE_SHEET_LOCK = asyncio.Lock()
_USER_REGISTRATION_LOCK = asyncio.Lock()
_GROUP_SYNC_LOCK = asyncio.Lock()
_BACKGROUND_TASKS = set()
_INSTANCE_SOCKET = None

# 그룹방(GROUP_CHAT_ID)에서 감지된 멤버 캐시: {user_id: nickname}
_KNOWN_GROUP_MEMBERS: dict[str, str] = {}


def track_group_user(user) -> None:
    """그룹방에서 활동하거나 입장한 비-봇 유저를 동기화 후보 캐시에 기록합니다."""
    if user is None or getattr(user, "is_bot", False):
        return
    user_id = str(getattr(user, "id", "")).strip()
    if not user_id.isdigit() or int(user_id) <= 0:
        return
    nickname = (
        getattr(user, "first_name", None)
        or getattr(user, "username", None)
        or _KNOWN_GROUP_MEMBERS.get(user_id)
        or "회원"
    )
    _KNOWN_GROUP_MEMBERS[user_id] = str(nickname).strip() or "회원"


def acquire_instance_lock():
    """Prevent two local polling processes from using the same bot token."""
    global _INSTANCE_SOCKET
    try:
        port = int(os.environ.get("BOT_INSTANCE_LOCK_PORT", "47219"))
        if not 1024 <= port <= 65535:
            raise ValueError
    except ValueError:
        LOGGER.warning("Invalid BOT_INSTANCE_LOCK_PORT; using 47219")
        port = 47219

    instance_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        instance_socket.bind(("127.0.0.1", port))
        instance_socket.listen(1)
    except OSError as error:
        instance_socket.close()
        raise RuntimeError(
            f"Another routine bot instance is already using local lock port {port}"
        ) from error

    _INSTANCE_SOCKET = instance_socket
    LOGGER.info("Acquired local single-instance lock on port %s", port)


def release_instance_lock():
    global _INSTANCE_SOCKET
    if _INSTANCE_SOCKET is not None:
        _INSTANCE_SOCKET.close()
        _INSTANCE_SOCKET = None


def create_tracked_task(coro, label: str):
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)

    def _on_done(done_task):
        _BACKGROUND_TASKS.discard(done_task)
        if done_task.cancelled():
            LOGGER.info("Background task cancelled: %s", label)
            return
        error = done_task.exception()
        if error:
            LOGGER.error(
                "Background task failed: %s",
                label,
                exc_info=(type(error), error, error.__traceback__),
            )

    task.add_done_callback(_on_done)
    return task


# 메모리 캐시
daily_auth_count = {"date": "", "count": 0}

# 터미널 출력 로깅 패치 상태
_OUTPUT_LOG_PATCHED = False


def _clip_log_text(value, limit: int = 240) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", "\\n")
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


def terminal_log(direction: str, event_type: str, **fields):
    """입/출력 이벤트를 터미널에 일관된 형식으로 기록합니다."""
    ts = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
    payload = " | ".join(
        f"{k}={_clip_log_text(v)}" for k, v in fields.items() if v is not None and v != ""
    )
    LOGGER.info("[%s] [%s] [%s] %s", ts, direction, event_type, payload)


async def application_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Record every unhandled Telegram handler and JobQueue error with a traceback."""
    update_id = getattr(update, "update_id", None)
    error = context.error
    LOGGER.error(
        "Unhandled Telegram error (update_id=%s, job=%s)",
        update_id,
        getattr(context.job, "name", None),
        exc_info=(type(error), error, error.__traceback__) if error else None,
    )


async def log_incoming_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """들어오는 Update(명령어/메시지/콜백)를 공통 로깅하고 그룹방 멤버를 추적합니다."""
    try:
        if update.message:
            msg = update.message
            if GROUP_CHAT_ID and str(msg.chat_id) == str(GROUP_CHAT_ID):
                track_group_user(msg.from_user)
                for new_member in getattr(msg, "new_chat_members", None) or ():
                    track_group_user(new_member)
                left_member = getattr(msg, "left_chat_member", None)
                if left_member is not None:
                    _KNOWN_GROUP_MEMBERS.pop(str(getattr(left_member, "id", "")), None)

            if msg.text and msg.text.startswith("/"):
                event_type = "command"
                content = msg.text
            elif msg.photo:
                event_type = "photo"
                content = msg.caption or "<photo-no-caption>"
            else:
                event_type = "message"
                content = msg.text or msg.caption or "<non-text-message>"

            terminal_log(
                "IN",
                event_type,
                update_id=update.update_id,
                user_id=msg.from_user.id if msg.from_user else None,
                chat_id=msg.chat_id,
                chat_type=msg.chat.type if msg.chat else None,
                content=content,
            )
            return

        if update.callback_query:
            query = update.callback_query
            terminal_log(
                "IN",
                "callback_query",
                update_id=update.update_id,
                user_id=query.from_user.id if query.from_user else None,
                chat_id=query.message.chat_id if query.message else None,
                data=query.data,
            )
            return

        terminal_log("IN", "other_update", update_id=update.update_id)
    except Exception as e:
        print(f"입력 로깅 에러: {e}")


async def handle_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """그룹방의 ChatMemberUpdated 이벤트를 감지해 멤버 캐시를 갱신합니다."""
    member_update = update.chat_member
    if member_update is None or not GROUP_CHAT_ID:
        return
    if str(member_update.chat.id) != str(GROUP_CHAT_ID):
        return

    new_state = member_update.new_chat_member
    if new_state is None:
        return
    status_val = str(getattr(new_state, "status", "")).lower()
    user = getattr(new_state, "user", None)
    if status_val in {"creator", "administrator", "member"} or (
        status_val == "restricted" and getattr(new_state, "is_member", True)
    ):
        track_group_user(user)
    elif status_val in {"left", "kicked"} and user is not None:
        _KNOWN_GROUP_MEMBERS.pop(str(getattr(user, "id", "")), None)


def install_terminal_output_logging():
    """Bot 출력 API를 패치해 모든 발송 메시지를 터미널에 로깅합니다."""
    global _OUTPUT_LOG_PATCHED
    if _OUTPUT_LOG_PATCHED:
        return

    original_send_message = Bot.send_message
    original_reply_text = Message.reply_text
    original_edit_message_text = CallbackQuery.edit_message_text
    original_callback_answer = CallbackQuery.answer

    async def logged_send_message(self, *args, **kwargs):
        chat_id = kwargs.get("chat_id", args[0] if args else None)
        text = kwargs.get("text", args[1] if len(args) > 1 else "")
        terminal_log("OUT", "send_message", chat_id=chat_id, content=text)
        return await original_send_message(self, *args, **kwargs)

    async def logged_reply_text(self, *args, **kwargs):
        text = kwargs.get("text", args[0] if args else "")
        terminal_log(
            "OUT",
            "reply_text",
            chat_id=self.chat_id,
            user_id=self.from_user.id if self.from_user else None,
            content=text,
        )
        return await original_reply_text(self, *args, **kwargs)

    async def logged_edit_message_text(self, *args, **kwargs):
        text = kwargs.get("text", args[0] if args else "")
        terminal_log(
            "OUT",
            "edit_message_text",
            chat_id=self.message.chat_id if self.message else None,
            user_id=self.from_user.id if self.from_user else None,
            content=text,
        )
        return await original_edit_message_text(self, *args, **kwargs)

    async def logged_callback_answer(self, *args, **kwargs):
        text = kwargs.get("text", args[0] if args else "")
        terminal_log(
            "OUT",
            "callback_answer",
            user_id=self.from_user.id if self.from_user else None,
            data=self.data,
            content=text,
        )
        return await original_callback_answer(self, *args, **kwargs)

    Bot.send_message = logged_send_message
    Message.reply_text = logged_reply_text
    CallbackQuery.edit_message_text = logged_edit_message_text
    CallbackQuery.answer = logged_callback_answer
    _OUTPUT_LOG_PATCHED = True


async def is_group_chat_with_redirect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """그룹 채팅에서 호출된 경우 True를 반환하고, 1:1 DM 유도 메시지를 전송합니다."""
    chat_type = update.message.chat.type
    if chat_type != "private":
        bot_username = context.bot.username
        keyboard = [
            [InlineKeyboardButton("💬 봇과 1:1 대화로 이동", url=f"https://t.me/{bot_username}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚠️ 이 기능은 봇과의 1:1 대화에서만 사용할 수 있습니다.\n"
            "아래 버튼을 눌러 1:1 대화로 이동해주세요! 👇",
            reply_markup=reply_markup,
        )
        return True
    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = context.bot.username
    keyboard = [
        [InlineKeyboardButton("봇과 1:1 대화로 이동", url=f"https://t.me/{bot_username}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_msg = (
        "환영합니다! 산스 AI루틴클럽입니다. 🌱\n\n"
        "📚 **이용 가능한 명령어 및 인증 안내**\n"
        "🔹 `/start` - 봇 시작 및 기본 안내 확인\n"
        "🔹 `/reg [인증 내용]` - 텍스트로 즉시 루틴 인증 (1:1 대화방)\n"
        "🔹 `/status` - 나의 루틴 인증 및 출석률 현황 확인\n"
        "📸 **사진 인증** - 1:1 대화방에 사진과 캡션(설명글)을 함께 전송하면 즉시 인증됩니다!\n"
        "⌨️ **텍스트 인증** - 1:1 대화방에 `/reg 오늘 진행한 루틴 내용` 입력!\n\n"
        "첫 인증 시 회원 목록에 자동 등록되며, 인증 내용은 클럽 그룹방에 함께 공유됩니다."
    )
    await update.message.reply_text(welcome_msg, reply_markup=reply_markup, parse_mode="Markdown")


# ===============================================
# 신규 멤버 자동 등록 및 그룹방 ↔ Users 시트 동기화
# ===============================================
async def ensure_user_registered(user_id: str, nickname: str, now_time: str) -> bool:
    """Users 시트에 해당 user_id가 없으면 신규 멤버로 즉시 추가합니다."""
    async with _USER_REGISTRATION_LOCK:
        user_cell = await async_find_in_col(users_sheet, user_id, column=1)
        if user_cell is not None:
            return False
        await async_append_row(
            users_sheet,
            [user_id, nickname or "회원", now_time, 0, 0, "Asia/Seoul", ""],
        )
        LOGGER.info(
            "Registered new member in Users sheet: user_id=%s, nickname=%s",
            user_id,
            nickname,
        )
        return True


async def _check_group_membership(bot, group_chat_id: str, user_id: str) -> tuple[str, str]:
    """
    Check whether user_id currently belongs to group_chat_id via Telegram Bot API.

    Returns:
        (state, nickname) where state is one of:
        - "active": member is currently in the group
        - "inactive": member left, was kicked, or is not in the group
        - "unknown": transient error; caller should avoid destructive deletion
    """
    try:
        member = await bot.get_chat_member(chat_id=group_chat_id, user_id=int(user_id))
    except BadRequest as error:
        msg = str(error).lower()
        if any(
            token in msg
            for token in ("user not found", "participant_id_invalid", "user_not_participant", "chat not found")
        ):
            return ("inactive", "")
        LOGGER.warning("Group membership check returned BadRequest for user_id=%s: %s", user_id, error)
        return ("unknown", "")
    except Forbidden as error:
        LOGGER.warning("Group membership check forbidden for user_id=%s: %s", user_id, error)
        return ("unknown", "")
    except TelegramError as error:
        LOGGER.warning("Group membership check failed for user_id=%s: %s", user_id, error)
        return ("unknown", "")
    except Exception as error:
        LOGGER.warning("Unexpected error checking group membership for user_id=%s: %s", user_id, error)
        return ("unknown", "")

    user = getattr(member, "user", None)
    if user is not None and getattr(user, "is_bot", False):
        return ("inactive", "")

    nickname = ""
    if user is not None:
        nickname = (
            getattr(user, "first_name", None)
            or getattr(user, "username", None)
            or ""
        ).strip()

    status_val = str(getattr(member, "status", "")).lower()
    if status_val in {"creator", "administrator", "member"}:
        return ("active", nickname)
    if status_val == "restricted":
        return ("active" if getattr(member, "is_member", True) else "inactive", nickname)
    if status_val in {"left", "kicked"}:
        return ("inactive", nickname)
    return ("unknown", nickname)


async def sync_group_members_job(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """
    Synchronize GROUP_CHAT_ID membership with the Users sheet:
    - In group but missing from Users sheet -> append to Users sheet
    - Not in group but present in Users sheet -> delete from Users sheet
    """
    if _GROUP_SYNC_LOCK.locked():
        LOGGER.warning("Skipped group member sync because another sync is active")
        return {"added": 0, "removed": 0}

    async with _GROUP_SYNC_LOCK:
        bot = getattr(context, "bot", None)
        if bot is None or not GROUP_CHAT_ID:
            LOGGER.warning("Skipped group member sync: bot or GROUP_CHAT_ID unavailable")
            return {"added": 0, "removed": 0}

        now_time = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        candidate_members: dict[str, str] = dict(_KNOWN_GROUP_MEMBERS)
        verified_active_ids: set[str] = set()

        # 1. 그룹방 관리자/소유자 명단 확보 (Bot API 기본 지원)
        try:
            admins = await bot.get_chat_administrators(chat_id=GROUP_CHAT_ID)
            for admin in admins or ():
                user = getattr(admin, "user", None)
                if user is None or getattr(user, "is_bot", False):
                    continue
                uid = str(user.id).strip()
                if uid.isdigit() and int(uid) > 0:
                    name = (getattr(user, "first_name", None) or getattr(user, "username", None) or "회원").strip()
                    candidate_members[uid] = name or "회원"
                    verified_active_ids.add(uid)
                    _KNOWN_GROUP_MEMBERS[uid] = name or "회원"
        except Exception as error:
            LOGGER.warning("Failed to fetch group administrators during sync: %s", error)

        # 2. Logs 시트에 등장한 유저들도 후보 풀에 병합
        try:
            logs_records = await async_get_all_values(logs_sheet)
            for row in (logs_records or [])[1:]:
                if len(row) >= 3:
                    uid = str(row[2]).strip()
                    if uid.isdigit() and int(uid) > 0 and uid not in candidate_members:
                        candidate_members[uid] = "회원"
        except Exception as error:
            LOGGER.warning("Failed to read Logs sheet during group member sync: %s", error)

        # 3. Users 시트 조회 및 그룹방 탈퇴자/중복 행 판별
        users_records = await async_get_all_values(users_sheet)
        existing_sheet_user_ids: set[str] = set()
        rows_to_delete: list[int] = []

        for row_num, row in enumerate((users_records or [])[1:], start=2):
            uid = str(row[0]).strip() if row else ""
            if not uid.isdigit() or int(uid) <= 0:
                continue
            if uid in existing_sheet_user_ids:
                # 중복된 user_id 행 정리
                rows_to_delete.append(row_num)
                continue

            if uid in verified_active_ids:
                existing_sheet_user_ids.add(uid)
                continue

            state, detected_name = await _check_group_membership(bot, GROUP_CHAT_ID, uid)
            if state == "inactive":
                rows_to_delete.append(row_num)
                _KNOWN_GROUP_MEMBERS.pop(uid, None)
            else:
                existing_sheet_user_ids.add(uid)
                if detected_name:
                    candidate_members[uid] = detected_name

        # 4. 그룹방에 없으나 Users 시트에 있는 행 삭제 (역순 삭제로 행 밀림 방지)
        for row_num in sorted(set(rows_to_delete), reverse=True):
            await async_delete_rows(users_sheet, row_num)

        # 5. 그룹방에 있으나 Users 시트에 없는 멤버 추가
        new_rows = []
        for uid, nickname in candidate_members.items():
            if uid in existing_sheet_user_ids:
                continue
            if uid in verified_active_ids:
                new_rows.append([uid, nickname or "회원", now_time, 0, 0, "Asia/Seoul", ""])
                existing_sheet_user_ids.add(uid)
                continue

            state, detected_name = await _check_group_membership(bot, GROUP_CHAT_ID, uid)
            if state == "active":
                final_name = detected_name or nickname or "회원"
                new_rows.append([uid, final_name, now_time, 0, 0, "Asia/Seoul", ""])
                existing_sheet_user_ids.add(uid)

        if new_rows:
            await async_append_rows(users_sheet, new_rows)

        LOGGER.info(
            "Group member sync completed: added=%s, removed=%s",
            len(new_rows),
            len(rows_to_delete),
        )
        return {"added": len(new_rows), "removed": len(rows_to_delete)}


async def monthly_sync_and_owner_briefing_job(context: ContextTypes.DEFAULT_TYPE):
    """
    매월 1일 00:15 KST 실행:
    1) 그룹방 소속 멤버와 Users 시트 ID를 동기화 (추가/삭제)
    2) 동기화된 Users 시트 기준으로 소유자(1415330667)에게 전월 인증률 및 주차별 인증/미인증자 브리핑 전송
    """
    sync_result = await sync_group_members_job(context)
    briefed = await monthly_owner_briefing_job(context)
    return {"sync": sync_result, "briefed": briefed}


# ===============================================
# 즉시 루틴 인증 (사진+캡션 / 텍스트)
# ===============================================
async def process_auth(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id,
    chat_id,
    routine_row,
    routine_id,
    routine_name,
    now_time,
    now_date,
    message_link,
    caption,
    query=None,
    base64_img=None,
    file_id=None,
    source_chat_id=None,
    source_message_id=None,
):
    global daily_auth_count

    if chat_id not in daily_auth_count:
        daily_auth_count[chat_id] = {"date": "", "count": 0}

    if daily_auth_count[chat_id]["date"] != now_date:
        daily_auth_count[chat_id]["date"] = now_date
        daily_auth_count[chat_id]["count"] = 1
    else:
        daily_auth_count[chat_id]["count"] += 1
    current_count = daily_auth_count[chat_id]["count"]

    if query:
        user_obj = query.from_user
    else:
        user_obj = update.message.from_user
    nickname = (user_obj.first_name or user_obj.username or "회원") if user_obj else "회원"
    track_group_user(user_obj)

    # 새로운 멤버가 인증하면 Users 시트에 자동 등록
    try:
        await ensure_user_registered(user_id, nickname, now_time)
    except Exception as e:
        LOGGER.error(
            "Failed to ensure user registration for user_id=%s",
            user_id,
            exc_info=(type(e), e, e.__traceback__),
        )

    log_id = str(uuid.uuid4())
    await async_append_row(
        logs_sheet,
        [log_id, routine_id, user_id, now_time, "success", message_link, caption, "", routine_name],
    )

    praises = ["대단해요!", "멋집니다!", "최고! 이 기세로 내일도 파이팅!", "정말 대단한 끈기네요 🎉"]
    reply_msg = f"✅ 오늘 {current_count}번째 인증입니다!\n{random.choice(praises)}"

    if query:
        await query.edit_message_text(reply_msg)
    else:
        await update.message.reply_text(reply_msg, reply_to_message_id=update.message.message_id)

    print(f"✅ [루틴 인증] {nickname} ({user_id}): {routine_name} (오늘 {current_count}번째)")

    # 그룹 채팅방 공유 (멀티모달 AI 분석 연동)
    try:
        auth_icon = "📸" if file_id else "✅"

        def build_auth_group_header(name_u: str, r_name: str, ai_comment: str = None) -> str:
            parts = [
                f"{auth_icon} {name_u}님이 루틴을 인증했습니다!",
                "",
                f"🔥 {r_name}",
            ]
            if ai_comment:
                parts.extend([
                    "",
                    "🤖 AI 코칭 코멘트",
                    ai_comment,
                ])
            parts.extend([
                "",
                "💬 이 루틴이나 주제에 관심이 있으신 분들은 아래에 자유롭게 의견이나 응원 댓글을 달아주세요!",
            ])
            return "\n".join(parts)

        def build_auth_group_caption(name_u: str, r_name: str, cap: str, ai_comment: str = None) -> str:
            return (
                f"{build_auth_group_header(name_u, r_name, ai_comment)}\n\n"
                f"📝 인증 내용\n{cap}"
            )

        async def send_text_chunks(value: str):
            max_len = 3900
            chunks = [value[i:i + max_len] for i in range(0, len(value), max_len)] or [value]
            for chunk in chunks:
                await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=chunk)

        async def send_auth_group_post(fid, header_text, fallback_text, source_chat_id=None, source_message_id=None):
            try:
                if source_chat_id is not None and source_message_id is not None:
                    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=header_text)
                    await context.bot.copy_message(
                        chat_id=GROUP_CHAT_ID,
                        from_chat_id=source_chat_id,
                        message_id=source_message_id,
                    )
                    return

                if fid and len(fallback_text) <= 1000:
                    await context.bot.send_photo(
                        chat_id=GROUP_CHAT_ID,
                        photo=fid,
                        caption=fallback_text,
                    )
                    return

                if fid:
                    await context.bot.send_photo(
                        chat_id=GROUP_CHAT_ID,
                        photo=fid,
                        caption="📸 루틴 인증 사진입니다. 인증 원문은 이어지는 메시지에 함께 공유됩니다.",
                    )
                await send_text_chunks(fallback_text)
            except Exception as send_error:
                print(f"인증 공유 전송 실패, 사진/텍스트 분리 전송으로 재시도합니다: {send_error}")
                if fid:
                    await context.bot.send_photo(
                        chat_id=GROUP_CHAT_ID,
                        photo=fid,
                        caption="루틴 인증 사진입니다. 인증 원문은 이어지는 메시지에 함께 공유됩니다.",
                    )
                await send_text_chunks(fallback_text)

        async def bg_auth_share_task(b64, cap, r_name, fid, name_u, source_chat, source_message):
            try:
                ai_comment = None
                if b64:
                    ai_comment = await generate_image_analysis(b64, cap, r_name)
                header_text = build_auth_group_header(name_u, r_name, ai_comment)
                fallback_text = build_auth_group_caption(name_u, r_name, cap, ai_comment)
                await send_auth_group_post(
                    fid,
                    header_text,
                    fallback_text,
                    source_chat_id=source_chat,
                    source_message_id=source_message,
                )
            except Exception as ex:
                print(f"인증샷 그룹방 공유 백그라운드 태스크 실패: {ex}")
                try:
                    fallback_caption = build_auth_group_caption(name_u, r_name, cap)
                    await send_auth_group_post(fid, fallback_caption, fallback_caption)
                except Exception as fallback_error:
                    print(f"인증 공유 폴백 전송도 실패했습니다: {fallback_error}")

        create_tracked_task(
            bg_auth_share_task(
                base64_img,
                caption,
                routine_name,
                file_id,
                nickname,
                source_chat_id,
                source_message_id,
            ),
            "인증 그룹 공유",
        )
    except Exception as e:
        print(f"그룹 공유 태스크 생성 에러 (인증): {e}")


async def reg_text_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Use /reg as text-only authentication without a Routines-sheet match."""
    if await is_group_chat_with_redirect(update, context):
        return

    auth_text = " ".join(context.args).strip()
    if not auth_text:
        await update.message.reply_text(
            "⌨️ 인증 내용을 입력해주세요.\n"
            "예시: `/reg 오늘 독서 30분 완료`",
            parse_mode="Markdown",
        )
        return

    user_id = str(update.message.from_user.id)
    chat_id = str(update.message.chat_id)
    now_dt = datetime.now(KST)
    now_date = now_dt.strftime("%Y-%m-%d")
    now_time = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    await process_auth(
        update=update,
        context=context,
        user_id=user_id,
        chat_id=chat_id,
        routine_row=None,
        routine_id=TEXT_AUTH_ROUTINE_ID,
        routine_name=auth_text,
        now_time=now_time,
        now_date=now_date,
        message_link=update.message.link or "",
        caption=auth_text,
        source_chat_id=chat_id,
        source_message_id=update.message.message_id,
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Authenticate photo+caption immediately without looking up Routines."""
    if update.message.chat.type != "private":
        return

    caption = (update.message.caption or "").strip()
    if not caption:
        return

    user_id = str(update.message.from_user.id)
    chat_id = str(update.message.chat_id)
    now_dt = datetime.now(KST)
    now_date = now_dt.strftime("%Y-%m-%d")
    now_time = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    photo_id = update.message.photo[-1].file_id
    message_link = update.message.link
    file_info = None
    if not message_link:
        try:
            file_info = await context.bot.get_file(photo_id)
            message_link = file_info.file_path or ""
        except Exception as e:
            print(f"사진 링크 조회 에러: {e}")
            message_link = ""

    # 멀티모달용 이미지 base64 인코딩
    base64_img = None
    try:
        if file_info is None:
            file_info = await context.bot.get_file(photo_id)
        file_bytes = await file_info.download_as_bytearray()
        base64_img = base64.b64encode(file_bytes).decode("utf-8")
    except Exception as e:
        print(f"이미지 base64 다운로드/인코딩 에러: {e}")

    await process_auth(
        update=update,
        context=context,
        user_id=user_id,
        chat_id=chat_id,
        routine_row=None,
        routine_id=PHOTO_AUTH_ROUTINE_ID,
        routine_name=caption,
        now_time=now_time,
        now_date=now_date,
        message_link=message_link,
        caption=caption,
        base64_img=base64_img,
        file_id=photo_id,
        source_chat_id=chat_id,
        source_message_id=update.message.message_id,
    )


# ===============================================
# 내 현황 모니터링 (/status - Logs 및 출석률 기반)
# ===============================================
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    now = datetime.now(KST)
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    try:
        logs_records = await async_get_all_values(logs_sheet)
    except Exception:
        await update.message.reply_text("데이터를 불러오는 중 오류가 발생했습니다.")
        return

    today_count = 0
    weekly_count = 0
    total_count = 0
    recent_logs = []

    for row in (logs_records or [])[1:]:
        if len(row) < 5 or str(row[4]).strip().lower() != "success":
            continue
        if str(row[2]).strip() != user_id:
            continue

        total_count += 1
        logged_at = parse_kst_datetime(row[3])
        raw_content = (
            str(row[6]).strip()
            if len(row) > 6 and row[6]
            else (str(row[8]).strip() if len(row) > 8 and row[8] else "루틴 인증")
        )
        short_content = format_routine_title(raw_content, max_chars=30)

        if logged_at is not None:
            if logged_at.date() == now.date():
                today_count += 1
            if logged_at >= week_start:
                weekly_count += 1
            recent_logs.append((logged_at.strftime("%m-%d %H:%M"), short_content))
        else:
            recent_logs.append((str(row[3])[:16], short_content))

    attendance_weeks = collect_successful_attendance_weeks(logs_records)
    snapshot = current_attendance_snapshot(attendance_weeks.get(user_id, set()), now)

    lines = [
        "📊 **나의 루틴 인증 및 출석 현황** 📊",
        "",
        f"✅ 오늘 인증: {today_count}건",
        f"📅 이번 주 인증: {weekly_count}건",
        f"🔥 누적 총 인증: {total_count}건",
    ]

    if snapshot is not None:
        annual = snapshot.annual
        lines.extend([
            "",
            f"🗓️ **{annual.year}년 출석률 현황**",
            f"• 이번 주 출석: {'출석 완료 (100%)' if snapshot.current_week_attended else '아직 미인증'}",
            f"• 올해 누적 출석률: {annual.rate_percent:.1f}% ({annual.attended_weeks}/{annual.denominator}주)",
        ])
        if snapshot.is_exception_week:
            lines.append("• 안내: 53주차는 연말 예외 주차로 연간 출석률 계산에서 제외됩니다.")
        elif annual.weeks_to_target == 0:
            lines.append(f"• 목표: 🎉 {annual.year}년 출석률 80% 기준 달성 완료!")
        else:
            lines.append(
                f"• 목표: 🎯 80% 기준까지 서로 다른 {annual.weeks_to_target}주 출석이 더 필요해요."
            )

    if recent_logs:
        lines.extend(["", "📝 **최근 인증 기록**"])
        for ts_str, content_str in recent_logs[-3:]:
            lines.append(f"• ({ts_str}) {content_str}")
    else:
        lines.extend([
            "",
            "👀 아직 등록된 인증 기록이 없습니다.",
            "1:1 대화방에서 사진+캡션 또는 `/reg [인증 내용]`으로 첫 인증을 시작해보세요!",
        ])

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ===============================================
# 주간 출석률 정산 (매주 월요일 00:06 KST)
# ===============================================
async def settle_weekly_attendance(context: ContextTypes.DEFAULT_TYPE):
    """Settle the prior KST ISO week after final Sunday log writes have drained."""
    if _ATTENDANCE_SETTLEMENT_LOCK.locked():
        LOGGER.warning("Skipped duplicate weekly attendance settlement")
        return False

    async with _ATTENDANCE_SETTLEMENT_LOCK:
        now_dt = datetime.now(KST)
        last_week_dt = now_dt - timedelta(weeks=1)
        iso_year, iso_week, _ = last_week_dt.isocalendar()
        last_week_id = f"{iso_year}-W{iso_week:02d}"
        try:
            settled = await update_attendance_sheet(last_week_id)
        except Exception as error:
            LOGGER.error(
                "Weekly attendance settlement failed for %s",
                last_week_id,
                exc_info=(type(error), error, error.__traceback__),
            )
            return False
        if settled:
            LOGGER.info("Weekly attendance settlement completed for %s", last_week_id)
        return settled


async def update_attendance_sheet(week_id: str):
    """Serialize attendance-sheet reads and writes across jobs."""
    async with _ATTENDANCE_SHEET_LOCK:
        return await _update_attendance_sheet(week_id)


async def _update_attendance_sheet(week_id: str):
    """
    Set one closed week's binary attendance (0 or 100) and annual summaries.

    A successful routine verification in a KST ISO week marks that member
    present for the week. Annual values are calculated in Python from Logs,
    never from a Google Sheets formula.
    """
    import gspread

    try:
        year, week = parse_attendance_week_id(week_id)
        if not is_recorded_attendance_week(year, week):
            LOGGER.info(
                "Skipped attendance settlement for %s because tracking starts at 2026-W30",
                week_id,
            )
            return False

        users_records = await async_get_all_values(users_sheet)
        logs_records = await async_get_all_values(logs_sheet)
        att_records = await async_get_all_values(attendance_sheet)
        headers = list(att_records[0]) if att_records else []
        header_cells = []

        def ensure_header(header: str, fixed_column: int | None = None) -> int:
            if fixed_column is None:
                for index, value in enumerate(headers, start=1):
                    if value == header:
                        return index
                headers.append(header)
                column = len(headers)
            else:
                column = fixed_column
                while len(headers) < column:
                    headers.append("")
                if headers[column - 1] == header:
                    return column
                headers[column - 1] = header
            header_cells.append(gspread.Cell(row=1, col=column, value=header))
            return column

        ensure_header("user_id", fixed_column=1)
        ensure_header("nickname", fixed_column=2)
        current_rate_col = ensure_header("current_year_attendance_rate", fixed_column=3)
        weekly_rate_col = ensure_header(week_id)
        active_year, _, _ = datetime.now(KST).isocalendar()
        if active_year < 2026:
            active_year = year
        summary_years = [year]
        if active_year >= 2026 and active_year not in summary_years:
            summary_years.append(active_year)
        annual_columns = {
            summary_year: (
                ensure_header(f"{summary_year}_attended_weeks"),
                ensure_header(f"{summary_year}_attendance_rate"),
                ensure_header(f"{summary_year}_weeks_to_80pct"),
            )
            for summary_year in summary_years
        }

        if not att_records:
            await async_update_cells(
                attendance_sheet,
                header_cells,
                value_input_option="RAW",
            )
            att_records = [headers]
            header_cells = []

        attendance_weeks_by_user = collect_successful_attendance_weeks(logs_records)
        att_user_rows = {
            str(row[0]).strip(): row_index
            for row_index, row in enumerate(att_records[1:], start=2)
            if row and str(row[0]).strip()
        }
        members = []
        seen_user_ids = set()
        for row in users_records[1:]:
            if not row:
                continue
            user_id = str(row[0]).strip()
            if not user_id or user_id in seen_user_ids:
                continue
            seen_user_ids.add(user_id)
            nickname = str(row[1] or "").strip() if len(row) > 1 else ""
            members.append((user_id, nickname or "회원"))

        new_user_rows = []
        next_row = max(len(att_records), 1) + 1
        for user_id, nickname in members:
            if user_id in att_user_rows:
                continue
            new_user_rows.append([user_id, nickname] + [""] * (len(headers) - 2))
            att_user_rows[user_id] = next_row
            next_row += 1

        if new_user_rows:
            await async_append_rows(
                attendance_sheet,
                new_user_rows,
                value_input_option="RAW",
            )

        cells_to_update = list(header_cells)
        week_key = (year, week)
        for user_id, _ in members:
            row_num = att_user_rows[user_id]
            member_weeks = attendance_weeks_by_user.get(user_id, set())
            summaries = {
                summary_year: annual_attendance_summary(member_weeks, summary_year)
                for summary_year in summary_years
            }
            current_summary = summaries[active_year]
            weekly_rate = 100.0 if week_key in member_weeks else 0.0
            cells_to_update.extend(
                (
                    gspread.Cell(row=row_num, col=weekly_rate_col, value=weekly_rate),
                    gspread.Cell(
                        row=row_num,
                        col=current_rate_col,
                        value=current_summary.rate_percent,
                    ),
                )
            )
            for summary_year, summary in summaries.items():
                attended_weeks_col, annual_rate_col, weeks_to_target_col = annual_columns[summary_year]
                cells_to_update.extend(
                    (
                        gspread.Cell(row=row_num, col=attended_weeks_col, value=summary.attended_weeks),
                        gspread.Cell(row=row_num, col=annual_rate_col, value=summary.rate_percent),
                        gspread.Cell(row=row_num, col=weeks_to_target_col, value=summary.weeks_to_target),
                    )
                )

        if cells_to_update:
            await async_update_cells(
                attendance_sheet,
                cells_to_update,
                value_input_option="RAW",
            )

        LOGGER.info(
            "Attendance settlement completed for %s: %s members, %s weekly rate",
            week_id,
            len(members),
            "exception" if week == 53 else "0/100",
        )
        return True
    except Exception as e:
        LOGGER.error(
            "Attendance settlement failed for %s",
            week_id,
            exc_info=(type(e), e, e.__traceback__),
        )
        raise


def main():
    install_terminal_output_logging()

    missing_settings = [
        name
        for name, value in (("TELEGRAM_BOT_TOKEN", TOKEN), ("GROUP_CHAT_ID", GROUP_CHAT_ID))
        if not value
    ]
    if missing_settings:
        raise RuntimeError(f"Required configuration is missing: {', '.join(missing_settings)}")

    acquire_instance_lock()

    auto_start_ollama = os.environ.get("AUTO_START_OLLAMA", "true").lower() in ("1", "true", "yes", "y")
    wait_seconds_str = os.environ.get("OLLAMA_STARTUP_WAIT_SECONDS", "20")
    try:
        startup_wait_seconds = int(wait_seconds_str)
    except ValueError:
        startup_wait_seconds = 20

    if auto_start_ollama:
        print("🤖 Ollama 자동 준비를 확인합니다...")
        try:
            ollama_ready = asyncio.run(ensure_ollama_ready(wait_seconds=startup_wait_seconds))
            if ollama_ready:
                print("✅ Ollama 준비 완료")
            else:
                print("⚠️ Ollama 자동 준비에 실패했습니다. 봇은 계속 실행되며 AI 기능만 제한될 수 있습니다.")
        except Exception as e:
            print(f"⚠️ Ollama 자동 준비 중 에러: {e}")

    app = Application.builder().token(TOKEN).build()
    app.add_error_handler(application_error_handler)

    # 입력 로깅 및 그룹방 멤버 감지 핸들러
    app.add_handler(MessageHandler(filters.ALL, log_incoming_update), group=-1)
    app.add_handler(CallbackQueryHandler(log_incoming_update), group=-1)
    app.add_handler(
        ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.CHAT_MEMBER),
        group=-1,
    )

    # 사용자 명령어 및 인증 핸들러
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("reg", reg_text_auth))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # 스케줄러 등록
    jq = app.job_queue
    kst = ZoneInfo("Asia/Seoul")

    # 기존 메인 봇이 Users 시트 회원에게 개인 DM을 직접 발송합니다.
    jq.run_daily(
        morning_notification_job,
        time(hour=9, minute=0, second=0, tzinfo=kst),
        name="personal_morning",
        job_kwargs=SCHEDULED_JOB_KWARGS,
    )
    jq.run_daily(
        daily_dashboard_notification_job,
        time(hour=18, minute=0, second=0, tzinfo=kst),
        name="personal_dashboard",
        job_kwargs=SCHEDULED_JOB_KWARGS,
    )
    jq.run_daily(
        evening_reminder_notification_job,
        time(hour=21, minute=0, second=0, tzinfo=kst),
        name="personal_reminder",
        job_kwargs=SCHEDULED_JOB_KWARGS,
    )
    jq.run_daily(
        weekly_top_notification_job,
        time(hour=12, minute=0, second=0, tzinfo=kst),
        days=(0,),
        name="personal_weekly_top",
        job_kwargs=SCHEDULED_JOB_KWARGS,
    )
    jq.run_daily(
        weekly_insight_briefing_notification_job,
        time(hour=12, minute=5, second=0, tzinfo=kst),
        days=(0,),
        name="personal_weekly_briefing",
        job_kwargs=SCHEDULED_JOB_KWARGS,
    )
    jq.run_daily(
        weekly_card_news_notification_job,
        time(hour=12, minute=10, second=0, tzinfo=kst),
        days=(0,),
        name="personal_weekly_card_news",
        job_kwargs=SCHEDULED_JOB_KWARGS,
    )
    LOGGER.info(
        "Main-bot personal notification jobs registered (misfire grace=%ss)",
        SCHEDULED_JOB_KWARGS["misfire_grace_time"],
    )

    # 📅 주간 출석률 정산 (매주 월요일 00:06 KST, JobQueue: Sunday=0, Monday=1)
    jq.run_daily(
        settle_weekly_attendance,
        time(hour=0, minute=6, second=0, tzinfo=kst),
        days=(1,),
        name="settle_weekly_attendance",
        job_kwargs=SCHEDULED_JOB_KWARGS,
    )

    # 🗓️ 매월 1일 00:15 KST: 그룹방 멤버 ↔ Users 시트 동기화 + 전월 월간 인증률 소유자(1415330667) 브리핑
    jq.run_monthly(
        monthly_sync_and_owner_briefing_job,
        when=time(hour=0, minute=15, second=0, tzinfo=kst),
        day=1,
        name="monthly_sync_and_owner_briefing",
        job_kwargs=SCHEDULED_JOB_KWARGS,
    )

    print("🤖 산스 AI루틴클럽 봇 가동 시작! (비동기, 출석률 정산, 월초 동기화·월말 브리핑 장착 완료)")
    app.run_polling(bootstrap_retries=-1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        LOGGER.info("Routine bot stopped by keyboard interrupt")
    except Exception:
        LOGGER.exception("Routine bot terminated during startup or polling")
        raise
    finally:
        release_instance_lock()
