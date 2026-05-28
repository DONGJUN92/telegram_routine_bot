# Sans AI Routine Club - Telegram Bot

> A Telegram community bot for routine verification, points, weekly reporting, AI insights, and small-achievement challenges.

[한국어 README 보기](./README_KR.md)

Sans AI Routine Club Bot helps members build lightweight habits in a Telegram community. Members register routines in DM, verify them with photo + caption, earn points, share insights, and receive scheduled AI-powered reports and prompts.

---

## Key Features

| Feature | Description |
|---------|-------------|
| Photo verification | Members verify routines by sending a photo with a caption in a private chat with the bot. |
| Routine management | Register, rename, check status, and delete active routines. New routines are currently registered as weekly `1time` goals. |
| Points and ranking | Routine verification gives +10 points. Insight sharing gives +15 points. Cumulative verification milestones add bonus points. |
| Weekly achievement | Weekly targets and completion rates are stored in `Weekly_Achievement` using ISO week IDs. |
| Attendance summary | Weekly achievement data can be summarized into the `출석률` worksheet. |
| Insight archive | Insights are summarized/category-tagged by AI and can be posted to a configured Telegram topic. |
| AI image coaching | Routine verification photos can be analyzed by Ollama for a warmer group-share caption. |
| Weekly AI briefing | Weekly insights are collected and summarized into a Sunday group briefing. |
| Weekly card news | Weekly routine highlights are rendered into 6 card-news images and sent as a media group. |
| AI routine recommendations | Monthly personalized routine recommendations are generated from routines, logs, and insights. |
| Small-achievement challenge | AI-generated catalyst missions run only on Mon/Fri/Sat at 15:30 KST and are sent to a configured group topic. |
| Scheduled messages | Morning motivation, daily dashboard, evening reminder, weekly reports, and monthly recommendations are scheduled with JobQueue/APScheduler. |

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.10+ |
| Telegram framework | `python-telegram-bot[job-queue]` |
| Storage | Google Sheets via `gspread` |
| AI engine | Ollama local API, default model `gemma4:e2b` |
| Scheduler | APScheduler through Telegram `JobQueue` |
| Image generation | Pillow-based card news renderer |
| Config | `.env` via `python-dotenv` |

---

## Project Structure

```text
telegram_routine_bot/
├── main.py                  # Bot commands, verification flow, schedulers
├── db_utils.py              # Async Google Sheets helpers
├── ai_utils.py              # Ollama prompts and AI API calls
├── card_news.py             # Weekly card-news image renderer
├── init_setup.py            # Interactive setup helper
├── reset.py                 # Telegram bot command reset helper
├── requirements.txt
├── .env.example
├── credentials.json         # Google service-account key, not tracked
├── db_schema/               # Sample sheet schemas
└── routine_bot_improvement_specs.md
```

---

## Quick Start

1. Clone and enter the repository.

```bash
git clone https://github.com/DONGJUN92/telegram_routine_bot.git
cd telegram_routine_bot
```

2. Create and activate a virtual environment.

```bash
python -m venv .venv
.venv\Scripts\activate
```

On macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Install dependencies.

```bash
pip install -r requirements.txt
```

4. Create `.env` from the template.

```bash
copy .env.example .env
```

On macOS/Linux:

```bash
cp .env.example .env
```

5. Put your Google service account key at `credentials.json`, fill `.env`, then run:

```bash
python main.py
```

---

## Environment Variables

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

Notes:

- `GROUP_CHAT_ID` is the main community group used for routine registration, verification, dashboard, reminders, weekly reports, and card news.
- `INSIGHT_CHAT_ID` + `INSIGHT_THREAD_ID` are used for AI insight archive posts.
- `CATALYST_CHAT_ID` + `CATALYST_THREAD_ID` are used by the scheduled small-achievement challenge.
- `/testcatalyst` sends to the chat/topic where the command was entered, while the cron job sends to `CATALYST_CHAT_ID` / `CATALYST_THREAD_ID`.

---

## Google Sheets

Create a spreadsheet whose name matches `GOOGLE_SHEET_NAME`, then add these worksheets:

| Worksheet | Purpose |
|-----------|---------|
| `Users` | User profile, shield count, points, timezone |
| `Routines` | Active routines and cumulative verification count |
| `Logs` | Routine verification logs |
| `Insights` | User insights and extracted AI keywords |
| `AI_Recommendations` | Monthly AI recommendations |
| `Weekly_Achievement` | Weekly target/done/rate records |
| `출석률` | Aggregated weekly attendance rate by user |

Share the spreadsheet with the `client_email` in `credentials.json` as an Editor.

---

## Commands

### User Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and command guide |
| `/reg [routine name]` | Register a new routine in DM. It is currently saved as `Lifestyle`, `1time`, `active`. |
| `/edit` or `/modify` | Rename one of your active routines in DM |
| `/status` | View your active routines, cumulative verification count, and weekly achievement |
| `/insight [text]` | Share an insight in DM; earns +15 points and +1 shield |
| `/del` or `/delete` | Delete an active routine in DM |
| `/rank` | Show the TOP 3 points leaderboard |
| `/cancel` | Cancel the current edit flow |
| Photo + caption | Verify a routine in DM. If multiple routines are active, the bot asks which routine to apply. |

Group calls for DM-only commands show a button that redirects the user to the bot's private chat.

### Test/Admin Commands

| Command | Description |
|---------|-------------|
| `/testhelp` | Show test command list |
| `/testmorning` | Send the morning message to the command chat |
| `/testdashboard` | Send the daily dashboard to the command chat |
| `/testreminder` | Send the evening reminder to the command chat |
| `/testcatalyst` | Generate a small-achievement challenge and send it to the command chat/topic |
| `/testweekly` | Send weekly TOP 3 to the command chat |
| `/testinsightbrief` | Generate weekly insight briefing and send it to the command chat |
| `/testweeklycard` | Generate and send weekly card news to the command chat |
| `/testrec` | Generate a monthly AI routine recommendation for yourself |
| `/testinitweekly` | Initialize current-week achievement rows |
| `/testinsight` | Test AI insight categorization and archive-topic posting |
| `/testmultimodal` or `/testimage` | Test Ollama image analysis with a dummy image |
| `/testattendance [YYYY-WNN]` | Aggregate attendance from the given ISO week, default `2026-W16` |

---

## Scheduled Jobs

All times are KST.

| Job | Target | Time | Frequency |
|-----|--------|------|-----------|
| Morning message | `GROUP_CHAT_ID` | `MORNING_ALARM_TIME`, default 09:00 | Daily |
| Daily dashboard | `GROUP_CHAT_ID` | `EVENING_DASHBOARD_TIME`, default 18:00 | Daily |
| Evening reminder | `GROUP_CHAT_ID` | `EVENING_REMINDER_TIME`, default 21:00 | Daily |
| Small-achievement challenge | `CATALYST_CHAT_ID` / `CATALYST_THREAD_ID` | `CATALYST_ALARM_TIME`, default 15:30 | Monday, Friday, Saturday |
| Monthly AI recommendation | Individual DM | 15th, 12:00 | Monthly |
| Weekly TOP 3 | `GROUP_CHAT_ID` | Sunday 12:00 | Weekly |
| Weekly insight briefing | `GROUP_CHAT_ID` | Sunday 12:05 | Weekly |
| Weekly card news | `GROUP_CHAT_ID` | Sunday 12:10 | Weekly |
| Weekly achievement init and attendance rollup | Google Sheets | Monday 00:01 | Weekly |

If the bot is offline when a scheduled time passes, that run is skipped. The small-achievement challenge also uses a local daily lock file to reduce duplicate scheduled sends if multiple bot processes overlap.

---

## AI Behavior

Ollama is optional but required for AI-powered features. On startup, the bot can try to start the Ollama server and pull the configured model:

- `AUTO_START_OLLAMA=true`: try `ollama serve` if the local API is unavailable
- `AUTO_PULL_OLLAMA_MODEL=true`: pull `OLLAMA_MODEL_NAME` if missing

AI-powered features:

- Insight keyword extraction
- Insight category and one-line archive summary
- Weekly insight briefing
- Monthly routine recommendation
- Photo-based AI coaching comment for routine verification shares
- Weekly card-news routine summaries
- Small-achievement catalyst mission

Small-achievement challenge behavior:

- Monday: writing mission
- Friday: image or video generation mission
- Saturday: small toy service mission
- If Ollama/model generation fails or returns an empty response, the challenge is not sent. There is no static fallback message.

---

## Troubleshooting

### `Message thread not found`

The configured Telegram topic ID does not exist in that chat, or the command was sent from a context whose `message_thread_id` cannot be reused. Check `INSIGHT_THREAD_ID`, `CATALYST_THREAD_ID`, and whether the bot has access to the topic.

### Google Sheets access denied

Share the spreadsheet with the service account `client_email` from `credentials.json` and grant Editor permission.

### Ollama AI output is missing

Check that Ollama is installed, `OLLAMA_BIN` is valid, and the model in `OLLAMA_MODEL_NAME` is available. The bot continues running when AI features fail, but AI-dependent messages may be skipped.

### Windows activation blocked

Run PowerShell as Administrator and execute:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## Security

- `.env` stores tokens, chat IDs, and schedule configuration.
- `credentials.json` stores Google credentials.
- Both should stay out of Git.

---

## License

This project is provided as-is for educational and community use.
