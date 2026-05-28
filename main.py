import asyncio
import os
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import random
import uuid
import warnings
import base64
import tempfile
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot, Message, CallbackQuery
from telegram.warnings import PTBUserWarning

# PTB UserWarning 무시 (ConversationHandler + CallbackQueryHandler 관련)
warnings.filterwarnings("ignore", category=PTBUserWarning)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, 
    ContextTypes, CallbackQueryHandler, ConversationHandler
)
from db_utils import (
    async_find_in_col, async_findall_in_col, async_append_row,
    async_update_cell, async_delete_rows, async_get_all_records,
    async_row_values, async_cell, users_sheet, routines_sheet, logs_sheet, insights_sheet, ai_recommendations_sheet,
    weekly_achievement_sheet, attendance_sheet
)
from ai_utils import (
    ensure_ollama_ready,
    generate_insight_keywords,
    generate_routine_recommendation,
    generate_weekly_insight_briefing,
    generate_image_analysis,
    generate_insight_summary,
    generate_catalyst_mission,
    generate_card_routine_summary,
)
from card_news import generate_card_news

load_dotenv()

# ==========================================
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GROUP_CHAT_ID = os.environ["GROUP_CHAT_ID"]
INSIGHT_CHAT_ID = os.environ.get("INSIGHT_CHAT_ID", "-1003779149038")
INSIGHT_THREAD_ID_STR = os.environ.get("INSIGHT_THREAD_ID", "594")
INSIGHT_THREAD_ID = int(INSIGHT_THREAD_ID_STR) if INSIGHT_THREAD_ID_STR else None
CATALYST_CHAT_ID = os.environ.get("CATALYST_CHAT_ID", "-1003779149038")
CATALYST_THREAD_ID_STR = os.environ.get("CATALYST_THREAD_ID", "4")
CATALYST_THREAD_ID = int(CATALYST_THREAD_ID_STR) if CATALYST_THREAD_ID_STR else None
CATALYST_STATE_DIR = os.environ.get(
    "CATALYST_STATE_DIR",
    os.path.join(tempfile.gettempdir(), "telegram_routine_bot"),
)
# ==========================================

# /reg 대화(Conversation) 상태 정의
CHOOSING_CATEGORY = 1
CHOOSING_FREQUENCY = 2

# 메모리 캐시
daily_auth_count = {"date": "", "count": 0}

# 터미널 출력 로깅 패치 상태
_OUTPUT_LOG_PATCHED = False

def _clip_log_text(value, limit: int = 240) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", "\\n")
    return text if len(text) <= limit else text[:limit] + "...(truncated)"

def sanitize_ai_briefing_text(text: str) -> str:
    """AI 브리핑에서 금지 문법(헤더/코드블록)만 제거하고 가독성 줄바꿈은 보존합니다."""
    if not text:
        return ""

    cleaned_lines = []
    prev_blank = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            if cleaned_lines and not prev_blank:
                cleaned_lines.append("")
                prev_blank = True
            continue

        if stripped.startswith("```"):
            continue

        while stripped.startswith("#"):
            stripped = stripped[1:].lstrip()

        if not stripped:
            continue

        cleaned_lines.append(stripped)
        prev_blank = False

    return "\n".join(cleaned_lines).strip()

def terminal_log(direction: str, event_type: str, **fields):
    """입/출력 이벤트를 터미널에 일관된 형식으로 기록합니다."""
    ts = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
    payload = " | ".join(
        f"{k}={_clip_log_text(v)}" for k, v in fields.items() if v is not None and v != ""
    )
    print(f"[{ts}] [{direction}] [{event_type}] {payload}")

async def log_incoming_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """들어오는 Update(명령어/메시지/콜백)를 공통 로깅합니다."""
    try:
        if update.message:
            msg = update.message
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

def get_weekly_target(frequency: str) -> int:
    """target_frequency 문자열을 주간 목표 횟수(정수)로 변환합니다."""
    mapping = {"everyday": 7, "weekdays": 5, "3times": 3, "1time": 1}
    return mapping.get(frequency, 7)

def get_current_week_info() -> tuple:
    """현재 주차 정보를 반환합니다: (week_id, week_start_str)"""
    now = datetime.now()
    iso_year, iso_week, _ = now.isocalendar()
    week_id = f"{iso_year}-W{iso_week:02d}"
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    week_start_str = week_start.strftime("%Y-%m-%d")
    return (week_id, week_start_str)

async def update_weekly_achievement(routine_id: str, routine_name: str, user_id: str, frequency: str) -> tuple:
    """
    Weekly_Achievement 시트에서 현재 주차 행을 찾거나 생성하고 weekly_done을 +1합니다.
    반환: (weekly_done, weekly_rate)
    """
    week_id, week_start_str = get_current_week_info()
    weekly_target = get_weekly_target(frequency)

    try:
        all_rows = await asyncio.to_thread(weekly_achievement_sheet.get_all_values)
    except Exception as e:
        print(f"Weekly_Achievement 조회 에러: {e}")
        return (0, 0.0)

    # 기존 행 검색: (week_id, routine_id) 일치하는 행 찾기
    found_row = None
    for i, row in enumerate(all_rows[1:]):
        if len(row) >= 4 and row[0] == week_id and row[3] == routine_id:
            found_row = i + 2  # 시트 행 번호 (1-indexed, 헤더 제외)
            break

    if found_row:
        # 기존 행의 weekly_done 증가
        done_val = await async_cell(weekly_achievement_sheet, found_row, 8)
        current_done = int(done_val) if done_val else 0
        new_done = current_done + 1
        await async_update_cell(weekly_achievement_sheet, found_row, 8, new_done)
    else:
        # 새 행 생성
        new_done = 1
        new_row = [week_id, week_start_str, user_id, routine_id, routine_name, frequency, weekly_target, new_done]
        found_row = len(all_rows) + 1
        await async_append_row(weekly_achievement_sheet, new_row)

    # I열(9열)에 수식 삽입: =MIN(H{row}/G{row}, 1)*100
    formula = f"=MIN(H{found_row}/G{found_row}, 1)*100"
    await asyncio.to_thread(
        weekly_achievement_sheet.update_acell, f"I{found_row}", formula
    )

    # 수식 결과 읽기
    rate_val = await async_cell(weekly_achievement_sheet, found_row, 9)
    try:
        weekly_rate = float(rate_val) if rate_val else 0.0
        weekly_rate = min(weekly_rate, 100.0)
    except (ValueError, TypeError):
        weekly_rate = round(min(new_done / weekly_target, 1) * 100, 1) if weekly_target > 0 else 0.0

    return (new_done, weekly_rate)

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
            reply_markup=reply_markup
        )
        return True
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = context.bot.username
    keyboard = [
        [InlineKeyboardButton("봇과 1:1 대화로 이동", url=f'https://t.me/{bot_username}')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_msg = (
        "환영합니다! 산스 AI루틴클럽입니다. 🌱\n\n"
        "📚 **이용 가능한 명령어 안내**\n"
        "🔹 /start - 봇 시작 및 기본 안내 확인\n"
        "🔹 /reg [루틴이름] - 새로운 루틴 목표 등록\n"
        "🔹 /edit - 등록된 루틴의 이름 수정 ✏️\n"
        "🔹 /status - 나의 루틴 인증 현황 모니터링\n"
        "🔹 /insight [내용] - 인사이트 공유\n"
        "🔹 /del - 등록된 루틴 삭제\n"
        "🔹 /rank - 명예의 전당 (포인트 랭킹 확인) 🏆\n"
        "📸 **단일 인증** - 사진을 업로드하고 캡션에 내용을 적어 전송!\n\n"
        "그룹방 알림을 최소화하기 위해, 그룹방에서는 명령어로 짧게 사용하시거나 아래 버튼을 눌러 1:1 채팅방에서 기능을 확인해보세요."
    )
    await update.message.reply_text(welcome_msg, reply_markup=reply_markup, parse_mode='Markdown')

# ===============================================
# 루틴 등록 로직 (/reg -> 즉시 주 1회로 고정 등록)
# ===============================================
async def reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_group_chat_with_redirect(update, context):
        return
    text = update.message.text.split()
    if len(text) < 2:
        await update.message.reply_text("앗, 양식이 조금 틀렸어요! 😅\n👉 다시 `/reg 매일독서10쪽` 처럼 등록할 루틴을 입력해주세요!", parse_mode='Markdown')
        return

    routine_name = " ".join(text[1:])
    category = "Lifestyle"
    frequency = "1time"
    
    user_id = str(update.message.from_user.id)
    nickname = update.message.from_user.first_name or update.message.from_user.username or "회원"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cell = await async_find_in_col(users_sheet, user_id)
    if not cell:
        await async_append_row(users_sheet, [user_id, nickname, now, 2, 0, "Asia/Seoul", ""])
        
    routine_id = str(uuid.uuid4())
    # [routine_id, user_id, routine_name, category, frequency, status, created_at, current_streak]
    await async_append_row(routines_sheet, [routine_id, user_id, routine_name, category, frequency, "active", now, 0])
    
    await update.message.reply_text(
        f"🎉 환영합니다! [{nickname}]님이 새로운 루틴 여정을 즉시 시작했습니다!\n"
        f"🎯 목표: {routine_name}\n"
        f"📊 빈도: 주 1회 (1time) 고정 등록 완료!\n\n"
        f"작은 성취부터 시작해보세요! 파이팅! 👏"
    )
    print(f"👤 [루틴 등록] {nickname} ({user_id}): {routine_name} / {frequency}")
    
    try:
        group_msg = (
            f"📣 **새로운 루틴 도전!**\n\n"
            f"👤 **{nickname}**님이 새로운 목표를 세웠습니다!\n"
            f"🎯 **목표**: {routine_name}\n"
            f"📊 **빈도**: 주 1회(1time) 고정\n\n"
            f"우리 모두 함께 응원해요! 🔥"
        )
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=group_msg, parse_mode='Markdown')
    except Exception as e:
        print(f"그룹 공유 에러 (루틴 등록): {e}")

# ===============================================
# ConversationHandler: 루틴 수정 로직 (/edit)
# ===============================================
CHOOSING_NEW_NAME = 3

async def edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_group_chat_with_redirect(update, context):
        return ConversationHandler.END
    user_id = str(update.message.from_user.id)
    
    try:
        routines_records = await asyncio.to_thread(routines_sheet.get_all_values)
    except Exception as e:
        await update.message.reply_text("데이터를 불러오는 중 오류가 발생했습니다.")
        return ConversationHandler.END

    active_routines = []
    for i, row in enumerate(routines_records[1:]):
        if len(row) > 1 and str(row[1]) == user_id:
            if len(row) >= 6 and row[5] == "active":
                active_routines.append({"row_num": i + 2, "name": row[2]})

    if not active_routines:
        await update.message.reply_text("👀 현재 수정 가능한 액티브(active) 상태의 루틴이 없습니다.")
        return ConversationHandler.END

    keyboard = []
    for r in active_routines:
        keyboard.append([InlineKeyboardButton(f"✏️ {r['name']}", callback_data=f"edit_{r['row_num']}")])
    keyboard.append([InlineKeyboardButton("❌ 취소", callback_data="edit_cancel")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("✏️ 이름을 수정하고 싶은 루틴을 선택해주세요.", reply_markup=reply_markup)
    return CHOOSING_NEW_NAME

async def edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "edit_cancel":
        await query.edit_message_text("❌ 수정이 취소되었습니다.")
        return ConversationHandler.END
        
    row_num = int(query.data.split('_')[1])
    context.user_data['edit_row_num'] = row_num
    
    current_name = await async_cell(routines_sheet, row_num, 3)
    
    await query.edit_message_text(
        f"현재 이름: **{current_name}**\n\n"
        f"👉 이 루틴의 새로운 이름을 입력해주세요. (1:1 대화방에 텍스트 전송)\n"
        f"취소하려면 `/cancel`을 입력하세요.",
        parse_mode='Markdown'
    )
    return CHOOSING_NEW_NAME

async def edit_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row_num = context.user_data.get('edit_row_num')
    new_name = update.message.text.strip()
    
    if not row_num:
        await update.message.reply_text("⚠️ 세션이 만료되었습니다. 다시 시도해 주세요.")
        context.user_data.clear()
        return ConversationHandler.END
        
    if new_name.startswith("/"):
        await update.message.reply_text("⚠️ 명령어가 아닌 올바른 이름을 입력해주세요.")
        return CHOOSING_NEW_NAME

    try:
        await async_update_cell(routines_sheet, row_num, 3, new_name)
        await update.message.reply_text(f"✅ 루틴 이름이 **{new_name}**(으)로 성공적으로 변경되었습니다!", parse_mode='Markdown')
        print(f"✏️ [루틴 수정] 행 {row_num} -> {new_name}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ 루틴 수정 중 오류가 발생했습니다: {e}")
        
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ 루틴 수정이 취소되었습니다.")
    context.user_data.clear()
    return ConversationHandler.END

# ===============================================
# 사진 인증 및 스트라이크 로직 (V2)
# ===============================================
async def process_auth(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, chat_id, routine_row, routine_id, routine_name, now_time, now_date, message_link, caption, query=None, base64_img=None, file_id=None):
    global daily_auth_count
    
    if chat_id not in daily_auth_count:
        daily_auth_count[chat_id] = {"date": "", "count": 0}
        
    if daily_auth_count[chat_id]["date"] != now_date:
        daily_auth_count[chat_id]["date"] = now_date
        daily_auth_count[chat_id]["count"] = 1
    else:
        daily_auth_count[chat_id]["count"] += 1
    current_count = daily_auth_count[chat_id]["count"]
 
    log_id = str(uuid.uuid4())
    # 8번째: sentiment_score ("", 빈 문자열 임시), 9번째(I열): routine_name 추가
    await async_append_row(logs_sheet, [log_id, routine_id, user_id, now_time, "success", message_link, caption, "", routine_name])
 
    points_to_add = 10
    streak_msg = ""
    
    try:
        user_cell = await async_find_in_col(users_sheet, user_id, column=1)
        if user_cell:
            u_row = user_cell.row
            current_points_str = await async_cell(users_sheet, u_row, 5)
            current_points = int(current_points_str) if current_points_str else 0
            
            # 루틴 누적 인증 횟수 업데이트
            if routine_row:
                streak_val = await async_cell(routines_sheet, routine_row, 8)
                streak = int(streak_val) if streak_val else 0
                streak += 1
                await async_update_cell(routines_sheet, routine_row, 8, streak)
                
                if streak >= 3:
                    points_to_add += 20
                    streak_msg = f"\n🔥 누적 {streak}회 인증 달성! 보너스 포인트 지급!! (+20점)"
                if streak >= 7:
                    points_to_add += 50
                    streak_msg = f"\n🔥 대기록! 누적 {streak}회 달성!! 보너스 왕창!! (+50점)"
 
            await async_update_cell(users_sheet, u_row, 5, current_points + points_to_add)
    except Exception as e:
        print(f"인증 보상 업데이트 에러: {e}")
 
    # 주간 달성률 계산 및 Weekly_Achievement 시트 업데이트
    rate_msg = ""
    try:
        if routine_row:
            frequency_val = await async_cell(routines_sheet, routine_row, 5)
            frequency = frequency_val if frequency_val else "everyday"
            weekly_done, weekly_rate = await update_weekly_achievement(
                routine_id, routine_name, user_id, frequency
            )
            weekly_target = get_weekly_target(frequency)
            user_rate = round((weekly_done / weekly_target) * 100, 0) if weekly_target > 0 else 0.0
            rate_msg = f"\n📊 이번 주 달성률: {user_rate:.0f}% ({weekly_done}/{weekly_target})"
    except Exception as e:
        print(f"달성률 업데이트 에러: {e}")
 
    praises = ["대단해요!", "멋집니다!", "최고! 이 기세로 내일도 파이팅!", "정말 대단한 끈기네요 🎉"]
    reply_msg = f"✅ 오늘 {current_count}번째 인증입니다! (+{points_to_add}점)\n{random.choice(praises)}{streak_msg}{rate_msg}"
    
    if query:
        await query.edit_message_text(reply_msg)
        user_obj = query.from_user
    else:
        await update.message.reply_text(reply_msg, reply_to_message_id=update.message.message_id)
        user_obj = update.message.from_user
    
    nickname = user_obj.first_name or user_obj.username or "회원"
    print(f"✅ [루틴 인증] {nickname} ({user_id}): {routine_name} (오늘 {current_count}번째)")
 
    # 그룹 채팅방 공유 (V2 고도화 - 멀티모달 AI 분석 연동)
    try:
        nickname = user_obj.first_name or user_obj.username or "회원"
        default_group_msg = (
            f"✅ **{nickname}**님이 루틴을 인증했습니다!\n\n"
            f"🔥 **{routine_name}**\n"
            f"{rate_msg.strip() if rate_msg else ''}\n\n"
            f"꾸준함이 실력입니다! 멋져요! 👏"
        )
        
        async def bg_auth_share_task(b64, cap, r_name, fid, name_u, d_msg):
            try:
                ai_comment = None
                if b64:
                    ai_comment = await generate_image_analysis(b64, cap, r_name)
                
                if ai_comment:
                    post_caption = (
                        f"✅ **{name_u}**님의 생생한 루틴 인증샷! 📸\n\n"
                        f"🔥 **{r_name}**\n"
                        f"{rate_msg.strip() if rate_msg else ''}\n\n"
                        f"🤖 **AI 코치 브리핑**:\n\"{ai_comment}\"\n\n"
                        f"💬 *이 루틴이나 주제에 관심이 있으신 분들은 아래에 자유롭게 의견이나 응원 댓글을 달아주세요!* 👇"
                    )
                else:
                    post_caption = d_msg + "\n\n💬 *이 루틴이나 주제에 관심이 있으신 분들은 아래에 자유롭게 의견이나 응원 댓글을 달아주세요!* 👇"
                
                if fid:
                    await context.bot.send_photo(chat_id=GROUP_CHAT_ID, photo=fid, caption=post_caption, parse_mode='Markdown')
                else:
                    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=post_caption, parse_mode='Markdown')
            except Exception as ex:
                print(f"인증샷 그룹방 공유 백그라운드 태스크 실패: {ex}")
                try:
                    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=d_msg, parse_mode='Markdown')
                except:
                    pass
 
        asyncio.create_task(bg_auth_share_task(base64_img, caption, routine_name, file_id, nickname, default_group_msg))
    except Exception as e:
        print(f"그룹 공유 태스크 생성 에러 (인증): {e}")

async def auth_routine_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    
    data_parts = query.data.split('_')
    if query.data.startswith('auth_cancel_'):
        msg_id = data_parts[2]
        if msg_id in context.user_data:
            del context.user_data[msg_id]
        await query.edit_message_text("❌ 인증이 취소되었습니다.")
        return
 
    msg_id = data_parts[1]
    routine_row = int(data_parts[2])
    
    auth_data = context.user_data.get(msg_id)
    if not auth_data:
        await query.edit_message_text("⚠️ 인증 정보가 만료되었거나 이미 처리되었습니다.")
        return
 
    routine_id = await async_cell(routines_sheet, routine_row, 1)
    routine_name = auth_data.get("routines", {}).get(routine_row, "알 수 없는 루틴")
 
    await process_auth(
        update=update, context=context, user_id=user_id, 
        chat_id=auth_data["chat_id"], routine_row=routine_row, routine_id=routine_id,
        routine_name=routine_name,
        now_time=auth_data["now_time"], now_date=auth_data["now_date"], 
        message_link=auth_data["message_link"], caption=auth_data["caption"],
        query=query,
        base64_img=auth_data.get("base64_img"), file_id=auth_data.get("file_id")
    )
    
    del context.user_data[msg_id]
 
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
    global daily_auth_count
    user_id = str(update.message.from_user.id)
    chat_id = str(update.message.chat_id)
    caption = update.message.caption or "내용 없음"
    now_dt = datetime.now()
    now_date = now_dt.strftime("%Y-%m-%d")
    now_time = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    
    if caption == "내용 없음":
        return
 
    photo_id = update.message.photo[-1].file_id
    message_link = update.message.link
    if not message_link:
        file_info = await context.bot.get_file(photo_id)
        message_link = file_info.file_path
        
    # 멀티모달용 이미지 base64 인코딩
    base64_img = None
    try:
        file_info = await context.bot.get_file(photo_id)
        file_bytes = await file_info.download_as_bytearray()
        base64_img = base64.b64encode(file_bytes).decode('utf-8')
    except Exception as e:
        print(f"이미지 base64 다운로드/인코딩 에러: {e}")
        
    try:
        routines_records = await asyncio.to_thread(routines_sheet.get_all_values)
    except Exception as e:
        await update.message.reply_text("데이터를 불러오는 중 오류가 발생했습니다.")
        return
 
    active_routines = []
    for i, row in enumerate(routines_records[1:]):
        if len(row) > 1 and str(row[1]) == user_id:
            if len(row) >= 6 and row[5] == "active":
                active_routines.append({"row": i + 2, "id": row[0], "name": row[2]})
 
    if not active_routines:
        await update.message.reply_text("👀 현재 진행 중인 루틴이 없습니다. `/reg` 명령어로 먼저 목표를 만들어보세요!")
        return
 
    if len(active_routines) == 1:
        await process_auth(
            update=update, context=context, user_id=user_id, chat_id=chat_id, 
            routine_row=active_routines[0]["row"], routine_id=active_routines[0]["id"],
            routine_name=active_routines[0]["name"],
            now_time=now_time, now_date=now_date, message_link=message_link, caption=caption,
            base64_img=base64_img, file_id=photo_id
        )
    else:
        msg_id = str(update.message.message_id)
        routine_names = {r["row"]: r["name"] for r in active_routines}
        context.user_data[msg_id] = {
            "now_time": now_time,
            "now_date": now_date,
            "message_link": message_link,
            "caption": caption,
            "chat_id": chat_id,
            "routines": routine_names,
            "base64_img": base64_img,
            "file_id": photo_id
        }
        
        keyboard = []
        for r in active_routines:
            cb_data = f"auth_{msg_id}_{r['row']}"
            keyboard.append([InlineKeyboardButton(f"✅ {r['name']}", callback_data=cb_data)])
        keyboard.append([InlineKeyboardButton("❌ 취소", callback_data=f"auth_cancel_{msg_id}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        msg_text = "📸 여러 개의 루틴이 진행 중이네요! 어떤 루틴을 인증하시겠어요?"
        await update.message.reply_text(msg_text, reply_markup=reply_markup, reply_to_message_id=update.message.message_id)

# ===============================================
# 인사이트 공유
# ===============================================
async def insight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_group_chat_with_redirect(update, context):
        return
    user_id = str(update.message.from_user.id)
    text = update.message.text.replace("/insight", "").strip()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not text:
        await update.message.reply_text(
            "💡 인사이트 내용을 함께 입력해주세요!\n예) /insight 오늘 루틴에서 느낀 점",
            reply_to_message_id=update.message.message_id
        )
        return

    insight_id = str(uuid.uuid4())
    await async_append_row(insights_sheet, [insight_id, user_id, now, text, "TRUE", ""])
    
    user_cell = await async_find_in_col(users_sheet, user_id)
    if user_cell:
        row_num = user_cell.row
        current_shield_str = await async_cell(users_sheet, row_num, 4)
        current_points_str = await async_cell(users_sheet, row_num, 5)
        
        current_shield = int(current_shield_str) if current_shield_str else 0
        current_points = int(current_points_str) if current_points_str else 0
        
        await async_update_cell(users_sheet, row_num, 4, current_shield + 1)
        await async_update_cell(users_sheet, row_num, 5, current_points + 15)
        
        user_name = await async_cell(users_sheet, row_num, 2)
        await update.message.reply_text(
            f"🛡️ {user_name}님이 멋진 인사이트로 포인트를 획득했습니다!\n(+15점 획득)",
            reply_to_message_id=update.message.message_id
        )

        # 그룹 채팅방 공유 (V2 추가)
        try:
            group_msg = f"💡 {user_name}님이 새로운 인사이트를 공유했습니다!\n\n\"{text}\"\n\n훌륭한 배움입니다! 🚀"
            await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=group_msg)
        except Exception as e:
            print(f"그룹 공유 에러 (인사이트): {e}")

        async def bg_keyword_task(t_insight_id, t_text, u_name):
            keywords = await generate_insight_keywords(t_text)
            if keywords:
                cell = await async_find_in_col(insights_sheet, t_insight_id)
                if cell:
                    await async_update_cell(insights_sheet, cell.row, 6, keywords)
                    
            try:
                summary_data = await generate_insight_summary(t_text)
                category = "자기계발"
                summary = t_text[:50] + "..."
                if summary_data and isinstance(summary_data, dict):
                    category = summary_data.get("category", "자기계발")
                    summary = summary_data.get("summary", summary)
                
                archive_msg = (
                    f"🧠 **산스 루틴클럽 지식 아카이브** 🧠\n\n"
                    f"👤 **작성자**: {u_name}님\n"
                    f"📁 **분류 카테고리**: {category}\n"
                    f"💡 **한 줄 핵심 요약**: {summary}\n\n"
                    f"📝 **인사이트 상세**:\n"
                    f"\"{t_text}\""
                )
                
                kwargs = {"chat_id": INSIGHT_CHAT_ID, "text": archive_msg, "parse_mode": "Markdown"}
                if INSIGHT_THREAD_ID:
                    kwargs["message_thread_id"] = INSIGHT_THREAD_ID
                    
                await context.bot.send_message(**kwargs)
                print(f"🧠 [인사이트 아카이빙] 토픽 {INSIGHT_THREAD_ID}에 성공적으로 포스트 완료")
            except Exception as ex:
                print(f"인사이트 아카이빙 전송 중 오류: {ex}")

        asyncio.create_task(bg_keyword_task(insight_id, text, user_name))

# ===============================================
# 상태, 삭제 로직
# ===============================================
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    
    try:
        routines_records = await asyncio.to_thread(routines_sheet.get_all_values)
    except Exception as e:
        await update.message.reply_text("데이터를 불러오는 중 오류가 발생했습니다.")
        return
        
    if len(routines_records) <= 1:
        await update.message.reply_text("👀 아직 등록된 루틴이 없네요! `/reg 매일독서10쪽` 으로 먼저 목표를 만들어보세요.")
        return
        
    user_routines = [row for row in routines_records[1:] if len(row) > 1 and str(row[1]) == user_id]
        
    if not user_routines:
        await update.message.reply_text("👀 아직 등록된 루틴이 없네요! `/reg 매일독서10쪽` 으로 먼저 목표를 만들어보세요.")
        return
        
    # Weekly_Achievement 시트에서 현재 주차 데이터 조회
    week_id, _ = get_current_week_info()
    try:
        wa_records = await asyncio.to_thread(weekly_achievement_sheet.get_all_values)
    except Exception:
        wa_records = []

    # routine_id → (weekly_done, weekly_rate) 매핑
    wa_map = {}
    for wa_row in wa_records[1:]:
        if len(wa_row) >= 9 and wa_row[0] == week_id:
            wa_map[wa_row[3]] = (wa_row[7], wa_row[8])  # (weekly_done, weekly_rate)

    reply_text = "📊 **나의 루틴 현황 모니터링** 📊\n\n"
    has_active = False
    
    for row_data in user_routines:
        if len(row_data) < 6: continue
        
        routine_name = row_data[2]
        routine_id = row_data[0]
        status_val = row_data[5]
        streak_val = row_data[7] if len(row_data) > 7 else "0"
        
        if status_val == "active":
            has_active = True
            frequency_val = row_data[4] if len(row_data) > 4 else "everyday"
            weekly_target = get_weekly_target(frequency_val)
            wa_data = wa_map.get(routine_id)
            if wa_data:
                weekly_done_val = int(wa_data[0]) if wa_data[0] else 0
            else:
                weekly_done_val = 0
            
            user_rate = round((weekly_done_val / weekly_target) * 100, 0) if weekly_target > 0 else 0.0
            reply_text += f"🔹 **{routine_name}**\n"
            reply_text += f"   🔥 누적 인증 횟수: {streak_val}회\n"
            reply_text += f"   📊 이번 주 달성률: {user_rate:.0f}% ({weekly_done_val}/{weekly_target})\n\n"
            
    if not has_active:
        reply_text = "👀 현재 진행 중인 액티브(active) 상태의 루틴이 없습니다!"
    await update.message.reply_text(reply_text, parse_mode='Markdown')

async def delete_routine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_group_chat_with_redirect(update, context):
        return
    user_id = str(update.message.from_user.id)
    try:
        routines_records = await asyncio.to_thread(routines_sheet.get_all_values)
    except Exception as e:
        await update.message.reply_text("데이터를 불러오는 중 오류가 발생했습니다.")
        return
        
    if len(routines_records) <= 1:
        await update.message.reply_text("👀 현재 활성화된 삭제할 루틴이 없습니다.")
        return
        
    user_routines_with_row = []
    # get_all_values returns list of lists (0-indexed). Sheet rows are 1-indexed. row 1 is header.
    for i, row in enumerate(routines_records[1:]):
        if len(row) > 1 and str(row[1]) == user_id:
            user_routines_with_row.append({"row_num": i + 2, "data": row})
            
    keyboard = []
    for r_obj in user_routines_with_row:
        row_data = r_obj["data"]
        row_num = r_obj["row_num"]
        if len(row_data) >= 6 and row_data[5] == "active":
            keyboard.append([InlineKeyboardButton(f"🗑️ {row_data[2]}", callback_data=f"del_{row_num}")])
    
    if not keyboard:
        await update.message.reply_text("👀 현재 활성화된 삭제할 루틴이 없습니다.")
        return
        
    keyboard.append([InlineKeyboardButton("❌ 취소", callback_data="cancel_del")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🛑 삭제하고 싶은 루틴을 선택해주세요.", reply_markup=reply_markup)

async def del_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'cancel_del':
        await query.edit_message_text("취소되었습니다.")
        return
        
    row_num = int(query.data.split('_')[1])
    await async_delete_rows(routines_sheet, row_num)
    await query.edit_message_text("🗑️ 성공적으로 삭제 및 초기화되었습니다.")

# ===============================================
# 랭킹 시스템 (게이미피케이션)
# ===============================================
async def show_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        users_records = await async_get_all_records(users_sheet)
    except Exception as e:
        print("랭킹 로드 실패", e)
        return
        
    if not users_records:
        await update.message.reply_text("아직 등록된 사용자가 없습니다.")
        return
        
    # 포인트 기준 정렬
    # gspread get_all_records()는 첫 번째 행을 딕셔너리의 키로 사용합니다.
    # 사용자의 시트 첫 번째 행이 어떻게 구성되어 있는지 알 수 없으나 생성 시 구조상 컬럼 인덱스로 가져오는 것이 안전할 수 있습니다.
    
    # 2행부터 모든 데이터 가져오기
    try:
        users_values = await async_findall_in_col(users_sheet, "", column=1) # 1열이 비어있지 않은 모든 셀 찾기는 안됨
        users_records = await asyncio.to_thread(users_sheet.get_all_values)
        
        if len(users_records) <= 1:
            await update.message.reply_text("아직 등록된 사용자가 없습니다.")
            return
            
        # 첫행(헤더) 제외
        users_data = users_records[1:]
        
        # 5번째 컬럼(index 4)이 포인트, 2번째 컬럼(index 1)이 닉네임으로 판단 (등록 로직 기준)
        parsed_users = []
        for row in users_data:
            if len(row) < 5:
                continue
            nickname = row[1] if row[1] else "회원"
            try:
                pts = int(row[4]) if row[4] else 0
            except ValueError:
                pts = 0
            parsed_users.append({"Nickname": nickname, "Points": pts})
            
        sorted_users = sorted(parsed_users, key=lambda x: x["Points"], reverse=True)
        
        reply = "🏆 **산스 AI루틴클럽 명예의 전당** 🏆\n\n"
        for i, user in enumerate(sorted_users[:3]):
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉"
            reply += f"{medal} {user['Nickname']} - {user['Points']}점\n"

        # 전체 누적 인증 수 및 최초 인증일 계산
        try:
            logs_records_all = await asyncio.to_thread(logs_sheet.get_all_values)
            total_auths = 0
            earliest_date = None
            for log_row in logs_records_all[1:]:
                if len(log_row) > 4 and log_row[4] == "success":
                    total_auths += 1
                    try:
                        log_dt = datetime.strptime(log_row[3][:10], "%Y-%m-%d")
                        if earliest_date is None or log_dt < earliest_date:
                            earliest_date = log_dt
                    except (ValueError, IndexError):
                        pass
            if total_auths > 0 and earliest_date:
                days_elapsed = (datetime.now() - earliest_date).days
                reply += f"\n🌟 {days_elapsed}일간 총 {total_auths}개의 루틴 인증이 진행되었습니다!\n모두 정말 고생 많으셨어요, 앞으로도 함께 파이팅! 💪🔥"
        except Exception as e:
            print(f"누적 인증 수 계산 오류: {e}")

        await update.message.reply_text(reply, parse_mode='Markdown')
    except Exception as e:
        print("랭킹 연산 오류:", e)
        await update.message.reply_text("랭킹을 불러오는 중 오류가 발생했습니다.")

# ===============================================
# JobQueue 스케줄러를 활용한 PUSH 시스템 (V2)
# ===============================================
async def morning_job(context: ContextTypes.DEFAULT_TYPE, target_chat_id: str = None):
    """매일 KST 09:00 (UTC 00:00)에 그룹방에 아침 시작 메시지를 발송합니다."""
    chat_id = target_chat_id or GROUP_CHAT_ID
    if not chat_id:
        print("⚠️ GROUP_CHAT_ID가 설정되지 않아 아침 메시지를 발송하지 않습니다.")
        return
    msg = (
        "🌅 굿모닝! 산스 AI루틴클럽원분들 오늘도 파이팅입니다! 💪\n\n"
        "하루의 시작을 루틴과 함께하면 달라집니다.\n"
        "오늘 나의 루틴을 확인하고 건강한 하루를 시작해보세요! 🌱\n\n"
        "📸 사진+캡션으로 인증해주시면 포인트가 자동으로 쌓입니다!"
    )
    try:
        await context.bot.send_message(chat_id=chat_id, text=msg)
    except Exception as e:
        print(f"아침 메시지 발송 실패: {e}")

async def daily_dashboard_job(context: ContextTypes.DEFAULT_TYPE, target_chat_id: str = None):
    """매일 KST 18:00에 일일 요약 대시보드와 함께 퇴근길 리마인더 메시지를 그룹방에 발송합니다."""
    chat_id = target_chat_id or GROUP_CHAT_ID
    if not chat_id:
        print("⚠️ chat_id가 설정되지 않아 대시보드를 발송하지 않습니다.")
        return
        
    try:
        now_date = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        week_id, week_start_str = get_current_week_info()
        
        # 1. 오늘 인증 내역 취합 및 이번 주차 누적 내역 취합 (Logs 시트 조회)
        logs_records = await asyncio.to_thread(logs_sheet.get_all_values)
        
        # 유저 닉네임 매핑을 위해 Users 조회
        users_records = await asyncio.to_thread(users_sheet.get_all_values)
        uid_to_nickname = {}
        for row in users_records[1:]:
            if row and len(row) >= 2:
                uid_to_nickname[str(row[0])] = row[1] or "회원"

        today_done_count = 0
        today_highlights = []
        weekly_counts = {}
        today_user_ids = set()

        for row in logs_records[1:]:
            if len(row) < 5:
                continue
            uid = str(row[2])
            status = row[4]
            log_time_str = row[3]
            routine_name = row[8] if len(row) > 8 else "루틴"
            caption = row[6] if len(row) > 6 else ""

            # 오늘 성공 인증 판별 (success)
            if log_time_str.startswith(now_date) and status == "success":
                today_done_count += 1
                nickname = uid_to_nickname.get(uid, "회원")
                today_highlights.append({
                    "nickname": nickname,
                    "routine": routine_name,
                    "caption": caption if (caption and caption != "내용 없음") else "루틴 인증을 완료했습니다! 👍"
                })
                today_user_ids.add(uid)

            # 이번 주차(월요일 이후) 성공 인증 판별
            if log_time_str >= week_start_str and status == "success":
                nickname = uid_to_nickname.get(uid, "회원")
                weekly_counts[nickname] = weekly_counts.get(nickname, 0) + 1
                
        # 2. 오늘 아직 인증 안 한 미인증자 목록 구하기
        routines_records = await asyncio.to_thread(routines_sheet.get_all_values)
        active_user_ids = set()
        for row in routines_records[1:]:
            if len(row) >= 6 and row[5] == "active":
                active_user_ids.add(str(row[1]))
                
        pending_users = []
        for uid in active_user_ids:
            if uid not in today_user_ids:
                name = uid_to_nickname.get(uid, "회원")
                pending_users.append(name)
                
        pending_users_str = ", ".join(pending_users) if pending_users else "모두 완료! 🎉"
        
        # 3. 이번 주 누적 인증 레이스 (Top 5) 조립
        sorted_weekly = sorted(weekly_counts.items(), key=lambda x: x[1], reverse=True)
        weekly_race_lines = []
        for i, (nick, count) in enumerate(sorted_weekly[:5]):
            medal = "🏆" if i == 0 else "✨"
            weekly_race_lines.append(f"  {medal} **{nick}**님 ➜ 누적 **{count}회** 인증 달성! 🔥")
        weekly_race_str = "\n".join(weekly_race_lines) if weekly_race_lines else "  이번 주 인증 레이스가 곧 진행됩니다!"

        # 4. 오늘 멤버들의 생생한 인증 톡 소개 조립
        highlights_lines = []
        for h in today_highlights[:6]:
            highlights_lines.append(f"  ✍️ **{h['nickname']}**님: [{h['routine']}]\n    ➜ \"_{h['caption']}_\"")
        highlights_str = "\n".join(highlights_lines) if highlights_lines else "  아직 오늘 등록된 소감이 없습니다. 첫 주인공이 되어보세요! 💫"

        dashboard_msg = (
            f"┌──────────────────────────────┐\n"
            f"│    📢 오늘의 산스 루틴 종합 대시보드   │\n"
            f"├──────────────────────────────┤\n"
            f"│  🔥 이번 주 총 **{today_done_count}개**의 루틴 인증 완료!\n"
            f"│\n"
            f"│  🏆 **이번 주 누적 인증 레이스 (Top 5)**\n"
            f"{weekly_race_str}\n"
            f"│\n"
            f"│  💬 **오늘 우리 멤버들의 생생한 인증 톡**\n"
            f"{highlights_str}\n"
            f"│\n"
            f"│  ⏳ **이번 주 인증 대기 현황**\n"
            f"│  ➜ 인증 대기 중: {pending_users_str}\n"
            f"└──────────────────────────────┘\n\n"
            f"🌅 퇴근 시간이 되었습니다! 오늘 루틴 인증을 아직 완료하지 않은 분들이 계시다면 지금 바로 1:1 대화방에서 인증해 보세요! 🙌\n\n"
            f"📸 사진+캡션으로 간편하게 인증하고 포인트를 적립해 보세요! ✨"
        )
        
        await context.bot.send_message(chat_id=chat_id, text=dashboard_msg, parse_mode='Markdown')
        print(f"📊 [일일 대시보드] 오늘 인증 {today_done_count}건 발송 완료 (Target: {chat_id})")
    except Exception as e:
        print(f"일일 대시보드 발송 실패: {e}")

async def daily_reminder_job(context: ContextTypes.DEFAULT_TYPE, target_chat_id: str = None):
    """매일 KST 21:00에 오늘 마감 전 마지막 루틴 인증을 독려하는 리마인더를 발송합니다."""
    chat_id = target_chat_id or GROUP_CHAT_ID
    if not chat_id:
        return
        
    msg = (
        "🌙 오늘 하루도 정말 고생 많으셨어요!\n\n"
        "오늘 루틴 인증을 마감하기까지 얼마 남지 않았습니다. 🙌\n"
        "하루를 정리하며 딱 5분이라도 내 자신과의 약속을 지켜보는 것은 어떨까요?\n\n"
        "📸 아직 인증 전이시라면 사진+캡션으로 간편하게 기록을 남겨보세요! 오늘도 포인트는 쌓입니다! ✨"
    )
    try:
        await context.bot.send_message(chat_id=chat_id, text=msg)
    except Exception as e:
        print(f"마감 리마인더 발송 실패: {e}")

async def test_rec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용: 명령어를 입력한 본인에게만 AI 루틴 추천을 발송합니다."""
    user_id = str(update.message.from_user.id)
    await update.message.reply_text("⏳ AI 파워로 루틴 추천을 생성 중입니다... 잠시만 기다려주세요!")
    await monthly_rec_job(context, target_user_id=user_id)
    await update.message.reply_text("✅ 완료! 1:1 채팅으로 추천 결과를 확인해보세요.")

async def test_morning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용: 아침 메시지 스케줄러를 즉시 실행하여 명령어를 친 대화방에 발송합니다."""
    target_chat_id = str(update.message.chat_id)
    await morning_job(context, target_chat_id=target_chat_id)
    await update.message.reply_text("✅ 아침 메시지 발송 테스트 완료! (명령어 입력 방으로 전송되었습니다.)")

async def test_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용: 일일 대시보드 스케줄러를 즉시 실행하여 명령어를 친 대화방에 발송합니다."""
    target_chat_id = str(update.message.chat_id)
    await update.message.reply_text("⏳ 일일 요약 대시보드 집계 및 발송 중...")
    await daily_dashboard_job(context, target_chat_id=target_chat_id)
    await update.message.reply_text("✅ 일일 요약 대시보드 발송 테스트 완료! (명령어 입력 방으로 전송되었습니다.)")

async def test_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용: 저녁 마감 리마인더를 즉시 실행하여 명령어를 친 대화방에 발송합니다."""
    target_chat_id = str(update.message.chat_id)
    await daily_reminder_job(context, target_chat_id=target_chat_id)
    await update.message.reply_text("✅ 마감 리마인더 발송 테스트 완료! (명령어 입력 방으로 전송되었습니다.)")

CATALYST_RUN_WEEKDAYS = {0, 4, 5}  # Monday, Friday, Saturday
CATALYST_WEEKDAY_THEMES = {
    0: "월요일: AI를 활용한 짧은 글쓰기 미션. 회고, 선언문, 응원글, 배운 점 정리처럼 텍스트 결과물을 만들게 하세요.",
    4: "금요일: AI 이미지 혹은 동영상 생성 미션. 한 주의 감정, 성과, 아이디어를 시각 결과물로 만들게 하세요.",
    5: "토요일: 내게 필요한 간단한 토이 서비스 만들어보기 미션. 작은 자동화, 계산기, 체크리스트, 랜딩 초안 등 실행 가능한 미니 도구를 만들게 하세요.",
}


def _claim_catalyst_scheduled_run(run_date: str) -> bool:
    """Return False when another process already claimed today's scheduled catalyst."""
    try:
        os.makedirs(CATALYST_STATE_DIR, exist_ok=True)
        lock_path = os.path.join(CATALYST_STATE_DIR, f"catalyst_{run_date}.lock")
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
            lock_file.write(datetime.now(ZoneInfo("Asia/Seoul")).isoformat())
        return True
    except FileExistsError:
        return False
    except Exception as e:
        print(f"⚠️ [소성취 촉매제] 중복 방지 락 생성 실패, 발송을 중단합니다: {e}")
        return False


async def daily_catalyst_job(
    context: ContextTypes.DEFAULT_TYPE,
    target_chat_id: str = None,
    target_thread_id: int = None,
    force: bool = False,
    scheduled: bool = True,
) -> bool:
    """월/금/토 KST 15:30에 AI 소성취 소통 촉매제 챌린지 메시지를 발송합니다."""
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    if not force and now_kst.weekday() not in CATALYST_RUN_WEEKDAYS:
        print(f"🚀 [소성취 촉매제] 실행 요일이 아니어서 생략합니다. (weekday={now_kst.weekday()})")
        return False

    if scheduled and not _claim_catalyst_scheduled_run(now_kst.strftime("%Y-%m-%d")):
        print(f"🚀 [소성취 촉매제] 오늘 예약 발송은 이미 처리되어 생략합니다. ({now_kst:%Y-%m-%d})")
        return False

    chat_id = target_chat_id or CATALYST_CHAT_ID
    thread_id = target_thread_id if target_thread_id is not None else CATALYST_THREAD_ID
    if not chat_id:
        print("⚠️ chat_id가 설정되지 않아 촉매제 메시지를 발송하지 않습니다.")
        return False
        
    try:
        mission_theme = CATALYST_WEEKDAY_THEMES.get(now_kst.weekday(), CATALYST_WEEKDAY_THEMES[0])
        challenge_text = await generate_catalyst_mission(mission_theme)
        if not challenge_text:
            print("⚠️ [소성취 촉매제] AI 미션 생성 실패/빈 응답으로 발송을 생략합니다.")
            return False
            
        msg = (
            f"🚀 **산스 AI루틴클럽 데일리 소성취 챌린지** 🚀\n\n"
            f"{challenge_text}"
        )
        send_kwargs = {"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}
        if thread_id:
            send_kwargs["message_thread_id"] = thread_id
        try:
            await context.bot.send_message(**send_kwargs)
        except Exception as ex:
            print(f"⚠️ [소성취 촉매제] 마크다운 발송 실패, 일반 텍스트 폴백 시도: {ex}")
            clean_msg = msg.replace("**", "").replace("*", "").replace("_", "").replace("`", "")
            clean_kwargs = {"chat_id": chat_id, "text": clean_msg}
            if thread_id:
                clean_kwargs["message_thread_id"] = thread_id
            await context.bot.send_message(**clean_kwargs)
            
        print(f"🚀 [소성취 촉매제] 챌린지 메시지 발송 완료 (Target: {chat_id}, Thread: {thread_id})")
        return True
    except Exception as e:
        print(f"소성취 촉매제 발송 실패: {e}")
        raise e

async def test_catalyst(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용: 데일리 촉매제 챌린지 메시지를 즉시 생성하여 명령어 입력 방에 발송합니다."""
    target_chat_id = str(update.message.chat_id)
    target_thread_id = update.message.message_thread_id
    await update.message.reply_text("⏳ AI가 데일리 촉매제 챌린지를 창작 중입니다...")
    try:
        sent = await daily_catalyst_job(
            context,
            target_chat_id=target_chat_id,
            target_thread_id=target_thread_id,
            force=True,
            scheduled=False,
        )
        if sent:
            await update.message.reply_text("✅ 데일리 촉매제 챌린지 발송 테스트 완료! (명령어 입력 방으로 전송되었습니다.)")
        else:
            await update.message.reply_text("⚠️ AI 미션을 생성하지 못해 데일리 촉매제 챌린지를 발송하지 않았습니다.")
    except Exception as e:
        await update.message.reply_text(f"❌ 데일리 촉매제 챌린지 발송 실패: {e}")

async def initialize_weekly_achievement(context: ContextTypes.DEFAULT_TYPE):
    """매주 월요일 00:01 KST(UTC 일요일 15:01)에 실행: 모든 활성 루틴을 주간 달성률 시트에 미리 등록합니다."""
    week_id, week_start_str = get_current_week_info()
    
    # 0. 지난주 출석률 정산 및 업데이트
    try:
        now_dt = datetime.now()
        last_week_dt = now_dt - timedelta(weeks=1)
        iso_year, iso_week, _ = last_week_dt.isocalendar()
        last_week_id = f"{iso_year}-W{iso_week:02d}"
        
        print(f"📊 [스케줄러] 지난주({last_week_id}) 출석률 정산 시작...")
        await update_attendance_sheet(last_week_id)
        print(f"📊 [스케줄러] 지난주({last_week_id}) 출석률 정산 완료!")
    except Exception as e:
        print(f"⚠️ [스케줄러] 지난주 출석률 정산 중 에러 발생: {e}")

    try:
        # 1. 모든 루틴 가져오기
        routines_records = await asyncio.to_thread(routines_sheet.get_all_values)
        if len(routines_records) <= 1:
            print("등록된 루틴이 없습니다.")
            return

        active_routines = []
        for i, row in enumerate(routines_records[1:]):
            if len(row) >= 6 and row[5] == "active":
                # routine_id, user_id, routine_name, frequency
                active_routines.append({
                    "routine_id": row[0],
                    "user_id": row[1],
                    "name": row[2],
                    "frequency": row[4]
                })

        if not active_routines:
            print("활성화된 루틴이 없습니다.")
            return

        # 2. 이번 주차에 이미 등록된 루틴 확인
        wa_records = await asyncio.to_thread(weekly_achievement_sheet.get_all_values)
        existing_routines = set()
        for row in wa_records[1:]:
            if len(row) >= 4 and row[0] == week_id:
                existing_routines.add(row[3]) # routine_id

        # 3. 누락된 루틴 추가
        added_count = 0
        for r in active_routines:
            if r["routine_id"] not in existing_routines:
                weekly_target = get_weekly_target(r["frequency"])
                # [week_id, week_start_str, user_id, routine_id, routine_name, frequency, weekly_target, weekly_done]
                new_row = [week_id, week_start_str, r["user_id"], r["routine_id"], r["name"], r["frequency"], weekly_target, 0]
                await async_append_row(weekly_achievement_sheet, new_row)
                
                # 수식 삽입을 위해 새로 추가된 행 번호 찾기 (async_append_row는 끝에 추가함)
                # 성능을 위해 전체를 다시 읽는 것보다 현재 행 수를 사용하는게 좋지만 안전을 위해 소폭 지연 후 다시 읽거나 예측
                # 여기서는 예측하여 수식 삽입
                current_total_rows = len(wa_records) + added_count + 1
                formula = f"=MIN(H{current_total_rows}/G{current_total_rows}, 1)*100"
                await asyncio.to_thread(weekly_achievement_sheet.update_acell, f"I{current_total_rows}", formula)
                
                added_count += 1
        
        print(f"주간 초기화 완료: {added_count}개 루틴 추가됨")
    except Exception as e:
        print(f"주간 초기화 중 에러 발생: {e}")

async def test_init_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용: 주간 달성률 초기화 스케줄러를 즉시 실행합니다."""
    await update.message.reply_text("⏳ 주간 달성률 초기화를 시작합니다...")
    await initialize_weekly_achievement(context)
    await update.message.reply_text("✅ 주간 달성률 초기화 테스트 완료!")

async def weekly_top_job(context: ContextTypes.DEFAULT_TYPE, target_chat_id: str = None):
    """매주 일요일 KST 12:00 (UTC 03:00)에 이번 주 TOP 3 루틴 인증자를 그룹방에 발송합니다."""
    chat_id = target_chat_id or GROUP_CHAT_ID
    if not chat_id:
        print("⚠️ chat_id가 설정되지 않아 주간 리더보드를 발송하지 않습니다.")
        return

    try:
        from datetime import timedelta
        now = datetime.now()
        # 이번 주 월요일 00:00:00 계산
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

        # Logs 시트 전체 조회
        logs_records = await asyncio.to_thread(logs_sheet.get_all_values)
        if len(logs_records) <= 1:
            print("이번 주 인증 로그 없음 — 메시지 발송 생략")
            return

        # 이번 주 범위 로그 필터링 (col3=user_id, col4=timestamp, col5=status, col9=routine_name)
        week_counts = {}   # {user_id: int}
        week_routines = {} # {user_id: set of routine names}
        for row in logs_records[1:]:
            if len(row) < 5:
                continue
            status = row[4] if len(row) > 4 else ""
            if status != "success":
                continue
            try:
                log_time = datetime.strptime(row[3][:19], "%Y-%m-%d %H:%M:%S")
            except (ValueError, IndexError):
                continue
            if log_time < week_start:
                continue
            uid = str(row[2])
            week_counts[uid] = week_counts.get(uid, 0) + 1
            routine_name_log = row[8] if len(row) > 8 else ""
            if uid not in week_routines:
                week_routines[uid] = set()
            if routine_name_log:
                week_routines[uid].add(routine_name_log)

        if not week_counts:
            print("이번 주 인증 로그 없음 — 메시지 발송 생략")
            return

        # 인증 횟수 내림차순 상위 3명
        sorted_users = sorted(week_counts.items(), key=lambda x: x[1], reverse=True)[:3]

        # Users 시트에서 닉네임 조회
        users_records = await asyncio.to_thread(users_sheet.get_all_values)
        uid_to_nickname = {}
        for row in users_records[1:]:
            if row and len(row) >= 2:
                uid_to_nickname[str(row[0])] = row[1] or "회원"

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (uid, count) in enumerate(sorted_users):
            nickname = uid_to_nickname.get(uid, "회원")
            routines = week_routines.get(uid, set())
            routine_str = ", ".join(routines) if routines else "기록 없음"
            lines.append(f"{medals[i]} {nickname} — {count}회 인증\n   └ 루틴: {routine_str}")

        leaderboard = "\n".join(lines)
        total_weekly_auths = sum(week_counts.values())
        msg = (
            f"🏆 이번 주 산스 AI루틴클럽 TOP 3 발표! 🏆\n\n"
            f"정말 대단한 한 주를 보내셨네요! 👏\n\n"
            f"{leaderboard}\n\n"
            f"🌟 이번주 총 {total_weekly_auths}개의 루틴 인증이 진행되었습니다!\n"
            f"모두 정말 고생 많으셨어요, 앞으로도 함께 파이팅! 💪🔥\n\n"
            f"이번 주 루틴을 통해 어떤 변화나 인사이트를 느끼셨나요? 💡\n"
            f"/insight 명령어로 공유해주시면 포인트를 드립니다!"
        )
        await context.bot.send_message(chat_id=chat_id, text=msg)
    except Exception as e:
        print(f"Weekly TOP 3 Job Error: {e}")

async def weekly_card_news_job(context: ContextTypes.DEFAULT_TYPE, target_chat_id: str = None):
    """이번 주 주목 루틴 4개를 선정하고 6장의 카드뉴스 이미지를 생성하여 그룹방에 발송합니다."""
    from telegram import InputMediaPhoto
    chat_id = target_chat_id or GROUP_CHAT_ID
    if not chat_id:
        print("⚠️ chat_id가 설정되지 않아 주간 카드뉴스를 발송하지 않습니다.")
        return

    try:
        now = datetime.now()
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

        # Logs 시트에서 이번 주 인증 데이터 수집
        logs_records = await asyncio.to_thread(logs_sheet.get_all_values)
        users_records = await asyncio.to_thread(users_sheet.get_all_values)

        uid_to_nickname = {}
        for row in users_records[1:]:
            if row and len(row) >= 2:
                uid_to_nickname[str(row[0])] = row[1] or "회원"

        # 이번 주 인증 데이터 집계: user별, routine별
        routine_stats = {}  # key: (uid, routine_name) -> {count, captions, certs}
        week_user_ids = set()
        total_week_auths = 0

        for row in logs_records[1:]:
            if len(row) < 5:
                continue
            status = row[4]
            if status != "success":
                continue
            try:
                log_time = datetime.strptime(row[3][:19], "%Y-%m-%d %H:%M:%S")
            except (ValueError, IndexError):
                continue
            if log_time < week_start:
                continue

            uid = str(row[2])
            routine_name = row[8] if len(row) > 8 else "루틴"
            caption = row[6] if len(row) > 6 else ""
            image_url = row[5] if len(row) > 5 else ""

            total_week_auths += 1
            week_user_ids.add(uid)

            key = (uid, routine_name)
            if key not in routine_stats:
                routine_stats[key] = {"count": 0, "captions": [], "certs": []}
            routine_stats[key]["count"] += 1
            if caption and caption != "내용 없음":
                routine_stats[key]["captions"].append(caption)
            
            routine_stats[key]["certs"].append({
                "caption": caption,
                "image_url": image_url
            })

        if not routine_stats:
            print("이번 주 인증 기록 없음 — 카드뉴스 발송 생략")
            return

        # 인증 횟수 + 캡션 다양성 기준으로 상위 4개 루틴 선정
        scored = []
        for (uid, rname), stats in routine_stats.items():
            score = stats["count"] * 2 + len(stats["captions"])
            scored.append({
                "uid": uid,
                "routine_name": rname,
                "count": stats["count"],
                "captions": stats["captions"],
                "certs": stats["certs"],
                "score": score,
            })
        scored.sort(key=lambda x: x["score"], reverse=True)

        # 동일 유저 중복 방지: 유저당 최대 1개 루틴만 선정
        selected = []
        seen_uids = set()
        for item in scored:
            if item["uid"] not in seen_uids:
                selected.append(item)
                seen_uids.add(item["uid"])
            if len(selected) >= 4:
                break

        # AI로 각 루틴 요약 텍스트 생성
        top_routines = []
        for item in selected:
            nickname = uid_to_nickname.get(item["uid"], "회원")
            try:
                summary = await generate_card_routine_summary(
                    nickname, item["routine_name"], item["certs"]
                )
            except Exception as e:
                print(f"카드뉴스 AI 요약 생성 실패: {e}")
                summary = f"{nickname}님이 '{item['routine_name']}' 루틴을 꾸준히 실천하고 있어요! 🔥"

            top_routines.append({
                "nickname": nickname,
                "routine_name": item["routine_name"],
                "summary": summary,
                "auth_count": item["count"],
            })

        # 카드뉴스 이미지 생성
        print(f"🎨 [카드뉴스] 이미지 생성 시작... (루틴 {len(top_routines)}개 선정)")
        card_images = generate_card_news(
            top_routines=top_routines,
            total_auths=total_week_auths,
            total_members=len(week_user_ids),
        )
        print(f"🎨 [카드뉴스] 이미지 {len(card_images)}장 생성 완료!")

        # 텔레그램 Media Group으로 한 번에 발송 (최대 10장)
        media_group = []
        for i, card_buf in enumerate(card_images):
            caption_text = None
            if i == 0:
                caption_text = "🌱 산스 AI루틴클럽 주간 카드뉴스 🌱"
            media_group.append(InputMediaPhoto(media=card_buf, caption=caption_text))

        await context.bot.send_media_group(chat_id=chat_id, media=media_group)
        print(f"📰 [카드뉴스] {len(card_images)}장 발송 완료! (Target: {chat_id})")

    except Exception as e:
        print(f"카드뉴스 생성/발송 실패: {e}")
        import traceback
        traceback.print_exc()

async def test_weekly_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용: 주간 카드뉴스를 즉시 생성하여 명령어를 친 대화방에 발송합니다."""
    target_chat_id = str(update.message.chat_id)
    await update.message.reply_text("⏳ 주간 카드뉴스 생성 중... 이미지를 만들고 있습니다! 🎨")
    try:
        await weekly_card_news_job(context, target_chat_id=target_chat_id)
        await update.message.reply_text("✅ 주간 카드뉴스 발송 테스트 완료! (명령어 입력 방으로 전송되었습니다.)")
    except Exception as e:
        await update.message.reply_text(f"❌ 주간 카드뉴스 생성 실패: {e}")

async def test_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용: 주간 TOP 3 스케줄러를 즉시 실행하여 명령어를 친 대화방에 발송합니다."""
    target_chat_id = str(update.message.chat_id)
    await update.message.reply_text("⏳ 이번 주 TOP 3 집계 중입니다...")
    await weekly_top_job(context, target_chat_id=target_chat_id)
    await update.message.reply_text("✅ 주간 TOP 3 발송 테스트 완료! (명령어 입력 방으로 전송되었습니다.)")

async def test_insight_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용: 주간 인사이트 AI 브리핑 스케줄러를 즉시 실행하여 명령어를 친 대화방에 발송합니다."""
    target_chat_id = str(update.message.chat_id)
    await update.message.reply_text("⏳ 주간 인사이트 AI 브리핑 생성 중입니다...")
    try:
        await weekly_insight_briefing_job(context, target_chat_id=target_chat_id)
        await update.message.reply_text("✅ 주간 인사이트 AI 브리핑 발송 테스트 완료! (명령어 입력 방으로 전송되었습니다.)")
    except Exception as e:
        await update.message.reply_text(f"❌ 주간 인사이트 AI 브리핑 발송 실패: {e}")

async def weekly_insight_briefing_job(context: ContextTypes.DEFAULT_TYPE, target_chat_id: str = None):
    """매주 일요일 KST 12:05에 이번 주 인사이트를 AI로 브리핑해 그룹방에 발송합니다."""
    chat_id = target_chat_id or GROUP_CHAT_ID
    if not chat_id:
        print("⚠️ chat_id가 설정되지 않아 인사이트 브리핑을 발송하지 않습니다.")
        return

    try:
        now = datetime.now()
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

        insights_records = await asyncio.to_thread(insights_sheet.get_all_values)
        if len(insights_records) <= 1:
            print("이번 주 인사이트 없음 — 브리핑 발송 생략")
            return

        users_records = await asyncio.to_thread(users_sheet.get_all_values)
        uid_to_nickname = {}
        for row in users_records[1:]:
            if row and len(row) >= 2:
                uid_to_nickname[str(row[0])] = row[1] or "회원"

        collected = []
        for row in insights_records[1:]:
            if len(row) < 4:
                continue
            try:
                insight_time = datetime.strptime(row[2][:19], "%Y-%m-%d %H:%M:%S")
            except (ValueError, IndexError):
                continue
            if insight_time < week_start:
                continue

            uid = str(row[1]) if len(row) > 1 else ""
            nickname = uid_to_nickname.get(uid, "회원")
            content = row[3].strip() if len(row) > 3 and row[3] else ""
            if not content:
                continue

            # LLM 입력 길이 폭주를 막기 위해 항목당 길이를 제한합니다.
            clipped_content = content if len(content) <= 300 else content[:300] + "..."
            collected.append(
                f"- ({insight_time.strftime('%m-%d %H:%M')}) {nickname}: {clipped_content}"
            )

        if not collected:
            print("이번 주 인사이트 없음 — 브리핑 발송 생략")
            return

        insights_text = "\n".join(collected[:80])
        briefing_text = await generate_weekly_insight_briefing(insights_text)
        if not briefing_text:
            print("주간 인사이트 브리핑 생성 실패 — 발송 생략")
            return

        briefing_text = sanitize_ai_briefing_text(briefing_text)

        if len(briefing_text) > 3500:
            briefing_text = briefing_text[:3500] + "\n..."

        msg = (
            "🧠 **이번 주 인사이트 AI 브리핑**\n\n"
            f"{briefing_text}\n\n"
            "👉 다음 브리핑의 주인공은 당신입니다. /insight 로 이번 주 배움을 한 줄 남겨주세요! 🌱"
        )
        try:
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
        except Exception as ex:
            print(f"⚠️ [주간 브리핑] 마크다운 발송 실패, 일반 텍스트 폴백 시도: {ex}")
            clean_msg = msg.replace("**", "").replace("*", "").replace("_", "").replace("`", "")
            await context.bot.send_message(chat_id=chat_id, text=clean_msg)
    except Exception as e:
        print(f"Weekly Insight Briefing Job Error: {e}")
        raise e

async def test_insight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용: 샘플 인사이트를 생성하여 AI 분석 후 토픽(594)으로 아카이빙을 테스트합니다."""
    await update.message.reply_text("⏳ AI가 샘플 인사이트 분석 및 아카이빙 전송을 테스트 중입니다...")
    
    sample_text = (
        "오늘 AI 봇 성능 튜닝을 진행했다. Python 비동기 라이브러리인 asyncio를 적극 도입하여 "
        "Google Sheets와 Ollama API 동시 호출 시 발생하는 블로킹 지연을 획득하게 개선했다. "
        "비동기 태스크 병렬 처리는 대규모 텔레그램 봇 아키텍처의 필수 요소임을 깨달았다."
    )
    user_name = update.message.from_user.first_name or update.message.from_user.username or "테스터"
    
    try:
        # AI 분석 및 포스팅
        summary_data = await generate_insight_summary(sample_text)
        category = "자기계발"
        summary = sample_text[:50] + "..."
        if summary_data and isinstance(summary_data, dict):
            category = summary_data.get("category", "자기계발")
            summary = summary_data.get("summary", summary)
        
        archive_msg = (
            f"🧠 **[테스트] 산스 루틴클럽 지식 아카이브** 🧠\n\n"
            f"👤 **작성자**: {user_name}님 (테스트)\n"
            f"📁 **분류 카테고리**: {category}\n"
            f"💡 **한 줄 핵심 요약**: {summary}\n\n"
            f"📝 **인사이트 상세**:\n"
            f"\"{sample_text}\""
        )
        
        kwargs = {"chat_id": INSIGHT_CHAT_ID, "text": archive_msg, "parse_mode": "Markdown"}
        if INSIGHT_THREAD_ID:
            kwargs["message_thread_id"] = INSIGHT_THREAD_ID
            
        await context.bot.send_message(**kwargs)
        await update.message.reply_text(
            f"✅ 아카이빙 테스트 메시지 전송 성공!\n"
            f"그룹 ID: {INSIGHT_CHAT_ID}\n"
            f"토픽 ID: {INSIGHT_THREAD_ID}\n"
            f"카테고리: {category}\n"
            f"요약: {summary}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ 아카이빙 테스트 실패: {e}")

async def test_multimodal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용: 1픽셀 PNG 이미지를 사용하여 Ollama Gemma4:e2b 멀티모달 분석 API를 테스트합니다."""
    await update.message.reply_text("⏳ 1픽셀 테스트 이미지를 base64로 인코딩하여 Ollama 멀티모달 분석을 수행 중입니다...")
    
    # 1x1 투명 PNG의 Base64
    dummy_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    sample_caption = "오늘 아침 일찍 일어나서 컴퓨터 앞에서 열심히 코딩 공부를 했습니다!"
    routine_name = "매일 코딩 1시간"
    
    try:
        ai_comment = await generate_image_analysis(dummy_base64, sample_caption, routine_name)
        if ai_comment:
            await update.message.reply_text(
                f"✅ 멀티모달 분석 성공!\n\n"
                f"🤖 **AI 코치 응답 결과**:\n\"{ai_comment}\""
            )
        else:
            await update.message.reply_text("❌ 멀티모달 분석 응답이 비어있습니다. Ollama 서버 및 Gemma 4:e2b 모델 상태를 확인해 주세요.")
    except Exception as e:
        await update.message.reply_text(f"❌ 멀티모달 테스트 에러: {e}")

async def test_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용: 현재 봇에서 지원하는 모든 테스트 명령어 목록을 출력합니다."""
    help_msg = (
        "🛠️ **산스 루틴클럽 테스트 명령어 안내** 🛠️\n\n"
        "🔹 `/testhelp` - 이 테스트 도움말 출력\n"
        "🔹 `/testrec` - AI 개인 맞춤 루틴 추천 즉시 실행 (DM 발송)\n"
        "🔹 `/testmorning` - 아침 시작 알림 메시지 즉시 실행 (그룹방)\n"
        "🔹 `/testdashboard` - 일일 대시보드 및 리마인더 즉시 실행 (그룹방)\n"
        "🔹 `/testreminder` - 저녁 마감 리마인더 즉시 실행 (그룹방)\n"
        "🔹 `/testcatalyst` - 월/금/토 AI 소성취 챌린지 즉시 실행 (명령어 입력 방)\n"
        "🔹 `/testweekly` - 주간 TOP 3 리더보드 즉시 실행 (그룹방)\n"
        "🔹 `/testinsightbrief` - 주간 인사이트 AI 브리핑 즉시 실행 (그룹방)\n"
        "🔹 `/testinitweekly` - 주간 달성률 시트 초기화 즉시 실행\n"
        "🔹 `/testinsight` - AI 인사이트 카테고리화 및 아카이빙 토픽(594) 전송 테스트\n"
        "🔹 `/testmultimodal` - Ollama Gemma 4:e2b 멀티모달 이미지 분석 API 연동 테스트\n"
        "🔹 `/testattendance [시작주차]` - 지정 주차(기본: 2026-W16)부터 출석률 종합 시뮬레이션\n"
        "🔹 `/testweeklycard` - 주간 카드뉴스 (6장 이미지) 생성 및 발송 테스트"
    )
    await update.message.reply_text(help_msg, parse_mode='Markdown')

def get_column_letter(col_idx: int) -> str:
    """열 번호(1-indexed)를 알파벳 열 문자(A, B, C...)로 변환합니다."""
    result = ""
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        result = chr(65 + remainder) + result
    return result

async def update_attendance_sheet(week_id: str):
    """
    Weekly_Achievement 시트의 데이터를 기준으로 '출석률' 시트의 특정 주차(week_id)의 출석률을 유저별로 종합하여 업데이트합니다.
    필요 시 열을 생성하고 C열의 수식을 업데이트하며, 신규 등록 유저를 동기화합니다.
    """
    import gspread
    try:
        # 1. Weekly_Achievement 시트에서 특정 주차의 데이터를 가져옵니다.
        wa_records = await asyncio.to_thread(weekly_achievement_sheet.get_all_values)
        if len(wa_records) <= 1:
            print(f"[{week_id}] Weekly_Achievement에 기록이 없습니다.")
            return

        # week_id에 일치하는 데이터 필터링하여 유저별 루틴 달성률 수집
        user_rates = {}
        for row in wa_records[1:]:
            if len(row) >= 9 and row[0] == week_id:
                uid = str(row[2])
                try:
                    rate = float(row[8]) if row[8] else 0.0
                except ValueError:
                    rate = 0.0
                if uid not in user_rates:
                    user_rates[uid] = []
                user_rates[uid].append(rate)

        # 동일 유저에 대해 루틴이 2개 이상일 경우 그 중 제일 높은 출석률(최대값)만 가져오도록 계산
        user_avg_attendance = {}
        for uid, rates in user_rates.items():
            user_avg_attendance[uid] = max(rates) if rates else 0.0

        # 2. '출석률' 시트의 전체 데이터를 읽어옵니다.
        att_records = await asyncio.to_thread(attendance_sheet.get_all_values)
        headers = att_records[0] if att_records else []
        
        # 3. week_id에 대응하는 열 인덱스(1-indexed) 찾기
        col_idx = None
        for idx, h in enumerate(headers):
            if h == week_id:
                col_idx = idx + 1
                break

        # 만약 해당 주차 열이 없다면 신규 열 추가
        if not col_idx:
            col_idx = len(headers) + 1
            # 헤더에 week_id 업데이트
            await asyncio.to_thread(attendance_sheet.update_cell, 1, col_idx, week_id)
            print(f"📊 [출석률] 신규 주차 열 추가 완료: {week_id} ({col_idx}열)")
            headers.append(week_id)

        # 마지막 열의 문자 (예: H열, I열 등) 구하기
        last_col_letter = get_column_letter(len(headers))

        # 4. Users 시트와 동기화하여 신규 유저가 출석률 시트에 누락된 경우 행을 추가합니다.
        users_records = await asyncio.to_thread(users_sheet.get_all_values)
        att_user_ids = {row[0]: idx + 2 for idx, row in enumerate(att_records[1:]) if row}

        # 신규 유저 추가
        for row in users_records[1:]:
            if not row or len(row) < 1:
                continue
            uid = str(row[0])
            nickname = row[1] or "회원"
            
            if uid not in att_user_ids:
                new_row_idx = len(att_records) + 1
                # C열 수식 자동 연산: D열부터 마지막 열까지의 평균
                formula = f'=IF($A{new_row_idx}="","",IFERROR(AVERAGE(D{new_row_idx}:{last_col_letter}{new_row_idx}),""))'
                
                # 빈 주차 영역은 0.00으로 패딩
                padding_len = len(headers) - 3  # A, B, C열 제외
                padding = ["0.00"] * padding_len
                
                new_user_row = [uid, nickname, formula] + padding
                await async_append_row(attendance_sheet, new_user_row)
                
                att_user_ids[uid] = new_row_idx
                att_records.append(new_user_row)
                print(f"👥 [출석률] 신규 멤버 추가: {nickname} ({uid})")

        # 5. 기존 및 신규 유저들의 특정 주차 출석률 업데이트 및 C열 수식 일괄 갱신 (Batch Update 최적화)
        cells_to_update = []
        for uid, row_num in att_user_ids.items():
            rate = user_avg_attendance.get(uid, 0.0)
            # 출석률 값 셀 객체 생성
            cells_to_update.append(gspread.Cell(row=row_num, col=col_idx, value=f"{rate:.2f}"))
            
            # C열(3열) 평균 수식 셀 객체 생성
            formula = f'=IF($A{row_num}="","",IFERROR(AVERAGE(D{row_num}:{last_col_letter}{row_num}),""))'
            cells_to_update.append(gspread.Cell(row=row_num, col=3, value=formula))

        # 단 1회의 API Write 호출로 일괄 업데이트
        if cells_to_update:
            await asyncio.to_thread(
                attendance_sheet.update_cells, 
                cells_to_update, 
                value_input_option='USER_ENTERED'
            )

        print(f"✅ [출석률] {week_id} 주차 유저별 출석률 종합 및 업데이트 완료!")
    except Exception as e:
        print(f"❌ [출석률] {week_id} 종합 중 치명적 에러 발생: {e}")
        raise e

async def test_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용 및 시뮬레이션용: 지정된 주차부터 현재 주차 이전(마감된 주차까지) 출석률 종합 작업을 실행합니다."""
    args = context.args
    start_week = args[0] if args else "2026-W16"
    
    await update.message.reply_text(f"⏳ {start_week}부터 이번 주 이전 주차까지 출석률 종합 시뮬레이션을 시작합니다...")
    
    try:
        start_year = int(start_week.split("-W")[0])
        start_wk = int(start_week.split("-W")[1])
    except (ValueError, IndexError):
        await update.message.reply_text("⚠️ 주차 형식이 잘못되었습니다. 예시: /testattendance 2026-W16")
        return
        
    try:
        # iso_year-Wiso_week-1 형식을 파싱해서 첫 날짜 구하기
        start_dt = datetime.strptime(f"{start_year}-W{start_wk:02d}-1", "%G-W%V-%u")
    except ValueError:
        # 파싱 폴백
        start_dt = datetime(start_year, 1, 1) + timedelta(weeks=start_wk - 1)
        
    now = datetime.now()
    weeks_to_process = []
    temp_dt = start_dt
    while temp_dt <= now:
        iso_y, iso_w, _ = temp_dt.isocalendar()
        wk_str = f"{iso_y}-W{iso_w:02d}"
        if wk_str not in weeks_to_process:
            weeks_to_process.append(wk_str)
        temp_dt += timedelta(days=7)
        
    # 현재 진행 중인 이번 주차는 집계에서 제외
    current_year, current_week, _ = now.isocalendar()
    current_week_id = f"{current_year}-W{current_week:02d}"
    if current_week_id in weeks_to_process:
        weeks_to_process.remove(current_week_id)
        
    results = []
    for wk in weeks_to_process:
        try:
            await update_attendance_sheet(wk)
            results.append(f"✅ {wk}: 성공")
        except Exception as e:
            results.append(f"❌ {wk}: 실패 ({e})")
            
    result_msg = "📊 **출석률 종합 시뮬레이션 결과** 📊\n\n" + "\n".join(results)
    await update.message.reply_text(result_msg, parse_mode='Markdown')
    
async def monthly_rec_job(context: ContextTypes.DEFAULT_TYPE, target_user_id: str = None):
    """매월 15일 KST 12:00에 실행: 루틴 등록 멤버에게 개별 DM으로 AI 루틴 추천.
    target_user_id 지정 시 해당 유저에게만, 없으면 전체 루틴 등록 멤버 대상.
    절대 GROUP_CHAT_ID에 발송하지 않음.
    """
    
    try:
        users_records = await asyncio.to_thread(users_sheet.get_all_values)
        if len(users_records) <= 1:
            return
            
        users_data = users_records[1:]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        for row in users_data:
            if not row or len(row) < 1: continue
            user_id = str(row[0])
            if not user_id: continue
            
            # target_user_id가 지정된 경우 해당 유저만 처리
            if target_user_id and user_id != target_user_id:
                continue

            # AI 추천 (루틴현황, 최근 인증, 인사이트 종합)
            combined_texts = []
            
            # 1. 진행 중인 활성 루틴
            user_routines = await async_findall_in_col(routines_sheet, user_id, column=2)
            active_routines = []
            if user_routines:
                for row_cell in user_routines:
                    row_data = await async_row_values(routines_sheet, row_cell.row)
                    if len(row_data) >= 6 and row_data[5] == "active":
                        active_routines.append(row_data[2])
            # 루틴을 등록하지 않은 멤버는 추천 대상에서 제외
            if not active_routines:
                print(f"[{user_id}] 활성 루틴 없음 — 추천 생략")
                continue

            combined_texts.append(f"현재루틴: {','.join(active_routines)}")

            # 2. 최근 3개 인증 로그
            user_logs = await async_findall_in_col(logs_sheet, user_id, column=3)
            if user_logs:
                for row_cell in user_logs[-3:]:
                    row_data = await async_row_values(logs_sheet, row_cell.row)
                    if len(row_data) >= 7:
                        combined_texts.append(f"인증: {row_data[6]}")
                        
            # 3. 최근 3개 인사이트
            user_insights = await async_findall_in_col(insights_sheet, user_id, column=2)
            if user_insights:
                for row_cell in user_insights[-3:]:
                    row_data = await async_row_values(insights_sheet, row_cell.row)
                    if len(row_data) >= 4:
                        combined_texts.append(f"생각: {row_data[3]}")
                        
            if combined_texts:
                logs_text = " / ".join(combined_texts)
                rec_data = await generate_routine_recommendation(logs_text)
                if rec_data and "routine" in rec_data:
                    rec_id = "re-" + str(uuid.uuid4())[:8]
                    routine_name = rec_data.get("routine", "")
                    rationale = rec_data.get("rationale", "")
                    await async_append_row(ai_recommendations_sheet, [rec_id, user_id, now_str, routine_name, rationale, ""])
                    print(f"[{user_id}] AI 추천 생성 완료: {routine_name}")
                    
                    try:
                        nickname = row[1] if len(row) > 1 else "회원"
                        msg = (
                            f"💡 **{nickname}님을 위한 이달의 맞춤 AI 추천 루틴**\n\n"
                            f"🎯 추천 목표: {routine_name}\n"
                            f"📝 추천 이유: {rationale}\n\n"
                            f"👉 마음에 드신다면 `/reg {routine_name}`으로 새로 등록해보세요!"
                        )
                        # 개인 DM으로만 발송 — group_chat에 절대 발송하지 않음
                        await context.bot.send_message(chat_id=user_id, text=msg, parse_mode='Markdown')
                    except Exception as e:
                        print(f"DM 발송 실패 (사용자가 봇을 차단했거나 1:1 대화를 시작하지 않음): {user_id}, {e}")
                    
    except Exception as e:
        print(f"Monthly Rec Job Error: {e}")

def main():
    install_terminal_output_logging()

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

    # 입력 로깅 핸들러: 모든 텍스트/사진/콜백 입력을 선행 로깅합니다.
    app.add_handler(MessageHandler(filters.ALL, log_incoming_update), group=-1)
    app.add_handler(CallbackQueryHandler(log_incoming_update), group=-1)

    # 수정 Conversation
    edit_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("edit", edit_start), CommandHandler("modify", edit_start)],
        states={
            CHOOSING_NEW_NAME: [
                CallbackQueryHandler(edit_callback, pattern='^edit_|^edit_cancel$'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_save)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel_edit)],
        per_chat=True,
        per_user=True,
        per_message=False
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("insight", insight))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("del", delete_routine))
    app.add_handler(CommandHandler("delete", delete_routine))
    app.add_handler(CommandHandler("rank", show_rank))
    app.add_handler(CommandHandler("testrec", test_rec))
    app.add_handler(CommandHandler("testmorning", test_morning))
    app.add_handler(CommandHandler("testdashboard", test_dashboard))
    app.add_handler(CommandHandler("testreminder", test_reminder))
    app.add_handler(CommandHandler("testcatalyst", test_catalyst))
    app.add_handler(CommandHandler("testweekly", test_weekly))
    app.add_handler(CommandHandler("testinsightbrief", test_insight_briefing))
    app.add_handler(CommandHandler("testinitweekly", test_init_weekly))
    app.add_handler(CommandHandler("testinsight", test_insight))
    app.add_handler(CommandHandler("testmultimodal", test_multimodal))
    app.add_handler(CommandHandler("testimage", test_multimodal))
    app.add_handler(CommandHandler("testhelp", test_help))
    app.add_handler(CommandHandler("testattendance", test_attendance))
    app.add_handler(CommandHandler("testweeklycard", test_weekly_card))
    app.add_handler(CommandHandler("reg", reg_start))
    app.add_handler(edit_conv_handler)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    app.add_handler(CallbackQueryHandler(del_callback, pattern='^del_|^cancel_del$'))
    app.add_handler(CallbackQueryHandler(auth_routine_callback, pattern='^auth_'))

    # 스케줄러 등록
    jq = app.job_queue
    kst = ZoneInfo("Asia/Seoul")
    
    # 환경변수 기반 스케줄 시간대 로드 (기본값 설정)
    morning_time_str = os.environ.get("MORNING_ALARM_TIME", "09:00").split(":")
    dashboard_time_str = os.environ.get("EVENING_DASHBOARD_TIME", "18:00").split(":")
    reminder_time_str = os.environ.get("EVENING_REMINDER_TIME", "21:00").split(":")
    catalyst_time_str = os.environ.get("CATALYST_ALARM_TIME", "15:30").split(":")
    
    morning_hour, morning_minute = int(morning_time_str[0]), int(morning_time_str[1])
    dashboard_hour, dashboard_minute = int(dashboard_time_str[0]), int(dashboard_time_str[1])
    reminder_hour, reminder_minute = int(reminder_time_str[0]), int(reminder_time_str[1])
    catalyst_hour, catalyst_minute = int(catalyst_time_str[0]), int(catalyst_time_str[1])
    
    # 🌅 아침 메시지
    jq.run_daily(morning_job, time(hour=morning_hour, minute=morning_minute, second=0, tzinfo=kst))
    
    # 📊 일일 대시보드 + 리마인더 (KST 18:00)
    jq.run_daily(daily_dashboard_job, time(hour=dashboard_hour, minute=dashboard_minute, second=0, tzinfo=kst))
    
    # 🌙 저녁 마감 리마인더 (KST 21:00)
    jq.run_daily(daily_reminder_job, time(hour=reminder_hour, minute=reminder_minute, second=0, tzinfo=kst))
    
    # 🚀 소성취 촉매제 (KST 월/금/토 15:30)
    jq.run_custom(
        daily_catalyst_job,
        job_kwargs={
            "trigger": "cron",
            "day_of_week": "mon,fri,sat",
            "hour": catalyst_hour,
            "minute": catalyst_minute,
            "second": 0,
            "timezone": kst,
            "id": "catalyst_mon_fri_sat",
            "replace_existing": True,
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 60,
        },
        name="catalyst_mon_fri_sat",
    )
    
    # 💡 AI 추천 (매월 15일 KST 12:00)
    jq.run_monthly(monthly_rec_job, when=time(hour=12, minute=0, second=0, tzinfo=kst), day=15)
    
    # 🏆 주간 TOP 3 (매주 일요일 KST 12:00)
    jq.run_daily(weekly_top_job, time(hour=12, minute=0, second=0, tzinfo=kst), days=(6,))

    # 🧠 주간 인사이트 AI 브리핑 (매주 일요일 KST 12:05)
    jq.run_daily(weekly_insight_briefing_job, time(hour=12, minute=5, second=0, tzinfo=kst), days=(6,))

    # 📰 주간 카드뉴스 (매주 일요일 KST 12:10)
    jq.run_daily(weekly_card_news_job, time(hour=12, minute=10, second=0, tzinfo=kst), days=(6,))
    
    # 📅 주간 초기화 (매주 월요일 KST 00:01)
    # KST 기준 월요일(0) 00:01
    jq.run_daily(initialize_weekly_achievement, time(hour=0, minute=1, second=0, tzinfo=kst), days=(0,))


    print("🤖 인사이트 루틴 랩 V2 봇 가동 시작! (비동기, 랭킹, JobQueue 장착 완료)")
    app.run_polling()

if __name__ == '__main__':
    main()
