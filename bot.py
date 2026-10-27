import os
import re
import logging
import asyncio
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from aiohttp import web
import math, time

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

from gmail_reader import fetch_new_emails, verify_gmail_credentials
from database import (
    init_db, close_db,
    get_user, add_gmail_account, get_gmail_accounts,
    get_gmail_account_by_email, get_gmail_account_for_guild,
    delete_gmail_account,
    set_channel_for_account, get_channels_for_account,
    get_channel_config,
    add_filter_to_channel, remove_filter_from_channel,
    get_all_active_subscriptions, update_last_uid_for_account,
    pause_user, resume_user, delete_user,
    log_notification, get_user_stats,
)



DEFAULT_TZ = "Asia/Kolkata"
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger("bot")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


# ─── Events ───

@bot.event
async def on_ready():
    await init_db()
    await bot.tree.sync()
    log.info(f"Bot ready: {bot.user}")
    if not check_emails.is_running():
        check_emails.start()


@bot.event
async def on_disconnect():
    await close_db()


# ─── Helpers ───

def clean_app_password(raw: str) -> str:
    return re.sub(r"\s+", "", raw)


def format_email_time(date_str: str, user_tz: str = DEFAULT_TZ) -> str:
    if not date_str:
        return "Unknown"
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        try:
            tz = ZoneInfo(user_tz)
        except Exception:
            tz = ZoneInfo(DEFAULT_TZ)
        dt_local = dt.astimezone(tz)
        now_local = datetime.now(tz)
        delta = (now_local.date() - dt_local.date()).days
        if delta == 0:
            return dt_local.strftime("%I:%M %p").lstrip("0")
        elif 0 < delta < 7:
            return dt_local.strftime("%a %I:%M %p").lstrip("0")
        return dt_local.strftime("%b %d")
    except Exception:
        return date_str or "Unknown"


def build_gmail_url(message_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#inbox/{message_id}"


def format_category(categories, important: bool = False) -> str:
    parts = []
    if important:
        parts.append("Important")
    if isinstance(categories, list):
        for cat in categories[:2]:
            if isinstance(cat, str) and cat.lower() != "important":
                parts.append(cat)
    if not parts:
        return "Inbox"
    return ", ".join(parts)


# ─── /connect (add a Gmail account) ───

@bot.tree.command(name="connect", description="Add a Gmail account")
@app_commands.describe(
    email="Your Gmail address",
    app_password="Your 16-character App Password",
    timezone="Your timezone",
)
@app_commands.choices(timezone=[
    app_commands.Choice(name="IST — India", value="Asia/Kolkata"),
    app_commands.Choice(name="GST — Dubai", value="Asia/Dubai"),
    app_commands.Choice(name="GMT — London", value="Europe/London"),
    app_commands.Choice(name="CET — Berlin", value="Europe/Berlin"),
    app_commands.Choice(name="EST — New York", value="America/New_York"),
    app_commands.Choice(name="CST — Chicago", value="America/Chicago"),
    app_commands.Choice(name="MST — Denver", value="America/Denver"),
    app_commands.Choice(name="PST — Los Angeles", value="America/Los_Angeles"),
    app_commands.Choice(name="SGT — Singapore", value="Asia/Singapore"),
    app_commands.Choice(name="JST — Tokyo", value="Asia/Tokyo"),
    app_commands.Choice(name="AEST — Sydney", value="Australia/Sydney"),
    app_commands.Choice(name="UTC", value="UTC"),
])
async def connect(
    interaction: discord.Interaction,
    email: str,
    app_password: str,
    timezone: app_commands.Choice[str] = None,
):
    if "@" not in email:
        await interaction.response.send_message(
            "That doesn't look like a valid email address.", ephemeral=True
        )
        return

    cleaned = clean_app_password(app_password)
    if len(cleaned) != 16:
        await interaction.response.send_message(
            f"App Password should be 16 characters (got {len(cleaned)}).",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    # Verify credentials before saving
    ok, err = verify_gmail_credentials(email, cleaned)
    if not ok:
        await interaction.followup.send(f"{err}", ephemeral=True)
        return

    # Check duplicate for this user
    existing = await get_gmail_account_by_email(interaction.user.id, email)
    if existing:
        await interaction.followup.send(
            f"⚠️ `{email}` is already connected to your account.\n"
            f"Use `/setchannel {email}` to link it to this server, "
            f"or `/disconnect-account {email}` to remove it.",
            ephemeral=True,
        )
        return

    tz = timezone.value if timezone else DEFAULT_TZ
    account = await add_gmail_account(interaction.user.id, email, cleaned, tz)

    await interaction.followup.send(
        f"Gmail added: `{email}`\n"
        f"Timezone: **{tz}**\n"
        f"Next: `/setchannel {email}` in the channel where you want notifications.",
        ephemeral=True,
    )

    # Delete original for password privacy
    try:
        await interaction.delete_original_response()
        await interaction.followup.send(
            f"Password message deleted for security.\n"
            f"`{email}` connected (tz: **{tz}**)",
            ephemeral=True,
        )
    except Exception:
        pass


# ─── /setchannel ───

@bot.tree.command(name="setchannel", description="Link a Gmail account to this channel")
@app_commands.describe(email="(Optional) which Gmail — only needed if you have multiple")
async def setchannel(interaction: discord.Interaction, email: str = None):
    if not interaction.guild_id:
        await interaction.response.send_message(
            "This command only works in a server.", ephemeral=True
        )
        return

    accounts = await get_gmail_accounts(interaction.user.id)

    if not accounts:
        await interaction.response.send_message(
            "No Gmail account connected. Run `/connect` first.",
            ephemeral=True,
        )
        return

    # Determine which account to use
    if email:
        account = next(
            (a for a in accounts if a['gmail_address'].lower() == email.lower()),
            None,
        )
        if not account:
            list_str = "\n".join(f"• `{a['gmail_address']}`" for a in accounts)
            await interaction.response.send_message(
                f"`{email}` isn't connected.\nYour accounts:\n{list_str}",
                ephemeral=True,
            )
            return
    elif len(accounts) == 1:
        # Only one account — auto-pick
        account = accounts[0]
    else:
        # Multiple accounts, no email provided
        list_str = "\n".join(f"• `{a['gmail_address']}`" for a in accounts)
        await interaction.response.send_message(
            f"⚠️ You have multiple Gmail accounts. Specify which one:\n"
            f"`/setchannel <email>`\n\n"
            f"Your accounts:\n{list_str}",
            ephemeral=True,
        )
        return

    # Link it
    await set_channel_for_account(
        account['id'], interaction.guild_id, interaction.channel_id
    )

    await interaction.response.send_message(
        f"`{account['gmail_address']}` will notify {interaction.channel.mention}.",
        ephemeral=True,
    )


# ─── /notify ───

@bot.tree.command(name="notify", description="Choose which emails notify this channel")
@app_commands.choices(category=[
    app_commands.Choice(name="Primary", value="primary"),
    app_commands.Choice(name="Important", value="important"),
    app_commands.Choice(name="Social", value="social"),
    app_commands.Choice(name="Updates", value="updates"),
    app_commands.Choice(name="Promotions", value="promotions"),
    app_commands.Choice(name="Forums", value="forums"),
    app_commands.Choice(name="All", value="all"),
])
async def notify(interaction: discord.Interaction, category: app_commands.Choice[str]):
    if not interaction.guild_id:
        await interaction.response.send_message("Server only.", ephemeral=True)
        return

    account = await get_gmail_account_for_guild(
        interaction.user.id, interaction.guild_id
    )
    if not account:
        await interaction.response.send_message(
            "No Gmail linked to this server.\n"
            "Run `/setchannel <email>` first.",
            ephemeral=True,
        )
        return

    filters = await add_filter_to_channel(
        account['id'], interaction.guild_id, category.value
    )

    if category.value == "all":
        note = "You'll receive **all** emails. (Previous filters cleared.)"
    elif "all" in filters:
        note = "You'll receive **all** emails."
    else:
        note = f"Added **{category.name}** for this channel."

    await interaction.response.send_message(
        f"{note}\nActive filters: `{', '.join(filters) if filters else 'None'}`",
        ephemeral=True,
    )


# ─── /unnotify ───

@bot.tree.command(name="unnotify", description="Remove a notification type")
@app_commands.choices(category=[
    app_commands.Choice(name="Primary", value="primary"),
    app_commands.Choice(name="Important", value="important"),
    app_commands.Choice(name="Social", value="social"),
    app_commands.Choice(name="Updates", value="updates"),
    app_commands.Choice(name="Promotions", value="promotions"),
    app_commands.Choice(name="Forums", value="forums"),
    app_commands.Choice(name="All", value="all"),
])
async def unnotify(interaction: discord.Interaction, category: app_commands.Choice[str]):
    if not interaction.guild_id:
        await interaction.response.send_message("Server only.", ephemeral=True)
        return

    account = await get_gmail_account_for_guild(
        interaction.user.id, interaction.guild_id
    )
    if not account:
        await interaction.response.send_message(
            "No Gmail linked to this server.", ephemeral=True
        )
        return

    filters = await remove_filter_from_channel(
        account['id'], interaction.guild_id, category.value
    )

    await interaction.response.send_message(
        f"Removed **{category.name}**\n"
        f"Active filters: `{', '.join(filters) if filters else 'None'}`",
        ephemeral=True,
    )


# ─── /mystatus ───

@bot.tree.command(name="mystatus", description="See all your Gmail accounts and channels")
async def mystatus(interaction: discord.Interaction):
    accounts = await get_gmail_accounts(interaction.user.id)
    if not accounts:
        await interaction.response.send_message(
            "Not connected. Use `/connect` to add a Gmail account.",
            ephemeral=True,
        )
        return

    stats = await get_user_stats(interaction.user.id)

    embed = discord.Embed(
        title="Your Setup",
        description=f"You have **{len(accounts)}** Gmail account(s) connected.",
        color=discord.Color.blue(),
    )

    for acc in accounts:
        channels = await get_channels_for_account(acc['id'])
        lines = []
        if channels:
            for c in channels:
                filters = ", ".join(c['filters']) if c['filters'] else "no filters"
                lines.append(f"• <#{c['channel_id']}> — {filters}")
        else:
            lines.append("• No channels linked")
        embed.add_field(
            name=f"{acc['gmail_address']} (tz: {acc['timezone']})",
            value="\n".join(lines),
            inline=False,
        )

    embed.add_field(
        name="Total notifications",
        value=str(stats.get('notification_count', 0)),
        inline=True,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ─── /pause, /resume ───

@bot.tree.command(name="pause", description="Pause ALL notifications")
async def pause(interaction: discord.Interaction):
    if await pause_user(interaction.user.id):
        await interaction.response.send_message(
            "All notifications paused.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "No account found. Use `/connect` first.", ephemeral=True
        )


@bot.tree.command(name="resume", description="Resume notifications")
async def resume(interaction: discord.Interaction):
    if await resume_user(interaction.user.id):
        await interaction.response.send_message("▶️ Notifications resumed!", ephemeral=True)
    else:
        await interaction.response.send_message(
            "No account found. Use `/connect` first.", ephemeral=True
        )


# ─── /disconnect-account, /disconnect ───

@bot.tree.command(name="disconnect-account", description="Remove one Gmail account")
@app_commands.describe(email="Which Gmail account to remove")
async def disconnect_account(interaction: discord.Interaction, email: str):
    account = await get_gmail_account_by_email(interaction.user.id, email)
    if not account:
        await interaction.response.send_message(
            f"`{email}` isn't connected to your account.", ephemeral=True
        )
        return

    await delete_gmail_account(account['id'])
    await interaction.response.send_message(
        f"Removed `{email}` and all its channel links.", ephemeral=True
    )


@bot.tree.command(name="disconnect", description="Remove ALL Gmail accounts")
async def disconnect(interaction: discord.Interaction):
    await interaction.response.send_message(
        "This deletes **all** your Gmail accounts and channels.\n"
        "Type `/disconnect-confirm` to confirm.",
        ephemeral=True,
    )


@bot.tree.command(name="disconnect-confirm", description="Confirm full deletion")
async def disconnect_confirm(interaction: discord.Interaction):
    await delete_user(interaction.user.id)
    await interaction.response.send_message(
        "All your data has been deleted. Reconnect anytime with `/connect`.",
        ephemeral=True,
    )


# ─── /help ───

@bot.tree.command(name="help", description="Setup guide + all commands")
async def help_command(interaction: discord.Interaction):
    accounts = await get_gmail_accounts(interaction.user.id)
    has_accounts = len(accounts) > 0

    embed = discord.Embed(
        title="Mailbot Help",
        description=(
            "Get Gmail notifications in Discord. "
            "You can connect multiple Gmail accounts and route each to different servers."
        ),
        color=discord.Color.green(),
    )

    if not has_accounts:
        embed.add_field(
            name="Setup",
            value=(
                "**1.** Enable 2-Step Verification → https://myaccount.google.com/security\n"
                "**2.** Generate an App Password → https://myaccount.google.com/apppasswords\n"
                "**3.** `/connect <email> <app-password> [timezone]`\n"
                "**4.** `/setchannel <email>` in the channel where you want notifications"
            ),
            inline=False,
        )

    embed.add_field(
        name="Accounts",
        value=(
            "`/connect` — Add a Gmail account\n"
            "`/setchannel <email>` — Link an account to this server\n"
            "`/disconnect-account <email>` — Remove one account\n"
            "`/disconnect` — Remove all accounts"
        ),
        inline=False,
    )
    embed.add_field(
        name="Filters",
        value="`/notify` — Add a category\n`/unnotify` — Remove a category",
        inline=False,
    )
    embed.add_field(
        name="Control",
        value="`/pause` · `/resume` · `/mystatus`",
        inline=False,
    )
    embed.set_footer(
        text="Passwords are encrypted. Revoke anytime at myaccount.google.com/apppasswords"
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ─── Background Loop ───

@tasks.loop(seconds=60)
async def check_emails():
    try:
        subs = await get_all_active_subscriptions()
        log.info(f"Checking {len(subs)} active subscriptions...")

        by_account = {}
        for s in subs:
            by_account.setdefault(s['gmail_account_id'], []).append(s)

        for account_id, channel_subs in by_account.items():
            first = channel_subs[0]
            user_tz = first.get('timezone') or DEFAULT_TZ

            try:
                emails, new_last_uid = await fetch_new_emails(
                    gmail_address=first['gmail_address'],
                    app_password=first['app_password'],
                    filters=list(first['filters']) if first['filters'] else [],
                    last_uid=first.get('last_uid', 0) or 0,
                    max_results=20,
                    mark_read=True,
                )

                old_uid = first.get('last_uid') or 0
                if new_last_uid > old_uid:
                    await update_last_uid_for_account(account_id, new_last_uid)
                    log.info(f"Watermark: {old_uid} → {new_last_uid} for account {account_id}")

                if not emails:
                    continue

                for em in emails:
                    await log_notification(
                        first['discord_id'], account_id,
                        em['from'], em['subject'],
                    )

                for sub in channel_subs:
                    channel = bot.get_channel(sub['channel_id'])
                    if not channel:
                        log.warning(f"Channel {sub['channel_id']} not found")
                        continue

                    for em in emails:
                        category_str = format_category(
                            em.get("categories") or [], em.get("important", False)
                        )
                        time_str = format_email_time(em.get("date", ""), user_tz)
                        gmail_url = build_gmail_url(em["id"])

                        embed = discord.Embed(
                            title=em['subject'][:256] or "(no subject)",
                            description=em['preview'][:300] or "(no preview)",
                            color=discord.Color.blurple(),
                            url=gmail_url,
                        )
                        embed.set_author(name=em['from'])
                        embed.add_field(name="🏷️ Category", value=category_str, inline=True)
                        embed.add_field(name="🕒 Time", value=time_str, inline=True)
                        embed.add_field(name="🔗 Open", value=f"[Open in Gmail]({gmail_url})", inline=True)

                        try:
                            await channel.send(embed=embed)
                        except discord.Forbidden:
                            log.warning(f"No permission in {sub['channel_id']}")
                        except discord.HTTPException as e:
                            log.error(f"Discord send failed: {e}")
                        await asyncio.sleep(0.5)

            except Exception as e:
                log.error(f"Error for account {account_id}: {e}")

    except Exception as e:
        log.error(f"Major error in check_emails loop: {e}")

last_event = time.monotonic()

@bot.event
async def on_socket_event_type(event_type):
    global last_event
    last_event = time.monotonic()

async def health(request):
    #check if bot is ready, not closed has latency and has seen recent events
    quiet = time.monotonic() - last_event
    ok = (
            bot.is_ready()
            and bot.is_close()
            and not math.isnan(bot.latency)
            and quiet < 600
    )
    return web.json_response(
        {
            "ok": ok,
            "latency":bot.latency,
            "quiet": quiet,
            "user": str(bot.user) if bot.user else None
        },
        status=200 if ok else 503,
    )

async def start_health_server():
    app = web.Application()
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=80)
    await site.start()
    log.info("Health server listening on http://0.0.0.0:8080/health")


# ─── Run ───

@bot.event
async def setup_hook():
    asyncio.create_task(start_health_server())

if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_BOT_TOKEN"))