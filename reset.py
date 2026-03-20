import asyncio
import os
from dotenv import load_dotenv
from telegram import Bot, BotCommand

load_dotenv()

# 봇 토큰 (.env 파일에서 로드)
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

async def nuke_and_rebuild():
    bot = Bot(token=TOKEN)
    
    # 1. 숨어있는 찌꺼기 완벽 삭제 (핵심!)
    try:
        await bot.delete_my_commands() # 기본 명령어 삭제
        await bot.delete_my_commands(language_code='ko') # 💥 범인으로 추정되는 한국어 전용 명령어 삭제
    except Exception as e:
        print(f"삭제 중 오류 무시 (정상): {e}")
    
    # 2. 우리가 원하는 5개 명령어 세팅
    commands = [
        BotCommand("start", "봇 가이드 확인 및 등록 시작"),
        BotCommand("reg", "새로운 목표 등록하기"),
        BotCommand("insight", "오늘의 인사이트 남기기"),
        BotCommand("status", "내 루틴 달성 현황 보기"),
        BotCommand("del", "진행 중인 루틴 지우기")
    ]
    
    # 3. 새로운 명령어 '한국어 전용'으로 강력하게 주입!
    await bot.set_my_commands(commands) # 기본 설정
    await bot.set_my_commands(commands, language_code='ko') # 한국어 유저에게 무조건 5개 강제 노출
    
    print("💥 숨겨진 한국어 설정까지 완벽하게 초기화 및 5개 세팅 완료!")

if __name__ == "__main__":
    asyncio.run(nuke_and_rebuild())