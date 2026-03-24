# 🌱 Sans AI Routine Club — Telegram Bot

> **A gamified habit-tracking Telegram bot with AI-powered routine recommendations**

[한국어 README 보기 (Korean)](./README_KR.md)

Sans AI Routine Club Bot helps community members **build and maintain daily routines** through photo-based verification, a points & ranking system, and personalized AI recommendations — all within a Telegram group chat.

---

## ✨ Key Features

| Feature | Description |
|---------|-------------|
| 📸 **Photo Verification** | Upload a photo with a caption to verify routine completion |
| 🏆 **Points & Ranking** | Earn points for verifications and insights; compete on the leaderboard |
| 📊 **Weekly Achievement** | Track weekly completion rates with ISO-week-based archiving |
| 💡 **Insight Sharing** | Share 50+ character reflections to earn bonus points and shields |
| 🤖 **AI Recommendations** | Monthly personalized routine suggestions powered by local LLM (Ollama) |
| 🔔 **Scheduled Messages** | Automated morning/evening motivation and weekly TOP 3 leaderboard |
| 👥 **Group Activity Feed** | Routine registrations, verifications, and insights are shared in the group chat |

---

## 🛠️ Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.10+ |
| Framework | `python-telegram-bot[job-queue]` v20+ (async) |
| Database | Google Sheets via `gspread` |
| AI Engine | Ollama (local) — `gemma3:1b` model |
| Scheduler | APScheduler (JobQueue) |
| Config | `python-dotenv` for environment variables |

---

## 📁 Project Structure

```
sans-ai-routine-bot/
├── main.py                 # Bot core logic, commands, and schedulers
├── db_utils.py             # Google Sheets async database utilities
├── ai_utils.py             # AI functions (keyword extraction, recommendations)
├── reset.py                # Bot command menu reset utility
├── .env.example            # Environment variable template
├── .gitignore              # Git exclusion rules
├── credentials.json        # Google Cloud service account key (not tracked)
├── db_schema/              # Sample CSV schemas for each sheet
│   ├── Users.csv
│   ├── Routines.csv
│   ├── Logs.csv
│   ├── Insights.csv
│   └── AI_Recommendations.csv
└── routine_bot_improvement_specs.md  # System specification document (Korean)
```

---

## 🚀 Quick Start (Recommended)

The easiest way to set up the bot is to use the interactive setup script:

1. **Clone & Enter the Repository**
   ```bash
   git clone https://github.com/DONGJUN92/telegram_routine_bot.git
   cd telegram_routine_bot
   ```

2. **Create & Activate Virtual Environment**
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

3. **Run the Setup Script**
   ```bash
   python init_setup.py  # Use python3 if on Mac/Linux
   ```
   *This script will automatically install dependencies, help you create a `.env` file, and verify your credentials.*

---

## 🛠️ Manual Setup (Alternative)

### 1. Prerequisites
- **Python 3.10+**
- **Telegram Bot Token** — Create via [@BotFather](https://t.me/BotFather)
- **Google Cloud Service Account** — For Sheets API
- **Ollama** (optional) — For AI features

### 2. Installation
```bash
python -m venv .venv
source .venv/bin/activate  # .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### 3. Configuration
Copy `.env.example` to `.env` and fill in the values:
```bash
cp .env.example .env
```
Ensure `credentials.json` (Google Cloud key) is in the root directory.

### 4. Run to Bot
```bash
python main.py
```

### 5. Set Up Google Sheets

1. Create a Google Cloud project and enable the **Google Sheets API**
2. Create a **Service Account** and download the JSON key file
3. Save it as `credentials.json` in the project root
4. Create a Google Spreadsheet with the following worksheets:
   - `Users`, `Routines`, `Logs`, `Insights`, `AI_Recommendations`, `Weekly_Achievement`
5. Share the spreadsheet with the service account email (found in `credentials.json` → `client_email`)

> 📋 Refer to the CSV files in `db_schema/` for the column structure of each sheet.

### 6. Run the Bot

```bash
python main.py
```

---

## 📱 Commands

### User Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and command guide |
| `/reg [routine_name]` | Register a new routine (private chat only) |
| `/status` | View your routine stats and weekly achievement |
| `/insight [content]` | Share an insight (50+ characters, private chat only) |
| `/del` | Delete a registered routine (private chat only) |
| `/rank` | View the TOP 3 points leaderboard |
| 📸 Photo + Caption | Verify routine completion (private chat only) |

### Admin/Test Commands

| Command | Description |
|---------|-------------|
| `/testmorning` | Trigger morning message immediately |
| `/testevening` | Trigger evening message immediately |
| `/testweekly` | Trigger weekly TOP 3 leaderboard |
| `/testrec` | Trigger AI routine recommendation for yourself |
| `/testinitweekly` | Trigger weekly achievement sheet initialization |

---

## ⏰ Scheduled Messages

| Message | Target | Time (KST) | Frequency |
|---------|--------|-------------|-----------|
| 🌅 Morning Motivation | Group chat | 09:00 | Daily |
| 🌙 Evening Reminder | Group chat | 21:00 | Daily |
| 🏆 Weekly TOP 3 | Group chat | Sunday 12:00 | Weekly |
| 📅 Weekly Init | System | Monday 00:01 | Weekly |
| 💡 AI Recommendation | Individual DM | 15th of month, 12:00 | Monthly |

> ⚠️ If the bot is offline when a scheduled time passes, that message will be **skipped** (not retroactively sent).

---

## 🤖 AI Features (Optional)

AI features require [Ollama](https://ollama.ai) running locally:

```bash
ollama run gemma3:1b
```

- **Keyword Extraction**: Automatically extracts 3 keywords from insight submissions
- **Routine Recommendation**: Analyzes your routines, recent logs, and insights to suggest a new personalized routine

> If Ollama is not running, AI features are gracefully skipped without affecting other bot functionality.

---

## 🔐 Security

All sensitive credentials are managed via environment variables:

- Bot tokens and chat IDs are loaded from `.env` (excluded from Git)
- Google service account keys are stored in `credentials.json` (excluded from Git)
- `.env.example` provides a safe template for new users

---

## ❓ Troubleshooting

### Windows: Scripts are disabled (Execution Policy)
If you get an error when running `.venv\Scripts\activate`:
1. Open PowerShell as **Administrator**.
2. Run: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
3. Restart your terminal and try again.

### Python command not found
- Try using `python3` instead of `python`.
- If on Windows, ensure "Add Python to PATH" was checked during installation.

### Google Sheets Access Denied
- Make sure you shared your Spreadsheet with the `client_email` found inside your `credentials.json` file.
- The service account must have **Editor** permissions.

---

## 📄 License

This project is provided as-is for educational and community purposes.

---

## 🙏 Acknowledgments

Built for the **Sans AI Routine Club** community — a group dedicated to building better habits through accountability and AI-powered insights.
