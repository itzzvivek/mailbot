# Gmail → Discord bot

Posts new Gmail messages into a Discord channel in real time, filtered by
category (Primary, Updates, Social, Promotions, Forums), importance, or
starred — set per-channel with slash commands.

100% free-tier friendly: no Google Cloud project, no billing account, no
public HTTPS endpoint required. Just Gmail + Discord.

## How it works

The bot opens one persistent IMAP IDLE connection to Gmail. IDLE is a
standard IMAP feature where the server holds the connection open and tells
the client the moment something changes -- no polling, no public webhook.

```
Gmail inbox  --IMAP IDLE-->  imap_listener.py (background thread)
                                        |
                                        v
                          fetch new message + its Gmail labels
                                        |
                                        v
                     check labels against each channel's filters (storage.py)
                                        |
                                        v
                       Discord bot posts an embed (bot.py)
```

## 1. Gmail setup (5 minutes, no Google Cloud needed)

1. Turn on **2-Step Verification** on your Google account, if it isn't already:
   https://myaccount.google.com/security
2. Go to https://myaccount.google.com/apppasswords and create an app password
   (name it anything, e.g. "discord-bot"). Google gives you a 16-character
   password -- copy it, you won't see it again.
3. That's it. No Cloud Console, no OAuth consent screen, no API enabling.

## 2. Discord setup

1. discord.com/developers/applications → New Application → Bot tab → copy the token.
2. Under OAuth2 → URL Generator, select scopes `bot` and `applications.commands`,
   permission `Send Messages`, and use the generated URL to invite the bot to your server.
3. Grab your server (guild) ID for `DISCORD_GUILD_ID` if you want slash
   commands to sync instantly during development (global sync can take up to an hour).

## 3. Install and run

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in .env: DISCORD_BOT_TOKEN, GMAIL_ADDRESS, GMAIL_APP_PASSWORD
python main.py
```

That's the whole setup. No tunnel, no domain, no certificate -- the bot only
makes outbound connections (to Gmail and to Discord), so it works from
literally anywhere with internet access, including behind NAT/a home router.

## 4. Deployment

See `FREE_DEPLOY.md` for running this 24/7 on a free-forever VM. Because
there's no inbound webhook anymore, deployment is much simpler than a
typical bot: any always-on machine works, no port-opening or HTTPS needed.

`storage.json` is written to disk at runtime and holds your per-channel
filters plus the last-seen mail UID -- make sure your host has a persistent
disk, or it'll re-scan from "now" on every restart (harmless, just means
you won't get a backlog of mail that arrived while it was down).

## 5. Using it

In any channel:

- `/gmail-filter-set category:primary` — start posting Primary inbox mail here
- `/gmail-filter-set category:important` — also post anything Gmail marks important
- `/gmail-filter-show` — see this channel's active filters
- `/gmail-filter-remove category:updates` — stop posting Updates mail here

Filters are OR'd together per channel — e.g. Primary + Important means "post
if it's Primary, or if it's Important, or both."

## Notes & limitations

- The bot can only read mail, never send/modify/delete -- IMAP login with an
  app password only grants what your account's IMAP access already allows,
  and this code never issues a STORE/DELETE/SEND command.
- If your connection drops, `imap_listener.py` reconnects automatically
  after a short delay and picks up from the last UID it saw.
- Storage is a flat JSON file, fine for one user / a handful of channels.
  Move to SQLite/Postgres if you scale up to many accounts.
- App passwords require 2-Step Verification to be enabled. If your Google
  Workspace admin has disabled app passwords org-wide, you'd need to fall
  back to OAuth2 XOAUTH2 for IMAP instead -- ask if you need that variant.
