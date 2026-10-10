import os
import re
import logging
import asyncio
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from gmail_reader import fetch_new_emails



import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

from database import (
    init_db, close_db, get_user, get_active_users, save_credentials,
    set_channel, add_filter, remove_filter, pause_user, resume_user,
    delete_user, log_notification, get_user_stats, update_last_uid
)

DEFAULT_TZ = "Asia/kolkata"
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
    """Strip spaces — Google shows them as 'abcd efgh ijkl mnop'"""
    return re.sub(r"\s+", "", raw)

def format_email_time(date_str: str, user_tz: str = DEFAULT_TZ) -> str:
    """Convert email date header into gmail-style short time"""
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
        delta_days = (now_local.date() - dt_local.date()).days

        if delta_days == 0:
            return dt_local.strftime("%I:%M %p").lstrip("0")
        elif delta_days < 7:
            return dt_local.strftime("%a %I:%M %p").lstrip("0")
        else:
            return dt_local.strftime("%b %d")
    except Exception:
        return date_str or "Unknown"

def build_gmail_url(message_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#inbox/{message_id}"

def format_category(labels: list) -> str:
    if not labels:
        return "Inbox"
    return "🏷️ " + ", ".join(labels[:3])


# ─── Commands ───

@bot.tree.command(name="connect", description="Connect your Gmail account")
async def connect(interaction: discord.Interaction):
    user = await get_user(interaction.user.id)

    if user:
        await interaction.response.send_message(
            "You're already connected.\n"
            "Use `/setchannel` to pick a channel, or `/reconnect` to change Gmail.",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title="Connect Your Gmail",
        description="Follow these steps to connect your Gmail account.",
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="1️⃣ Enable 2-Step Verification",
        value="https://myaccount.google.com/security",
        inline=False,
    )
    embed.add_field(
        name="2️⃣ Generate an App Password",
        value="https://myaccount.google.com/apppasswords\n"
              "Name it anything (e.g., `Discord Mailbot`).",
        inline=False,
    )
    embed.add_field(
        name="3️⃣ Save It Here",
        value="Use `/setup-cred <your-email> <app-password> <timezone>`",
        inline=False,
    )
    embed.add_field(
        name="Security",
        value="Your password is stored **only on this bot's server** and is used "
              "exclusively for reading your Gmail. You can revoke it anytime at "
              "https://myaccount.google.com/apppasswords",
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="setup-cred", description="Save your Gmail + App Password + timezone")
@app_commands.describe(
    email="Your Gmail address (e.g., you@gmail.com)",
    app_password="Your 16-character App Password",
    timezone="Your timezone - so email times match your Gmail"
)
@app_commands.choices(timezone=[
    app_commands.Choice(name="IST — India (UTC+5:30)", value="Asia/Kolkata"),
    app_commands.Choice(name="GST — Dubai (UTC+4)", value="Asia/Dubai"),
    app_commands.Choice(name="GMT — London (UTC+0)", value="Europe/London"),
    app_commands.Choice(name="CET — Berlin/Paris (UTC+1)", value="Europe/Berlin"),
    app_commands.Choice(name="EST — New York (UTC-5)", value="America/New_York"),
    app_commands.Choice(name="CST — Chicago (UTC-6)", value="America/Chicago"),
    app_commands.Choice(name="MST — Denver (UTC-7)", value="America/Denver"),
    app_commands.Choice(name="PST — Los Angeles (UTC-8)", value="America/Los_Angeles"),
    app_commands.Choice(name="SGT — Singapore (UTC+8)", value="Asia/Singapore"),
    app_commands.Choice(name="JST — Tokyo (UTC+9)", value="Asia/Tokyo"),
    app_commands.Choice(name="AEST — Sydney (UTC+10)", value="Australia/Sydney"),
    app_commands.Choice(name="UTC", value="UTC"),
])
async def setpassword(
    interaction: discord.Interaction, email: str, app_password: str, timezone: app_commands.Choice[str] = None
):
    if "@" not in email:
        await interaction.response.send_message(
            "That doesn't look like a valid email address.", ephemeral=True
        )
        return

    cleaned = clean_app_password(app_password)
    if len(cleaned) != 16:
        await interaction.response.send_message(
            f"App Password should be 16 characters (got {len(cleaned)}). "
            "Remove spaces and try again.",
            ephemeral=True,
        )
        return

    tz = timezone.value if timezone else "Asia/Kolkata"

    # Save to DB
    await save_credentials(interaction.user.id, email, cleaned, tz)
    await interaction.response.send_message(
        f"Gmail connected: `{email}`\n"
        f"Timezone: **{tz}**\n"
        f"Next: run `/setchannel` in the channel you want notifications in.",
        ephemeral=True,
    )

    # Delete the DM message so the password isn't visible in history
    try:
        await interaction.delete_original_response()
        await interaction.followup.send(
            "For your security, the message with your password was deleted.",
            ephemeral=True,
        )
    except Exception:
        pass

    log.info(f"Credentials saved for user {interaction.user.id}")


@bot.tree.command(name="setchannel", description="Set notification channel")
async def setchannel(interaction: discord.Interaction):
    user = await get_user(interaction.user.id)
    if not user:
        await interaction.response.send_message(
            "Connect your Gmail first with `/connect`", ephemeral=True
        )
        return

    success = await set_channel(interaction.user.id, interaction.channel_id)
    if success:
        await interaction.response.send_message(
            f"Notifications will go to {interaction.channel.mention}",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            "Something went wrong. Try again.", ephemeral=True
        )


@bot.tree.command(name="notify", description="Choose which emails notify you")
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
    user = await get_user(interaction.user.id)
    if not user:
        await interaction.response.send_message(
            "Connect your Gmail first with `/connect`", ephemeral=True
        )
        return

    filters = await add_filter(interaction.user.id, category.value)

    if category.value == "all":
        note = "You'll receive notifications for **all** emails. (Previous filters cleared.)"
    elif "all" in filters:
        note = "You'll receive notifications for **all** emails."
    else:
        note = f"Added **{category.name}** to your notifications."

    await interaction.response.send_message(
        f"{note}\nActive filters: `{', '.join(filters) if filters else 'None'}`",
        ephemeral=True,
    )


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
    user = await get_user(interaction.user.id)
    if not user:
        await interaction.response.send_message(
            "Connect your Gmail first with `/connect`", ephemeral=True
        )
        return

    filters = await remove_filter(interaction.user.id, category.value)
    await interaction.response.send_message(
        f"Removed **{category.name}**\n"
        f"Active filters: `{', '.join(filters) if filters else 'None'}`",
        ephemeral=True,
    )


@bot.tree.command(name="mystatus", description="Check your current setup")
async def mystatus(interaction: discord.Interaction):
    user = await get_user(interaction.user.id)
    if not user:
        await interaction.response.send_message(
            "Not connected. Use `/connect` to get started.", ephemeral=True
        )
        return

    stats = await get_user_stats(interaction.user.id)

    embed = discord.Embed(title="Your Setup", color=discord.Color.blue())
    embed.add_field(name="Gmail", value=user['gmail_address'], inline=True)
    embed.add_field(
        name="Channel",
        value=f"<#{user['channel_id']}>" if user['channel_id'] else "Not set",
        inline=True,
    )
    embed.add_field(
        name="Notifying",
        value=", ".join(user['filters']) if user['filters'] else "None",
        inline=False,
    )
    embed.add_field(
        name="Status",
        value="Active" if user['is_active'] else "Paused",
        inline=True,
    )
    embed.add_field(
        name="Notifications",
        value=str(stats.get('notification_count', 0)),
        inline=True,
    )

    embed.add_field(
        name="Timezone",
        value=user.get('timezone', DEFAULT_TZ),
        inline=True,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="pause", description="Stop notifications")
async def pause(interaction: discord.Interaction):
    if await pause_user(interaction.user.id):
        await interaction.response.send_message(
            "Notifications paused. Use `/resume` when ready.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "Not connected. Use `/connect` first.", ephemeral=True
        )


@bot.tree.command(name="resume", description="Start notifications again")
async def resume(interaction: discord.Interaction):
    if await resume_user(interaction.user.id):
        await interaction.response.send_message(
            "▶️ Notifications resumed!", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "Not connected. Use `/connect` first.", ephemeral=True
        )


@bot.tree.command(name="disconnect", description="Remove your Gmail and data")
async def disconnect(interaction: discord.Interaction):
    await interaction.response.send_message(
        "⚠️ Are you sure? This deletes all your data.\n"
        "Type `/disconnect-confirm` to confirm.",
        ephemeral=True,
    )


@bot.tree.command(name="disconnect-confirm", description="Confirm data deletion")
async def disconnect_confirm(interaction: discord.Interaction):
    await delete_user(interaction.user.id)
    await interaction.response.send_message(
        "Your data has been deleted. Reconnect anytime with `/connect`.",
        ephemeral=True,
    )


@bot.tree.command(name="help", description="Show all commands")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Available Commands",
        description="Everything you can do with this bot",
        color=discord.Color.green(),
    )
    embed.add_field(
        name="Setup",
        value="`/connect` — Connect your Gmail\n"
              "`/setpassword` — Save Gmail + App Password\n"
              "`/setchannel` — Set notification channel",
        inline=False,
    )
    embed.add_field(
        name="Customize",
        value="`/notify` — Choose which emails\n"
              "`/unnotify` — Remove a notification type\n"
              "`/mystatus` — Check your setup",
        inline=False,
    )
    embed.add_field(
        name="Control",
        value="`/pause` — Stop notifications\n"
              "`/resume` — Start notifications\n"
              "`/disconnect` — Remove your data",
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ─── Background Loop ───
@tasks.loop(seconds=30)
async def check_emails():
    try:
        users = await get_active_users()
        log.info(f"Found {len(users)} active users....")

        for user in users:
            if not user['channel_id']:
                continue

            try:
                emails, new_last_uid = await fetch_new_emails(
                    gmail_address=user['gmail_address'],
                    app_password=user['app_password'],
                    filters=list(user['filters']) if user['filters'] else [],
                    last_uid=user.get('last_uid', 0),
                    max_results=20,
                    mark_read=True,
                )

                #save the watermark
                if new_last_uid > (user.get('last_uid') or 0):
                    await update_last_uid(user['discord_id'], new_last_uid)
                    log.info(
                        f"Watermark: {user.get('last_uid')} > {new_last_uid}",
                        f"for user {user['discord_id']}"
                    )

                if not emails:
                    continue

                channel = bot.get_channel(user['channel_id'])
                if not channel:
                    log.info(f"channel: {user['channel_id']} not found")
                    continue

                for em in emails:
                    category_str=format_category(em.get("labels", []))

                    time_str=format_email_time(em.get("date", ""), user.get("timezone") or DEFAULT_TZ,)
                    gmail_url=build_gmail_url(em["id"])


                    embed = discord.Embed(
                        title=em['subject'][:256] or "(no subject)",
                        description=em['preview'][:300] or "(no preview)",
                        color=discord.Color.blurple(),
                        url=gmail_url,
                    )
                    embed.set_author(name=em['from'])
                    embed.add_field(name="Category", value=category_str, inline=True)
                    embed.add_field(name="Time", value=time_str, inline=True)
                    embed.add_field(
                        name="Open",
                        value=f"[Open in Gmail]({gmail_url})",
                        inline=True,
                    )
                    await channel.send(embed=embed)
                    await log_notification(
                        user['discord_id'], em['from'], em['subject'])
                    await asyncio.sleep(0.5)
            except Exception as e:
                log.error(f"Error for user {user['discord_id']}: {e}")
    except Exception as e:
        log.error(f"Major error in check_emails loop: {e}")

# ─── Run ───

if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_BOT_TOKEN"))