# 🌱 산스 AI루틴클럽 — 텔레그램 봇

> **AI 기반 개인 맞춤 루틴 추천과 게이미피케이션으로 습관을 만드는 텔레그램 봇**

[View English README](./README.md)

산스 AI루틴클럽 봇은 텔레그램 그룹 내에서 멤버들의 **루틴(습관) 인증을 관리**하고, **포인트·랭킹 시스템**으로 동기를 부여하며, **AI가 개인 맞춤 루틴을 추천**하는 자동화 봇입니다.

---

## ✨ 주요 기능

| 기능 | 설명 |
|------|------|
| 📸 **사진 인증** | 사진 + 캡션 업로드로 루틴 인증 완료 |
| 🏆 **포인트 & 랭킹** | 인증, 인사이트 공유로 포인트 적립 및 리더보드 경쟁 |
| 📊 **주간 달성률** | ISO 주차 기반으로 이번 주 달성률 관리 및 아카이빙 |
| 💡 **인사이트 공유** | 50자 이상 성찰 작성 시 보너스 포인트 + 방어권 |
| 🤖 **AI 루틴 추천** | 로컬 LLM(Ollama)을 활용한 월간 맞춤 루틴 추천 |
| 🔔 **자동 알림** | 매일 아침/저녁 동기부여 메시지 + 주간 TOP 3 발표 |
| 👥 **그룹 활동 공유** | 등록, 인증, 인사이트 활동이 그룹에 자동 공유 |

---

## 🛠️ 기술 스택

| 항목 | 기술 |
|------|------|
| 언어 | Python 3.13 |
| 프레임워크 | `python-telegram-bot` v20+ (비동기) |
| 데이터베이스 | Google Sheets (`gspread`) |
| AI 엔진 | Ollama (로컬) — `gemma3:1b` 모델 |
| 스케줄러 | APScheduler (JobQueue) |
| 환경설정 | `python-dotenv` 환경변수 관리 |

---

## 📁 프로젝트 구조

```
sans-ai-routine-bot/
├── main.py                 # 봇 핵심 로직, 명령어, 스케줄러
├── db_utils.py             # Google Sheets 비동기 DB 유틸리티
├── ai_utils.py             # AI 기능 (키워드 추출, 루틴 추천)
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

## 🚀 시작하기

### 사전 준비

- **Python 3.10+**
- **Telegram Bot Token** — [@BotFather](https://t.me/BotFather)에서 봇 생성
- **Google Cloud 서비스 계정** — Google Sheets API 접근용
- **Ollama** (선택사항) — AI 기능 사용 시에만 필요

### 1. 저장소 클론

```bash
git clone https://github.com/<your-username>/sans-ai-routine-bot.git
cd sans-ai-routine-bot
```

### 2. 가상환경 설정

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

### 3. 의존성 설치

```bash
pip install python-telegram-bot gspread python-dotenv aiohttp
```

### 4. 환경변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 열어 실제 값을 입력하세요:

```env
# Telegram Bot 설정
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
GROUP_CHAT_ID=your_group_chat_id_here

# Google Sheets 설정
GOOGLE_SHEET_NAME=your_google_sheet_name_here
GOOGLE_CREDENTIALS_FILE=credentials.json
```

### 5. Google Sheets 설정

1. Google Cloud 프로젝트 생성 후 **Google Sheets API** 활성화
2. **서비스 계정** 생성 후 JSON 키 파일 다운로드
3. 프로젝트 루트에 `credentials.json`으로 저장
4. Google 스프레드시트 생성 후 아래 워크시트 추가:
   - `Users`, `Routines`, `Logs`, `Insights`, `AI_Recommendations`, `Weekly_Achievement`
5. 스프레드시트를 서비스 계정 이메일(`credentials.json`의 `client_email`)과 공유

> 📋 각 시트의 컬럼 구조는 `db_schema/` 폴더의 CSV 파일을 참고하세요.

### 6. 봇 실행

```bash
python main.py
```

---

## 📱 명령어

### 사용자 명령어

| 명령어 | 설명 |
|--------|------|
| `/start` | 환영 메시지 및 명령어 안내 |
| `/reg [루틴이름]` | 새 루틴 등록 (1:1 채팅 전용) |
| `/status` | 내 루틴 현황 및 주간 달성률 확인 |
| `/insight [내용]` | 인사이트 공유 (50자 이상, 1:1 채팅 전용) |
| `/del` | 등록된 루틴 삭제 (1:1 채팅 전용) |
| `/rank` | 포인트 TOP 3 리더보드 확인 |
| 📸 사진 + 캡션 | 루틴 인증 완료 (1:1 채팅 전용) |

### 관리자/테스트 명령어

| 명령어 | 설명 |
|--------|------|
| `/testmorning` | 아침 메시지 즉시 발송 |
| `/testevening` | 저녁 메시지 즉시 발송 |
| `/testweekly` | 주간 TOP 3 즉시 발송 |
| `/testrec` | 본인에게 AI 루틴 추천 즉시 발송 |
| `/testinitweekly` | 주간 달성률 시트 초기화 |

---

## ⏰ 자동 알림 스케줄

| 알림 | 대상 | 시간 (KST) | 주기 |
|------|------|------------|------|
| 🌅 아침 메시지 | 그룹채팅 | 09:00 | 매일 |
| 🌙 저녁 메시지 | 그룹채팅 | 21:00 | 매일 |
| 🏆 주간 TOP 3 | 그룹채팅 | 일요일 12:00 | 매주 |
| 📅 주간 초기화 | 시스템 | 월요일 00:01 | 매주 |
| 💡 AI 추천 | 개인 DM | 매월 15일 12:00 | 매월 |

> ⚠️ 봇이 꺼져 있는 동안 지나간 발송 시각의 메시지는 **생략**됩니다 (소급 발송 없음).

---

## 🤖 AI 기능 (선택사항)

AI 기능을 사용하려면 [Ollama](https://ollama.ai)를 로컬에서 실행해야 합니다:

```bash
ollama run gemma3:1b
```

- **키워드 추출**: 인사이트 제출 시 자동으로 키워드 3개 추출
- **루틴 추천**: 현재 루틴, 최근 인증 기록, 인사이트를 분석하여 새로운 맞춤 루틴 추천

> Ollama가 실행 중이지 않아도 다른 봇 기능에는 영향이 없습니다.

---

## 🔐 보안

모든 민감 정보는 환경변수로 관리됩니다:

- 봇 토큰, 채팅 ID → `.env` 파일에서 로드 (Git 제외)
- Google 서비스 계정 키 → `credentials.json` (Git 제외)
- `.env.example`으로 안전한 설정 템플릿 제공

---

## 📄 라이선스

이 프로젝트는 교육 및 커뮤니티 목적으로 제공됩니다.

---

## 🙏 감사의 말

**산스 AI루틴클럽** 커뮤니티를 위해 만들어졌습니다 — 서로의 책임감과 AI 인사이트로 더 나은 습관을 함께 만들어가는 그룹입니다.
