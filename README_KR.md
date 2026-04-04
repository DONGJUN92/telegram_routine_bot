# 🌱 산스 AI루틴클럽 — 텔레그램 봇

> **AI 기반 개인 맞춤 루틴 추천과 게이미피케이션으로 습관을 만드는 텔레그램 봇**

[View English README](./README.md)

산스 AI루틴클럽 봇은 텔레그램 그룹 내에서 멤버들의 **루틴(습관) 인증을 관리**하고, **포인트·랭킹 시스템**으로 동기를 부여하며, **AI가 개인 맞춤 루틴을 추천**하는 자동화 봇입니다.

---

## ✨ 주요 기능

| 기능 | 설명 |
|------|------|
| 📸 **사진 인증** | 사진 + 캡션 업로드로 루틴 인증 완료 |
| 🏆 **포인트 & 랭킹** | 인증(+10), 인사이트 공유(+15)로 포인트 적립; 연속 인증 보너스(3회 +20점, 7회 +50점); 리더보드 경쟁 |
| 📊 **주간 달성률** | ISO 주차 기반으로 이번 주 달성률 관리 및 아카이빙 |
| 💡 **인사이트 공유** | 성찰 작성 시 보너스 포인트 + 방어권 |
| 🤖 **AI 루틴 추천** | 로컬 LLM(Ollama)을 활용한 월간 맞춤 루틴 추천 |
| 🧠 **주간 인사이트 AI 브리핑** | 해당 주차 인사이트를 AI가 요약해 그룹에 공유 |
| 🔔 **자동 알림** | 매일 아침/저녁 동기부여 메시지 + 주간 TOP 3 + 인사이트 브리핑 |
| 👥 **그룹 활동 공유** | 등록, 인증, 인사이트 활동이 그룹에 자동 공유 |

---

## 🛠️ 기술 스택

| 항목 | 기술 |
|------|------|
| 언어 | Python 3.10+ |
| 프레임워크 | `python-telegram-bot[job-queue]` v20+ (비동기) |
| 데이터베이스 | Google Sheets (`gspread`) |
| AI 엔진 | Ollama (로컬) — `gemma4:e2b` 모델 |
| 스케줄러 | APScheduler (JobQueue) |
| 환경설정 | `python-dotenv` 환경변수 관리 |

---

## 📁 프로젝트 구조

```
sans-ai-routine-bot/
├── main.py                 # 봇 핵심 로직, 명령어, 스케줄러
├── db_utils.py             # Google Sheets 비동기 DB 유틸리티
├── ai_utils.py             # AI 기능 (키워드 추출, 루틴 추천, 인사이트 브리핑)
├── reset.py                # 봇 명령어 메뉴 리셋 유틸리티
├── .env.example            # 환경변수 템플릿
├── .gitignore              # Git 제외 규칙
├── credentials.json        # Google Cloud 서비스 계정 키 (Git 미추적)
├── db_schema/              # 각 시트의 샘플 CSV 스키마
│   ├── Users.csv
│   ├── Routines.csv
│   ├── Logs.csv
│   ├── Insights.csv
│   └── AI_Recommendations.csv
└── routine_bot_improvement_specs.md  # 시스템 사양서
```

---

## 🚀 빠른 시작 (권장)

가장 쉬운 설정 방법은 자동화된 초기 설정 스크립트를 사용하는 것입니다:

1. **저장소 클론 및 이동**
   ```bash
   git clone https://github.com/DONGJUN92/telegram_routine_bot.git
   cd telegram_routine_bot
   ```

2. **가상환경 생성 및 활성화**
   - **Windows**: 
     ```bash
     python -m venv .venv
     .venv\Scripts\activate
     ```
   - **Mac/Linux**: 
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```

3. **설정 스크립트 실행**
   ```bash
   python init_setup.py  # Mac/Linux는 python3 사용 가능
   ```
   *이 스크립트는 패키지 설치부터 `.env` 파일 생성, 구글 인증 파일 확인 및 연결 테스트까지 도와줍니다.*

---

## 🛠️ 직접 설정 (수동)

### 1. 사전 준비
- **Python 3.10+**
가상환경 사용을 강력히 권장합니다.

**Windows의 경우:**
```cmd
python -m venv .venv
.venv\Scripts\activate
```

**macOS/Linux의 경우:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. 의존성 패키지 설치

활성화된 가상환경 내에서 필요한 라이브러리를 설치합니다.
*(참고: `tzdata`는 윈도우/리눅스 환경 관계없이 `ZoneInfo` 시간대능이 안정적으로 동작하게 해줍니다.)*

```bash
pip install python-telegram-bot[job-queue] gspread python-dotenv aiohttp tzdata
```

### 4. 환경 설정

봇 토큰 등 중요 정보를 소스코드에 노출시키지 않기 위해 `.env` 파일을 사용합니다.

```bash
# 템플릿 파일을 복사하여 실제 환경변수 파일 생성 (Windows)
copy .env.example .env
# macOS/Linux의 경우: cp .env.example .env
```
`credentials.json` 파일을 루트 폴더에 준비하세요.

생성된 `.env` 파일을 열어 실제 발급받은 값을 입력하세요:

```env
# 텔레그램 봇 설정
TELEGRAM_BOT_TOKEN=여기에_텔레그램_토큰_입력
GROUP_CHAT_ID=여기에_그룹채팅방_ID_입력

# 구글 시트 연동 설정
GOOGLE_SHEET_NAME=구글_스프레드시트_문서이름
GOOGLE_CREDENTIALS_FILE=credentials.json
```
*Tip: `GROUP_CHAT_ID`는 봇을 방에 초대한 후 메시지를 남기고 텔레그램 Web API(`/getUpdates`)를 확인하거나, `@RawDataBot` 같은 유틸리티 봇을 활용해 쉽게 알아낼 수 있습니다.*

### 5. Google Sheets API 설정

1. [Google Cloud Console](https://console.cloud.google.com/)에서 프로젝트 생성 후 **Google Sheets API** 활성화
2. **서비스 계정(Service Account)** 생성 후 **JSON 키 파일** 다운로드
3. 다운로드 받은 JSON 파일을 `credentials.json`으로 이름 변경 후, 프로젝트 최상단 폴더에 저장
4. 데이터를 저장할 Google 스프레드시트 문서 생성 후 하단 탭에 아래 6개 워크시트 생성 (이름 정확히 일치):
   - `Users`, `Routines`, `Logs`, `Insights`, `AI_Recommendations`, `Weekly_Achievement`
5. **중요:** 해당 스프레드시트 우측 상단 '공유' 버튼을 누르고, `credentials.json` 파일 안의 `client_email` 주소를 추가하여 **'편집자'** 권한 부여

> 📋 각 시트의 1행(컬럼 이름) 구조는 `db_schema/` 폴더 내의 CSV 파일들을 참고하여 똑같이 작성해 주세요.

### 6. 봇 실행

모든 준비가 끝났다면 아래 명령어로 봇을 실행합니다:

```bash
python main.py
```
*(실행 중 봇의 터미널 창에는 멤버들의 루틴 등록 및 인증 행동이 실시간 로그로 출력됩니다. 서버에서 24시간 가동하려면 `screen`, `tmux`, `nohup`, 또는 `systemd` 등을 활용하세요.)*

---

## 📱 명령어

### 사용자 명령어

| 명령어 | 설명 |
|--------|------|
| `/start` | 환영 메시지 및 명령어 안내 |
| `/reg [루틴이름]` | 새 루틴 등록 (1:1 개인 채팅 전용) |
| `/status` | 내 루틴 현황 및 주간 달성률 확인 |
| `/insight [내용]` | 인사이트 공유 (1:1 개인 채팅 전용) |
| `/del` 또는 `/delete` | 등록된 루틴 취소/삭제 (1:1 개인 채팅 전용) |
| `/rank` | 포인트 TOP 3 리더보드 확인 |
| 📸 사진 + 캡션 | 루틴 완료 인증 (1:1 개인 채팅 전용) |

### 관리자/테스트 명령어

| 명령어 | 설명 |
|--------|------|
| `/testmorning` | 아침 메시지 즉시 발송 |
| `/testevening` | 저녁 메시지 즉시 발송 |
| `/testweekly` | 주간 TOP 3 즉시 발송 |
| `/testinsightbrief` | 주간 인사이트 AI 브리핑 즉시 발송 |
| `/testrec` | 본인에게 AI 루틴 추천 즉시 발송 |
| `/testinitweekly` | 주간 달성률 시트 초기화 |

---

## ⏰ 자동 알림 스케줄

| 알림 | 대상 | 시간 (KST) | 주기 |
|------|------|------------|------|
| 🌅 아침 메시지 | 그룹채팅 | 09:00 | 매일 |
| 🌙 저녁 메시지 | 그룹채팅 | 21:00 | 매일 |
| 🏆 주간 TOP 3 | 그룹채팅 | 일요일 12:00 | 매주 |
| 🧠 주간 인사이트 AI 브리핑 | 그룹채팅 | 일요일 12:05 | 매주 |
| 📅 주간 초기화 | 시스템 | 월요일 00:01 | 매주 |
| 💡 AI 추천 | 개인 DM | 매월 15일 12:00 | 매월 |

> ⚠️ 봇이 꺼져 있는 동안 지나간 발송 시각의 메시지는 **생략**됩니다 (소급 발송 없음).

---

## 🤖 AI 기능 (선택사항)

AI 기능은 `main.py` 실행 시 자동으로 Ollama 서버 상태를 확인하고, 필요하면 자동 실행을 시도합니다.
따라서 별도 터미널에서 `ollama run ...` 을 수동 실행하지 않아도 됩니다.

> 전제 조건: Ollama가 설치되어 있고, `ollama` 명령어를 실행할 수 있어야 합니다.

자동 동작 기본값:
- `AUTO_START_OLLAMA=true`: 서버 미실행 시 자동 실행 시도
- `AUTO_PULL_OLLAMA_MODEL=true`: 모델(`gemma4:e2b`)이 없으면 자동 다운로드

- **키워드 추출**: 인사이트 제출 시 자동으로 키워드 3개 추출
- **주간 인사이트 브리핑**: 해당 주차 인사이트를 분석해 일요일 12:05에 그룹 브리핑 생성
- **루틴 추천**: 현재 루틴, 최근 인증 기록, 인사이트를 분석하여 새로운 맞춤 루틴 추천

> Ollama 자동 실행/다운로드에 실패해도 봇은 계속 실행되며, AI 기능만 제한될 수 있습니다.

---

## 🔐 보안

모든 민감 정보는 환경변수로 관리됩니다:

- 봇 토큰, 채팅 ID → `.env` 파일에서 로드 (Git 제외)
- Google 서비스 계정 키 → `credentials.json` (Git 제외)
- `.env.example`으로 안전한 설정 템플릿 제공

---

## ❓ 문제 해결 (Troubleshooting)

### Windows: 스크립트 실행 권한 오류 (Execution Policy)
`.venv\Scripts\activate` 실행 시 오류가 발생한다면:
1. PowerShell을 **관리자 권한**으로 실행합니다.
2. `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` 명령어를 실행합니다.
3. 터미널을 다시 켜고 시도해보세요.

### Python 명령어를 찾을 수 없음
- `python` 대신 `python3`를 입력해보세요.
- Windows의 경우, Python 설치 시 "Add Python to PATH" 항목을 체크했는지 확인하세요.

### Google Sheets 접근 권한 오류
- `credentials.json` 파일 내의 `client_email` 주소를 복사하여, 사용할 구글 스프레드시트에 **편집자(Editor)** 권한으로 공유했는지 확인하세요.

---

## 📄 라이선스

이 프로젝트는 교육 및 커뮤니티 목적으로 제공됩니다.

---

## 🙏 감사의 말

**산스 AI루틴클럽** 커뮤니티를 위해 만들어졌습니다 — 서로의 책임감과 AI 인사이트로 더 나은 습관을 함께 만들어가는 그룹입니다.
