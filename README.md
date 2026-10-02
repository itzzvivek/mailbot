# 📧 Mailbot — Gmail → Discord Notifications

> Get your Gmail delivered straight to Discord. Filter by category, pause anytime, and never miss what matters.

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://www.python.org/)
[![Discord.py](https://img.shields.io/badge/discord.py-2.3.2-5865F2)](https://discordpy.readthedocs.io/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-336791)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## ✨ Features

- 📬 **Real-time Gmail → Discord notifications** — emails appear in your channel within 60 seconds
- 🏷️ **Category filtering** — Primary, Important, Social, Updates, Promotions, Forums
- 🔐 **Secure authentication** — Gmail App Passwords, no OAuth verification needed
- 🔒 **Encrypted storage** — App passwords encrypted at rest with Fernet
- ⏯️ **Pause / Resume** — control when you receive notifications
- 👥 **Multi-user** — one bot serves many users across many servers
- 🚫 **UID watermark** — only new emails trigger notifications (no floods of old mail)
- 🐳 **Docker-first** — deploy in one command
- 💸 **100% free to run** — fits on Oracle Cloud Free Tier
- 🔗 **Clickable embeds** — open the email directly in Gmail from Discord

---

## 🖼️ Preview

```
┌─────────────────────────────────────────────────────────┐
│ 📧 Meeting tomorrow at 10 AM          ← clickable link  │
│                                                         │
│ boss@company.com                        ← author        │
│ Hi team, we have a meeting...           ← preview       │
│                                                         │
│ 🏷️ Category    🕒 Time         🔗 Open                │
│ Primary,       3:45 PM         Open in Gmail          │
│ Important                                               │
└─────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### For Users (Adding the Bot to Your Server)

1. **[Invite the bot](https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&scope=bot+applications.commands&permissions=2048)** to your Discord server
2. Run `/connect` — the bot will guide you through setup
3. Follow the steps to generate a **Gmail App Password**
4. Run `/setpassword <your-email> <app-password>`
5. Run `/setchannel` in the channel where you want notifications
6. Run `/notify primary` (or any category) to choose what to receive
7. Done! 🎉

### For Developers (Self-Hosting)

```bash
# 1. Clone the repo
git clone https://github.com/itzzvivek/mailbot.git
cd mailbot

# 2. Configure environment
cp .env.example .env
nano .env

# 3. Build and start
docker compose up -d --build

# 4. Check logs
docker compose logs -f bot
```

---

## 📋 Commands

| Command | Description |
|---------|-------------|
| `/connect` | Start the Gmail connection flow |
| `/setpassword` | Save your Gmail address + App Password |
| `/setchannel` | Set the channel for notifications |
| `/notify` | Choose which email categories notify you |
| `/unnotify` | Remove a category from notifications |
| `/mystatus` | Check your current setup |
| `/pause` | Stop notifications temporarily |
| `/resume` | Resume notifications |
| `/disconnect` | Remove your Gmail + all data |
| `/help` | Show all commands |

### Filter Categories

| Category | What it matches |
|----------|-----------------|
| `primary` | Primary inbox |
| `important` | Gmail-flagged important |
| `social` | Social notifications |
| `updates` | Receipts, confirmations, updates |
| `promotions` | Marketing and offers |
| `forums` | Mailing lists and forums |
| `all` | Everything (overrides other filters) |

**Mutual exclusion:** Selecting `all` clears every other filter. Selecting a specific category removes `all` if present.

---

## 🔐 Security Model

Mailbot is designed with a **"no-verification OAuth-free"** approach — using Gmail App Passwords instead of Google OAuth.

| Concern | How Mailbot Handles It |
|---------|-----------------------|
| **No Google verification** | Uses Gmail App Passwords (no OAuth consent screen) |
| **No domain or HTTPS needed** | IMAP is outbound-only — no public endpoint |
| **Encrypted at rest** | App passwords encrypted with Fernet + server-side key |
| **Read-only by design** | Only uses IMAP `SEARCH` and `FETCH` — never sends/deletes |
| **User-controllable** | Users can revoke access anytime at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) |
| **No emails stored** | Only metadata (subject, sender, preview) is sent to Discord |

### What We Store

| Data | Purpose | Encrypted? |
|------|---------|-----------|
| Discord ID | Identify the user | ❌ |
| Gmail address | Connect to IMAP | ❌ |
| App Password | Authenticate to Gmail | ✅ Fernet |
| Channel ID | Where to send notifications | ❌ |
| Filters | What emails to notify about | ❌ |
| Last UID | Avoid re-processing old emails | ❌ |

### What We Never Store

- ❌ Email bodies
- ❌ Attachments
- ❌ Google OAuth tokens
- ❌ Your main Google password

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Oracle Cloud VM                      │
│                                                         │
│   ┌──────────────────┐      ┌──────────────────┐        │
│   │  Bot Container   │      │  PostgreSQL      │        │
│   │                  │      │                  │        │
│   │  • discord.py    │─────▶│  • users         │        │
│   │  • IMAP polling  │      │  • notification  │        │
│   │  • 60s loop      │      │    _logs         │        │
│   └────────┬─────────┘      └──────────────────┘        │
│            │                                            │
└────────────┼────────────────────────────────────────────┘
             │
             │ IMAP over TLS (outbound only)
             ▼
   ┌──────────────────┐         ┌──────────────────┐
   │  imap.gmail.com  │         │  Discord API     │
   │  :993            │         │  (webhooks/bot)  │
   └──────────────────┘         └──────────────────┘
```

### Data Flow

1. **Every 60 seconds**, the bot queries PostgreSQL for active users
2. For each user, it connects to Gmail via **IMAP over TLS**
3. It fetches only messages with **UID > last_uid** (incremental)
4. It parses subject, sender, preview, labels, date
5. It sends an **embed** to the user's Discord channel
6. It updates `last_uid` in the database

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11 |
| Discord | `discord.py` 2.3.2 |
| Database | PostgreSQL 15 |
| DB Driver | `asyncpg` |
| Email | `imaplib` (built-in) |
| Encryption | `cryptography` (Fernet) |
| Containerization | Docker + Docker Compose |
| Hosting | Oracle Cloud Free Tier (ARM Ampere) |

---

## 📦 Self-Hosting Guide

### Prerequisites

- Docker + Docker Compose installed
- A Discord bot token ([create one here](https://discord.com/developers/applications))
- A PostgreSQL database (Docker Compose provides one)
- An `ENCRYPTION_KEY` (see below)

### 1. Generate an Encryption Key

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Back this key up.** If you lose it, all stored app passwords become unrecoverable.

### 2. Configure `.env`

```env
# Discord
DISCORD_TOKEN=your_discord_bot_token

# PostgreSQL
POSTGRES_USER=mailbot_user
POSTGRES_PASSWORD=choose_a_strong_password
POSTGRES_DB=mailbot
DATABASE_URL=postgresql://mailbot_user:choose_a_strong_password@postgres:5432/mailbot

# Encryption
ENCRYPTION_KEY=your_fernet_key_here
```

### 3. Start the Stack

```bash
docker compose up -d --build
docker compose logs -f bot
```

You should see:

```
✅ Database initialized
✅ Bot ready: mailbot#XXXX
🔍 Checking 0 active users...
```

### 4. Invite the Bot

Use the Discord Developer Portal → OAuth2 URL Generator:

- Scopes: `bot`, `applications.commands`
- Permissions: `Send Messages`, `Embed Links`

### 5. Test

- Run `/connect` in your Discord server
- Follow the on-screen instructions
- Send a test email and wait ~60 seconds

---

## 🔄 Backup & Restore

### Backup

```bash
docker compose exec -T postgres pg_dump \
    -U mailbot_user -d mailbot \
    --clean --if-exists \
    > backups/mailbot_$(date +%Y%m%d).sql
```

### Restore

```bash
cat backups/mailbot_20261003.sql | \
    docker compose exec -T postgres psql -U mailbot_user -d mailbot
```

### Automated Daily Backups

Add to `crontab -e`:

```cron
0 3 * * * /home/ubuntu/mailbot/backup.sh >> /home/ubuntu/mailbot/backups/backup.log 2>&1
```

See `backup.sh` for the full script.

---

---

## 🐛 Troubleshooting

| Problem | Fix |
|---------|-----|
| Bot offline | `docker compose logs bot` |
| No notifications | Check `/mystatus` — is channel set and status Active? |
| Old emails flooding | Ensure `last_uid` is stored (see migration) |
| IMAP login fails | Verify App Password is 16 chars, no spaces |
| Can't decrypt passwords | `ENCRYPTION_KEY` changed — restore from backup or ask users to re-connect |
| Database connection errors | `docker compose ps` — is postgres healthy? |

---

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/amazing`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgements

- [discord.py](https://github.com/Rapptz/discord.py) — Discord bot framework
- [asyncpg](https://github.com/MagicStack/asyncpg) — High-performance PostgreSQL driver
- [cryptography](https://github.com/pyca/cryptography) — Fernet encryption
- [Oracle Cloud Free Tier](https://www.oracle.com/cloud/free/) — Free always-on VM

---

## ⭐ Support

If you find this project useful:

- ⭐ Star the repo
- 🐛 [Report bugs](https://github.com/itzzvivek/mailbot/issues)
- 💡 [Suggest features](https://github.com/itzzvivek/mailbot/issues)
- 🐦 Share it on Discord

---

<p align="center">
  <strong>Built with ❤️ for the Discord community</strong><br>
  <sub>Made by <a href="https://github.com/itzzvivek">@itzzvivek</a></sub>
</p>