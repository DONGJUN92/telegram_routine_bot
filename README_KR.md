# 산스 AI루틴클럽 - 텔레그램 봇

> 루틴 인증, 포인트, 주간 리포트, AI 인사이트, 소성취 챌린지를 운영하는 텔레그램 커뮤니티 봇입니다.

[View English README](./README.md)

산스 AI루틴클럽 봇은 멤버가 봇과의 1:1 대화에서 루틴을 등록하고, 사진+캡션으로 인증하며, 그룹방에는 인증/인사이트/리포트가 공유되도록 설계되어 있습니다. Google Sheets를 데이터베이스로 사용하고, Ollama 로컬 모델로 AI 분석과 추천을 생성합니다.

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| 사진 인증 | 1:1 대화방에서 사진+캡션을 보내 루틴 완료를 인증합니다. |
| 루틴 관리 | 루틴 등록, 이름 수정, 현황 확인, 삭제를 지원합니다. 신규 루틴은 현재 주 1회(`1time`) 목표로 즉시 등록됩니다. |
| 포인트와 랭킹 | 루틴 인증은 +10점, 인사이트 공유는 +15점입니다. 누적 인증 횟수에 따라 보너스 포인트가 붙습니다. |
| 주간 달성률 | ISO 주차 기준으로 `Weekly_Achievement` 시트에 목표/완료/달성률을 기록합니다. |
| 출석률 집계 | `Weekly_Achievement` 데이터를 `출석률` 시트에 유저별 주차 출석률로 집계할 수 있습니다. |
| 인사이트 아카이브 | 인사이트를 AI가 카테고리화하고 한 줄 요약해 지정 토픽에 아카이빙합니다. |
| AI 이미지 코칭 | 인증 사진을 Ollama 멀티모달 분석에 보내 그룹 공유용 코칭 코멘트를 생성합니다. |
| 주간 인사이트 브리핑 | 한 주의 인사이트를 AI가 요약해 일요일 그룹방에 공유합니다. |
| 주간 카드뉴스 | 이번 주 주목 루틴을 6장 카드뉴스 이미지로 생성해 미디어 그룹으로 발송합니다. |
| AI 루틴 추천 | 매월 15일 현재 루틴, 최근 인증, 인사이트를 바탕으로 개인 맞춤 루틴을 추천합니다. |
| AI 소성취 챌린지 | 월/금/토 15:30에 AI가 생성한 소성취 미션을 지정 그룹 토픽으로 발송합니다. |
| 자동 알림 | 아침 메시지, 일일 대시보드, 저녁 리마인더, 주간 리포트, 월간 추천을 JobQueue로 예약 실행합니다. |

---

## 기술 스택

| 항목 | 기술 |
|------|------|
| 언어 | Python 3.10+ |
| 텔레그램 프레임워크 | `python-telegram-bot[job-queue]` |
| 저장소 | Google Sheets (`gspread`) |
| AI 엔진 | Ollama 로컬 API, 기본 모델 `gemma4:e2b` |
| 스케줄러 | Telegram `JobQueue` 기반 APScheduler |
| 이미지 생성 | Pillow 기반 카드뉴스 렌더러 |
| 환경설정 | `.env` + `python-dotenv` |

---

## 프로젝트 구조

```text
telegram_routine_bot/
├── main.py                  # 봇 명령어, 인증 흐름, 스케줄러
├── db_utils.py              # Google Sheets 비동기 헬퍼
├── ai_utils.py              # Ollama 프롬프트와 AI API 호출
├── card_news.py             # 주간 카드뉴스 이미지 생성
├── init_setup.py            # 초기 설정 도우미
├── reset.py                 # 텔레그램 봇 명령어 메뉴 리셋
├── requirements.txt
├── .env.example
├── credentials.json         # Google 서비스 계정 키, Git 미추적
├── db_schema/               # 샘플 시트 스키마
└── routine_bot_improvement_specs.md
```

---

## 빠른 시작

1. 저장소를 클론하고 폴더로 이동합니다.

```bash
git clone https://github.com/DONGJUN92/telegram_routine_bot.git
cd telegram_routine_bot
```

2. 가상환경을 만들고 활성화합니다.

```cmd
python -m venv .venv
.venv\Scripts\activate
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. 의존성을 설치합니다.

```bash
pip install -r requirements.txt
```

4. `.env` 파일을 생성합니다.

```cmd
copy .env.example .env
```

macOS/Linux:

```bash
cp .env.example .env
```

5. Google 서비스 계정 키를 `credentials.json`으로 루트 폴더에 두고, `.env` 값을 채운 뒤 실행합니다.

```bash
python main.py
```

---

## 환경변수

```env
# Telegram Bot Settings
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
GROUP_CHAT_ID=your_group_chat_id_here
INSIGHT_CHAT_ID=-1003779149038
INSIGHT_THREAD_ID=594
CATALYST_CHAT_ID=-1003779149038
CATALYST_THREAD_ID=4

# Google Sheets Settings
GOOGLE_SHEET_NAME=your_google_sheet_name_here
GOOGLE_CREDENTIALS_FILE=credentials.json

# Ollama Auto-Start Settings
AUTO_START_OLLAMA=true
AUTO_PULL_OLLAMA_MODEL=true
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL_NAME=gemma4:e2b
OLLAMA_BIN=ollama
OLLAMA_STARTUP_WAIT_SECONDS=20

# Alarm Schedules, KST HH:MM
MORNING_ALARM_TIME=09:00
EVENING_DASHBOARD_TIME=18:00
EVENING_REMINDER_TIME=21:00
CATALYST_ALARM_TIME=15:30
```

참고:

- `GROUP_CHAT_ID`: 루틴 등록 공유, 인증 공유, 대시보드, 리마인더, 주간 리포트, 카드뉴스가 발송되는 기본 그룹방입니다.
- `INSIGHT_CHAT_ID` + `INSIGHT_THREAD_ID`: AI 인사이트 아카이브가 발송되는 그룹/토픽입니다.
- `CATALYST_CHAT_ID` + `CATALYST_THREAD_ID`: 예약 실행되는 소성취 챌린지가 발송되는 그룹/토픽입니다.
- `/testcatalyst`는 명령어가 입력된 방/토픽으로 전송되고, cron job은 `CATALYST_CHAT_ID` / `CATALYST_THREAD_ID`로 전송됩니다.

---

## Google Sheets 설정

`GOOGLE_SHEET_NAME`과 같은 이름의 스프레드시트를 만들고, 아래 워크시트를 정확한 이름으로 생성하세요.

| 워크시트 | 용도 |
|----------|------|
| `Users` | 유저 정보, 방어권, 포인트, 타임존 |
| `Routines` | 루틴 정보와 누적 인증 횟수 |
| `Logs` | 루틴 인증 로그 |
| `Insights` | 인사이트와 AI 추출 키워드 |
| `AI_Recommendations` | 월간 AI 루틴 추천 기록 |
| `Weekly_Achievement` | 주차별 목표/완료/달성률 |
| `출석률` | 유저별 주차 출석률 집계 |

그리고 `credentials.json` 안의 `client_email`을 해당 스프레드시트에 편집자 권한으로 공유해야 합니다.

---

## 명령어

### 사용자 명령어

| 명령어 | 설명 |
|--------|------|
| `/start` | 환영 메시지와 명령어 안내 |
| `/reg [루틴이름]` | 1:1 대화방에서 새 루틴 등록. 현재는 `Lifestyle`, `1time`, `active`로 저장됩니다. |
| `/edit` 또는 `/modify` | 1:1 대화방에서 활성 루틴 이름 수정 |
| `/status` | 내 루틴, 누적 인증 횟수, 주간 달성률 확인 |
| `/insight [내용]` | 1:1 대화방에서 인사이트 공유. +15점과 방어권 +1 |
| `/del` 또는 `/delete` | 1:1 대화방에서 활성 루틴 삭제 |
| `/rank` | 포인트 TOP 3 리더보드 확인 |
| `/cancel` | 진행 중인 수정 흐름 취소 |
| 사진 + 캡션 | 1:1 대화방에서 루틴 인증. 활성 루틴이 여러 개면 버튼으로 선택합니다. |

그룹방에서 1:1 전용 명령어를 호출하면 봇과의 개인 대화로 이동하는 버튼이 표시됩니다.

### 관리자/테스트 명령어

| 명령어 | 설명 |
|--------|------|
| `/testhelp` | 테스트 명령어 목록 출력 |
| `/testmorning` | 아침 메시지를 명령어 입력 방으로 즉시 발송 |
| `/testdashboard` | 일일 대시보드를 명령어 입력 방으로 즉시 발송 |
| `/testreminder` | 저녁 리마인더를 명령어 입력 방으로 즉시 발송 |
| `/testcatalyst` | 소성취 챌린지를 생성해 명령어 입력 방/토픽으로 즉시 발송 |
| `/testweekly` | 주간 TOP 3를 명령어 입력 방으로 즉시 발송 |
| `/testinsightbrief` | 주간 인사이트 브리핑을 생성해 명령어 입력 방으로 즉시 발송 |
| `/testweeklycard` | 주간 카드뉴스를 생성해 명령어 입력 방으로 즉시 발송 |
| `/testrec` | 본인에게 월간 AI 루틴 추천 즉시 발송 |
| `/testinitweekly` | 이번 주 주간 달성률 행 초기화 |
| `/testinsight` | AI 인사이트 카테고리화와 아카이브 토픽 전송 테스트 |
| `/testmultimodal` 또는 `/testimage` | 더미 이미지로 Ollama 이미지 분석 테스트 |
| `/testattendance [YYYY-WNN]` | 지정 주차부터 출석률 집계. 기본값은 `2026-W16` |

---

## 자동 스케줄

모든 시간은 KST 기준입니다.

| 작업 | 대상 | 시간 | 주기 |
|------|------|------|------|
| 아침 메시지 | `GROUP_CHAT_ID` | `MORNING_ALARM_TIME`, 기본 09:00 | 매일 |
| 일일 대시보드 | `GROUP_CHAT_ID` | `EVENING_DASHBOARD_TIME`, 기본 18:00 | 매일 |
| 저녁 리마인더 | `GROUP_CHAT_ID` | `EVENING_REMINDER_TIME`, 기본 21:00 | 매일 |
| 소성취 챌린지 | `CATALYST_CHAT_ID` / `CATALYST_THREAD_ID` | `CATALYST_ALARM_TIME`, 기본 15:30 | 월/금/토 |
| 월간 AI 루틴 추천 | 개인 DM | 매월 15일 12:00 | 매월 |
| 주간 TOP 3 | `GROUP_CHAT_ID` | 일요일 12:00 | 매주 |
| 주간 인사이트 브리핑 | `GROUP_CHAT_ID` | 일요일 12:05 | 매주 |
| 주간 카드뉴스 | `GROUP_CHAT_ID` | 일요일 12:10 | 매주 |
| 주간 달성률 초기화와 출석률 정산 | Google Sheets | 월요일 00:01 | 매주 |

봇이 꺼져 있는 동안 지나간 예약 실행은 소급 발송되지 않습니다. 소성취 챌린지는 여러 봇 프로세스가 겹쳐 실행될 때 중복 발송을 줄이기 위해 날짜별 로컬 락 파일도 사용합니다.

---

## AI 동작

Ollama는 선택 사항이지만, AI 기능에는 필요합니다. 봇 시작 시 아래 설정에 따라 Ollama 서버 실행과 모델 다운로드를 자동 시도할 수 있습니다.

- `AUTO_START_OLLAMA=true`: 로컬 API가 꺼져 있으면 `ollama serve` 실행 시도
- `AUTO_PULL_OLLAMA_MODEL=true`: `OLLAMA_MODEL_NAME` 모델이 없으면 다운로드 시도

AI 기반 기능:

- 인사이트 키워드 추출
- 인사이트 카테고리/한 줄 요약 생성
- 주간 인사이트 브리핑
- 월간 루틴 추천
- 인증 사진 기반 AI 코칭 코멘트
- 주간 카드뉴스용 루틴 요약
- 소성취 챌린지 미션 생성

소성취 챌린지 규칙:

- 월요일: 글쓰기 미션
- 금요일: 이미지 또는 동영상 생성 미션
- 토요일: 내게 필요한 간단한 토이 서비스 만들기 미션
- Ollama 또는 모델 호출 실패, 빈 응답이면 발송하지 않습니다. 정적 폴백 문구는 사용하지 않습니다.

---

## 문제 해결

### `Message thread not found`

설정한 토픽 ID가 해당 채팅방에 없거나, 명령어가 입력된 컨텍스트의 `message_thread_id`를 재사용할 수 없을 때 발생할 수 있습니다. `INSIGHT_THREAD_ID`, `CATALYST_THREAD_ID`, 봇의 토픽 접근 권한을 확인하세요.

### Google Sheets 접근 권한 오류

`credentials.json` 안의 `client_email`을 스프레드시트에 편집자 권한으로 공유했는지 확인하세요.

### AI 응답이 비어 있음

Ollama 설치 여부, `OLLAMA_BIN`, `OLLAMA_MODEL_NAME`, 모델 다운로드 상태를 확인하세요. AI 기능이 실패해도 봇은 계속 실행되지만, AI 의존 메시지는 생략될 수 있습니다.

### Windows 가상환경 활성화 오류

PowerShell을 관리자 권한으로 실행한 뒤 아래 명령어를 실행하세요.

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## 보안

- `.env`: 봇 토큰, 채팅 ID, 스케줄 설정 저장
- `credentials.json`: Google 서비스 계정 키 저장
- 두 파일은 Git에 올리지 않는 것을 권장합니다.

---

## 라이선스

이 프로젝트는 교육 및 커뮤니티 운영 목적으로 제공됩니다.
