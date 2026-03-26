import asyncio
import os
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import random
import uuid
import warnings
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
    weekly_achievement_sheet
)
from ai_utils import generate_insight_keywords, generate_routine_recommendation

load_dotenv()

# ==========================================
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GROUP_CHAT_ID = os.environ["GROUP_CHAT_ID"]
# ==========================================

# /reg 대화(Conversation) 상태 정의
CHOOSING_CATEGORY = 1
CHOOSING_FREQUENCY = 2

# 메모리 캐시
daily_auth_count = {"date": "", "count": 0}

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
        await async_append_row(weekly_achievement_sheet, new_row)
        # 수식 삽입을 위해 방금 추가된 행 번호 찾기
        updated_rows = await asyncio.to_thread(weekly_achievement_sheet.get_all_values)
        found_row = len(updated_rows)

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
        "🔹 /status - 나의 루틴 인증 현황 모니터링\n"
        "🔹 /insight [내용] - 50자 이상 인사이트 공유\n"
        "🔹 /del - 등록된 루틴 삭제\n"
        "🔹 /rank - 명예의 전당 (포인트 랭킹 확인) 🏆\n"
        "📸 **단일 인증** - 사진을 업로드하고 캡션에 내용을 적어 전송!\n\n"
        "그룹방 알림을 최소화하기 위해, 그룹방에서는 명령어로 짧게 사용하시거나 아래 버튼을 눌러 1:1 채팅방에서 기능을 확인해보세요."
    )
    await update.message.reply_text(welcome_msg, reply_markup=reply_markup, parse_mode='Markdown')

# ===============================================
# ConversationHandler: 루틴 등록 로직 (/reg -> 카테고리 -> 빈도)
# ===============================================
async def reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_group_chat_with_redirect(update, context):
        return ConversationHandler.END
    text = update.message.text.split()
    if len(text) < 2:
        await update.message.reply_text("앗, 양식이 조금 틀렸어요! 😅\n👉 다시 `/reg 매일독서10쪽` 처럼 등록할 루틴을 입력해주세요!", parse_mode='Markdown')
        return ConversationHandler.END

    routine_name = " ".join(text[1:])
    context.user_data['routine_name'] = routine_name
    
    keyboard = [
        [InlineKeyboardButton("💪 신체 건강", callback_data="Physical"),
         InlineKeyboardButton("🧠 지적 성장", callback_data="Intellectual")],
        [InlineKeyboardButton("🧘 정신/감정", callback_data="Mental"),
         InlineKeyboardButton("🎨 취미/창작", callback_data="Creative")],
        [InlineKeyboardButton("🧹 생활 관리", callback_data="Lifestyle")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"🎯 [{routine_name}] - 어떤 카테고리의 루틴인가요?", reply_markup=reply_markup)
    return CHOOSING_CATEGORY

async def reg_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data['category'] = query.data
    
    keyboard = [
        [InlineKeyboardButton("🗓️ 매일 (Everyday)", callback_data="everyday")],
        [InlineKeyboardButton("🏢 평일만 (Weekdays)", callback_data="weekdays")],
        [InlineKeyboardButton("🔥 주 3회 (3 times a week)", callback_data="3times")],
        [InlineKeyboardButton("🎯 주 1회 (Once a week)", callback_data="1time")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("⏳ 얼마나 자주 실행할 계획이신가요?", reply_markup=reply_markup)
    return CHOOSING_FREQUENCY

async def reg_frequency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    frequency = query.data
    routine_name = context.user_data.get('routine_name', '알수없는루틴')
    category = context.user_data.get('category', '기타')
    
    user_id = str(query.from_user.id)
    nickname = query.from_user.first_name or query.from_user.username or "회원"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cell = await async_find_in_col(users_sheet, user_id)
    if not cell:
        # [user_id, nickname, now, shield, points, timezone, info]
        await async_append_row(users_sheet, [user_id, nickname, now, 2, 0, "Asia/Seoul", ""])
        
    routine_id = str(uuid.uuid4())
    # [routine_id, user_id, routine_name, category, frequency, status, created_at, current_streak]
    # V2: current_streak를 8번째 컬럼으로 사용 (초기값 0)
    await async_append_row(routines_sheet, [routine_id, user_id, routine_name, category, frequency, "active", now, 0])
    
    await query.edit_message_text(f"🎉 환영합니다! [{nickname}]님이 새로운 루틴 여정을 시작했습니다!\n목표: {routine_name}\n카테고리: {category}\n빈도: {frequency}\n모두 박수로 환영해주세요! 👏")
    print(f"👤 [루틴 등록] {nickname} ({user_id}): {routine_name} / {frequency}")
    
    # 그룹 채팅방 공유 (V2 추가)
    try:
        group_msg = f"📣 **새로운 루틴 도전!**\n\n👤 **{nickname}**님이 새로운 목표를 세웠습니다!\n🎯 **목표**: {routine_name}\n📊 **빈도**: {frequency}\n\n우리 모두 함께 응원해요! 🔥"
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=group_msg, parse_mode='Markdown')
    except Exception as e:
        print(f"그룹 공유 에러 (루틴 등록): {e}")

    context.user_data.clear()
    return ConversationHandler.END

async def cancel_reg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("루틴 등록이 취소되었습니다.")
    context.user_data.clear()
    return ConversationHandler.END

# ===============================================
# 사진 인증 및 스트라이크 로직 (V2)
# ===============================================
async def process_auth(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, chat_id, routine_row, routine_id, routine_name, now_time, now_date, message_link, caption, query=None):
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
            rate_msg = f"\n📊 이번 주 달성률: {weekly_rate:.0f}% ({min(weekly_done, weekly_target)}/{weekly_target})"
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

    # 그룹 채팅방 공유 (V2 추가)
    try:
        nickname = user_obj.first_name or user_obj.username or "회원"
        group_msg = f"✅ **{nickname}**님이 루틴을 인증했습니다!\n\n🔥 **{routine_name}**\n{rate_msg.strip() if rate_msg else ''}\n\n꾸준함이 실력입니다! 멋져요! 👏"
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=group_msg, parse_mode='Markdown')
    except Exception as e:
        print(f"그룹 공유 에러 (인증): {e}")

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
        query=query
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

    message_link = update.message.link
    if not message_link:
        photo_id = update.message.photo[-1].file_id
        file_info = await context.bot.get_file(photo_id)
        message_link = file_info.file_path
        
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
            now_time=now_time, now_date=now_date, message_link=message_link, caption=caption
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
            "routines": routine_names
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

    if len(text) < 50:
        await update.message.reply_text(
            f"💡 좋은 인사이트네요! 50자를 넘겨주시면 15포인트를 드립니다.\n(현재 글자수: {len(text)}자)",
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
            # 인사이트 내용이 너무 길면 자르기
            summary = text if len(text) <= 50 else text[:50] + "..."
            group_msg = f"💡 **{user_name}**님이 새로운 인사이트를 공유했습니다!\n\n\"{summary}\"\n\n훌륭한 배움입니다! 🚀"
            await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=group_msg, parse_mode='Markdown')
        except Exception as e:
            print(f"그룹 공유 에러 (인사이트): {e}")

        async def bg_keyword_task(t_insight_id, t_text):
            keywords = await generate_insight_keywords(t_text)
            if keywords:
                cell = await async_find_in_col(insights_sheet, t_insight_id)
                if cell:
                    await async_update_cell(insights_sheet, cell.row, 6, keywords)

        asyncio.create_task(bg_keyword_task(insight_id, text))

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
                weekly_done_val = wa_data[0]
                weekly_rate_val = wa_data[1]
            else:
                weekly_done_val = "0"
                weekly_rate_val = "0"
            reply_text += f"🔹 **{routine_name}**\n"
            reply_text += f"   🔥 누적 인증 횟수: {streak_val}회\n"
            reply_text += f"   📊 이번 주 달성률: {weekly_rate_val}% ({weekly_done_val}/{weekly_target})\n\n"
            
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
async def morning_job(context: ContextTypes.DEFAULT_TYPE):
    """매일 KST 09:00 (UTC 00:00)에 그룹방에 아침 시작 메시지를 발송합니다."""
    if not GROUP_CHAT_ID:
        print("⚠️ GROUP_CHAT_ID가 설정되지 않아 아침 메시지를 발송하지 않습니다.")
        return
    msg = (
        "🌅 굿모닝! 산스 AI루틴클럽원분들 오늘도 파이팅입니다! 💪\n\n"
        "하루의 시작을 루틴과 함께하면 달라집니다.\n"
        "오늘 나의 루틴을 확인하고 건강한 하루를 시작해보세요! 🌱\n\n"
        "📸 사진+캡션으로 인증해주시면 포인트가 자동으로 쌓입니다!"
    )
    try:
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
    except Exception as e:
        print(f"아침 메시지 발송 실패: {e}")

async def evening_job(context: ContextTypes.DEFAULT_TYPE):
    """매일 KST 21:00 (UTC 12:00)에 그룹방에 저녁 마무리 메시지를 발송합니다."""
    if not GROUP_CHAT_ID:
        return
    msg = (
        "🌙 오늘 하루도 정말 고생 많으셨어요!\n\n"
        "오늘 루틴 인증을 아직 안 하셨다면, 지금이라도 늦지 않았어요. 🙌\n"
        "딱 5분이라도 내 자신과의 약속을 지켜보는 건 어떨까요?\n\n"
        "📸 사진+캡션으로 인증을 남겨주시면 오늘도 포인트는 쌓입니다! ✨"
    )
    try:
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
    except Exception as e:
        print(f"저녁 메시지 발송 실패: {e}")

async def test_rec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용: 명령어를 입력한 본인에게만 AI 루틴 추천을 발송합니다."""
    user_id = str(update.message.from_user.id)
    await update.message.reply_text("⏳ AI 파워로 루틴 추천을 생성 중입니다... 잠시만 기다려주세요!")
    await monthly_rec_job(context, target_user_id=user_id)
    await update.message.reply_text("✅ 완료! 1:1 채팅으로 추천 결과를 확인해보세요.")

async def test_morning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용: 아침 메시지 스케줄러를 즉시 실행합니다."""
    await morning_job(context)
    await update.message.reply_text("✅ 아침 메시지 발송 테스트 완료!")

async def test_evening(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용: 저녁 메시지 스케줄러를 즉시 실행합니다."""
    await evening_job(context)
    await update.message.reply_text("✅ 저녁 메시지 발송 테스트 완료!")

async def initialize_weekly_achievement(context: ContextTypes.DEFAULT_TYPE):
    """매주 월요일 00:01 KST(UTC 일요일 15:01)에 실행: 모든 활성 루틴을 주간 달성률 시트에 미리 등록합니다."""
    week_id, week_start_str = get_current_week_info()
    
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

async def weekly_top_job(context: ContextTypes.DEFAULT_TYPE):
    """매주 일요일 KST 12:00 (UTC 03:00)에 이번 주 TOP 3 루틴 인증자를 그룹방에 발송합니다."""
    if not GROUP_CHAT_ID:
        print("⚠️ GROUP_CHAT_ID가 설정되지 않아 주간 리더보드를 발송하지 않습니다.")
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
            f"/insight 명령어로 50자 이상 공유해주시면 포인트를 드립니다!"
        )
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
    except Exception as e:
        print(f"Weekly TOP 3 Job Error: {e}")

async def test_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용: 주간 TOP 3 스케줄러를 즉시 실행합니다."""
    await update.message.reply_text("⏳ 이번 주 TOP 3 집계 중입니다...")
    await weekly_top_job(context)
    await update.message.reply_text("✅ 주간 TOP 3 발송 테스트 완료!")
    
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
    app = Application.builder().token(TOKEN).build()

    # 등록 Conversation
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("reg", reg_start)],
        states={
            CHOOSING_CATEGORY: [CallbackQueryHandler(reg_category, pattern='^(Physical|Intellectual|Mental|Creative|Lifestyle)$')],
            CHOOSING_FREQUENCY: [CallbackQueryHandler(reg_frequency, pattern='^(everyday|weekdays|3times|1time)$')]
        },
        fallbacks=[CommandHandler('cancel', cancel_reg)],
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
    app.add_handler(CommandHandler("testevening", test_evening))
    app.add_handler(CommandHandler("testweekly", test_weekly))
    app.add_handler(CommandHandler("testinitweekly", test_init_weekly))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    app.add_handler(CallbackQueryHandler(del_callback, pattern='^del_|^cancel_del$'))
    app.add_handler(CallbackQueryHandler(auth_routine_callback, pattern='^auth_'))

    # 스케줄러 등록
    jq = app.job_queue
    kst = ZoneInfo("Asia/Seoul")
    
    # 🌅 아침 메시지 (KST 09:00)
    jq.run_daily(morning_job, time(hour=9, minute=0, second=0, tzinfo=kst))
    
    # 🌙 저녁 메시지 (KST 21:00)
    jq.run_daily(evening_job, time(hour=21, minute=0, second=0, tzinfo=kst))
    
    # 💡 AI 추천 (매월 15일 KST 12:00)
    jq.run_monthly(monthly_rec_job, when=time(hour=12, minute=0, second=0, tzinfo=kst), day=15)
    
    # 🏆 주간 TOP 3 (매주 일요일 KST 12:00)
    jq.run_daily(weekly_top_job, time(hour=12, minute=0, second=0, tzinfo=kst), days=(6,))
    
    # 📅 주간 초기화 (매주 월요일 KST 00:01)
    # KST 기준 월요일(0) 00:01
    jq.run_daily(initialize_weekly_achievement, time(hour=0, minute=1, second=0, tzinfo=kst), days=(0,))


    print("🤖 인사이트 루틴 랩 V2 봇 가동 시작! (비동기, 랭킹, JobQueue 장착 완료)")
    app.run_polling()

if __name__ == '__main__':
    main()