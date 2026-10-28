import os
import sys
import subprocess
import shutil

def print_banner():
    print("=" * 50)
    print("   🌿 산스 AI 루틴 클럽 봇 초기 설정 도우미 🌿   ")
    print("=" * 50)

def install_requirements():
    print("\n[1] 필수 패키지 설치를 시작합니다...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ 패키지 설치 완료!")
    except Exception as e:
        print(f"❌ 패키지 설치 중 오류 발생: {e}")
        sys.exit(1)

def configure_env():
    print("\n[2] 환경 변수(.env) 설정을 시작합니다.")
    
    if os.path.exists(".env"):
        choice = input("⚠️  이미 .env 파일이 존재합니다. 덮어씌울까요? (y/n): ").lower()
        if choice != 'y':
            print("기존 설정을 유지합니다.")
            return

    token = input("👉 텔레그램 봇 토큰을 입력하세요 (@BotFather): ").strip()
    chat_id = input("👉 활동 공유용 그룹 채팅 ID를 입력하세요 (예: -100...): ").strip()
    sheet_name = input("👉 연결할 구글 스프레드시트 이름을 입력하세요: ").strip()
    cred_file = input("👉 구글 인증 파일명 (기본: credentials.json): ").strip() or "credentials.json"

    env_content = f"""# Telegram Bot 설정
TELEGRAM_BOT_TOKEN={token}
GROUP_CHAT_ID={chat_id}
OWNER_USER_ID=1415330667

# Google Sheets 설정
GOOGLE_SHEET_NAME={sheet_name}
GOOGLE_CREDENTIALS_FILE={cred_file}
GOOGLE_SHEETS_WRITE_LIMIT_PER_MINUTE=30
GOOGLE_SHEETS_MAX_RETRIES=5
GOOGLE_SHEETS_QUOTA_COOLDOWN_SECONDS=65

# Local Runtime Safety
BOT_LOG_DIR=logs
BOT_LOG_LEVEL=INFO
BOT_INSTANCE_LOCK_PORT=47219

# 메인 봇 개인 DM 발송 간격
PERSONAL_NOTIFICATION_SEND_INTERVAL_SECONDS=0.05

# Ollama 자동 시작 설정 (선택)
AUTO_START_OLLAMA=true
AUTO_PULL_OLLAMA_MODEL=true
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL_NAME=gemma4:e2b
OLLAMA_BIN=ollama
OLLAMA_STARTUP_WAIT_SECONDS=20

"""
    with open(".env", "w", encoding="utf-8") as f:
        f.write(env_content)
    print("✅ .env 파일 생성 완료!")

def check_credentials():
    print("\n[3] 구글 인증 파일(JSON) 및 연결 확인")
    cred_file = "credentials.json"
    sheet_name = ""
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    key, value = line.split("=", 1)
                    if key.strip() == "GOOGLE_CREDENTIALS_FILE":
                        cred_file = value.strip()
                    if key.strip() == "GOOGLE_SHEET_NAME":
                        sheet_name = value.strip()

    if os.path.exists(cred_file):
        print(f"✅ {cred_file} 파일이 확인되었습니다.")
        
        # 연결 테스트 시도
        try:
            import gspread
            print(f"🔄 '{sheet_name}' 시트에 연결을 시도합니다...")
            gc = gspread.service_account(filename=cred_file)
            doc = gc.open(sheet_name)
            print(f"✅ 구글 시트 연결 성공! (시트: {sheet_name})")
        except ImportError:
            print("ℹ️ 패키지가 아직 설치되지 않아 연결 테스트를 건너뜁니다.")
        except Exception as e:
            print(f"❌ 구글 시트 연결 실패: {e}")
            print("💡 시트 이름이 정확한지, 서비스 계정 이메일이 시트에 '편집자'로 공유되었는지 확인해주세요.")
    else:
        print(f"❌ {cred_file} 파일이 없습니다!")
        print(f"💡 GCP 콘솔에서 서비스 계정 키를 다운로드하여 이 폴더에 {cred_file} 이름으로 저장해주세요.")

def check_ollama():
    print("\n[4] AI 기능(Ollama) 확인")
    print("💡 이 봇은 로컬 AI 모델(gemma4:e2b)을 사용합니다.")
    print("💡 main.py 실행 시 Ollama 서버를 자동 확인하고 필요하면 자동 실행을 시도합니다.")
    print("💡 별도 터미널에서 'ollama run ...'을 수동 실행할 필요는 없습니다.")
    print("❓ Ollama가 설치되어 있고, 터미널에서 'ollama' 명령이 인식되나요? (설치: https://ollama.com)")

def main():
    print_banner()
    
    # 0. 플랫폼별 명령어 안내 (Windows vs Mac/Linux)
    if sys.platform == "win32":
        print("💻 Windows 환경입니다. 'python' 명령어를 사용합니다.")
    else:
        print("💻 Mac/Linux 환경입니다. 'python3' 명령어가 필요할 수 있습니다.")

    # 1. 패키지 설치 여부 확인/실행
    do_install = input("\n📦 필수 패키지를 지금 설치할까요? (y/n): ").lower()
    if do_install == 'y':
        install_requirements()
    
    # 2. .env 설정
    configure_env()
    
    # 3. 인증 파일 확인
    check_credentials()
    
    # 4. Ollama 안내
    check_ollama()
    
    print("\n" + "=" * 50)
    print("✨ 모든 설정이 완료되었습니다! ✨")
    print("봇 실행: python main.py")
    print("=" * 50)

if __name__ == "__main__":
    main()
