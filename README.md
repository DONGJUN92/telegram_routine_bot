# 🌱 Sans AI Routine Club — Telegram Bot

> **A gamified habit-tracking Telegram bot with AI-powered routine recommendations**

[한국어 README 보기 (Korean)](./README_KR.md)

Sans AI Routine Club Bot helps community members **build and maintain daily routines** through photo-based verification, a points & ranking system, and personalized AI recommendations — all within a Telegram group chat.

---

## ✨ Key Features

| Feature | Description |
|---------|-------------|
| 📸 **Photo Verification** | Upload a photo with a caption to verify routine completion |
| 🏆 **Points & Ranking** | Earn points for verifications (+10) and insights (+15); Streak bonuses (+20 for 3 days, +50 for 7 days); compete on the leaderboard |
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
| AI Engine | Ollama (local) — `gemma4:e2b` model |
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

To prevent library conflicts, it is highly recommended to use a virtual environment.

**Windows:**
```cmd
python -m venv .venv
.venv\Scripts\activate
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

Install the required Python packages inside the activated virtual environment. 
*(Note: `tzdata` is recommended to ensure `ZoneInfo` works flawlessly across Windows/Linux).*

```bash
pip install python-telegram-bot[job-queue] gspread python-dotenv aiohttp tzdata
```

### 4. Configure Environment Variables

The bot uses `.env` files to securely manage tokens without exposing them in the code.

```bash
# Copy the template to create your actual .env file
cp .env.example .env
```
Ensure `credentials.json` (Google Cloud key) is in the root directory.

Open `.env` in a text editor and fill in your actual values:

```env
# Telegram Bot Settings
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
GROUP_CHAT_ID=your_group_chat_id_here

# Google Sheets Settings
GOOGLE_SHEET_NAME=your_google_sheet_name_here
GOOGLE_CREDENTIALS_FILE=credentials.json
```
*Tip: To get the `GROUP_CHAT_ID`, you can add the bot to your group, send a message, and check the `/getUpdates` API from Telegram, or use helper bots like `@RawDataBot`.*

### 5. Set Up Google Sheets API

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project and enable the **Google Sheets API**.
3. Create a **Service Account** and generate a new JSON key.
4. Download the JSON file, rename it to `credentials.json`, and place it in the project root folder.
5. Create a new Google Spreadsheet and add the following 6 worksheets exactly as named:
   - `Users`, `Routines`, `Logs`, `Insights`, `AI_Recommendations`, `Weekly_Achievement`
6. **Important:** Share this spreadsheet with the `client_email` found inside your `credentials.json` file as an "Editor".

> 📋 Check the `db_schema/` folder for sample CSVs showing how the columns should be labeled in each sheet.

### 6. Run the Bot

Once everything is configured, run the main script:

```bash
python main.py
```
*You will see terminal logs displaying bot registration and routine authentication events in real time. To keep the bot running 24/7 on a server, consider using tools like `screen`, `tmux`, or `systemd`.*

---

## 📱 Commands

### User Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and command guide |
| `/reg [name]` | Register a new routine (private chat only) |
| `/status` | View your routine stats and weekly achievement |
| `/insight [text]` | Share an insight (50+ chars, private chat only) |
| `/del` or `/delete`| Delete a registered routine (private chat only) |
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
ollama run gemma4:e2b
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
