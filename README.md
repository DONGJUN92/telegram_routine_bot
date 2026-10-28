# Sans AI Routine Club - Telegram Bot

> A Telegram community bot for instant routine verification, attendance tracking, weekly reporting, and AI coaching.

[한국어 README 보기](./README_KR.md)

Sans AI Routine Club Bot helps members build habits in a Telegram community. Members verify routines in a 1:1 private chat with either a photo + caption or `/reg [verification text]` without needing pre-registered routines. New members are automatically added to the `Users` sheet upon their first verification.

---

## Key Features

| Feature | Description |
|---------|-------------|
| Instant routine verification | Verify routines in DM with either photo + caption or `/reg [verification text]` without `Routines` sheet lookups. |
| Auto member registration | New members are automatically registered in `Users` and authenticated immediately on their first verification. |
| Status & attendance check (`/status`) | View today's, this week's, and total verification counts, annual attendance rate (toward the 80% target), and recent logs. |
| Attendance monitoring | Successful verification logs are calculated in code as one 0/100 attendance result per member and KST week, with annual summaries in `출석률`. |
| AI image coaching | Routine verification photos are analyzed by local Ollama (`gemma4:e2b`) for a warm group-share coaching comment. |
| Personal scheduled notifications | Registered members receive a morning prompt, private dashboard, evening attendance reminder, weekly TOP 3, AI briefing, and card news via DM. |

---

## Commands

| Command / Input | Scope | Description |
|---------|-------|-------------|
| `/start` | Anywhere | Welcome message and verification guide |
| `/reg [text]` | DM only | Instant text routine verification (auto-registers new members in `Users`) |
| Photo + caption | DM only | Instant photo routine verification with AI coaching comment shared to the group (auto-registers new members in `Users`) |
| `/status` | Anywhere | View verification counts, annual attendance rate, and recent verification logs |

---

## Scheduled Jobs (KST)

| Job | Target | Time | Frequency |
|-----|--------|------|-----------|
| Morning prompt | Main bot, registered member DM | 09:00 | Daily |
| Personal dashboard | Main bot, registered member DM | 18:00 | Daily |
| Evening reminder | Main bot, registered member DM | 21:00 | Daily |
| Weekly TOP 3 | Main bot, registered member DM | Sunday 12:00 | Weekly |
| Weekly insight AI briefing | Main bot, registered member DM | Sunday 12:05 | Weekly |
| Weekly card news | Main bot, registered member DM | Sunday 12:10 | Weekly |
| Weekly attendance settlement | Google Sheets (`출석률`) | Monday 00:06 | Weekly |
| Monthly group sync & owner briefing | `Users` sheet sync + Owner DM (`OWNER_USER_ID=1415330667`) | 1st day 00:15 | Monthly |
