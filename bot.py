import os
import discord
from discord import app_command
from discord.ext import commands, tasks
from dotenv import load_dotenv
import logging

from database import(
    init_db, close_db, get_user, get_active_users,
    set_channel, add_filter, pause_user, resume_user,
    delete_user, log_notification, get_user_stats
)
from gmail_reader import fetch_new_emails

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

log = logging.getLogger("bot")

intents = discord.Intents.default()
bot = commands.Bot(commands_prefix = "!", intents=intents)

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

@bot.tree.command(name="connect", description="connect your gmail account")
async def connect(interaction: discord.Interaction):
    user = await get_user(interaction)

    if user:
        await interaction.response.send_message(
            "You're already connected\n",
            "Use `/setchannel` to set where notification.",
            ephemeral=True
        )

    oauth_url= f"http://localhost:8080/oauth?discord_id={interaction.user.id}"

    await interaction.response.send_message(
        f"**Connect your Gmail:**\n"
        f"{oauth_url}\n\n"
        f"After connecting, use `setchannel` to set where notification go.`",
        ephemeral=True
    )

@bot.tree.command(name="setchannel", description="set your notification channel")
async def setchannel(interaction: discord.Interaction):
    user = await get_user(interaction.user.id)

    if not user:
        await interaction.response.send_message(
            "Please connect your Gmail first with `/connect`",
            ephemeral=True
        )
        return

    success = await set_channel(interaction.user.id, interaction.channel_id)
    if success:
        await interaction.response.send_message(
            f"Notification will go to {interaction.channel.mention}",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "Something went wrong. Try Again.",
            ephemeral=True
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
            "Please connect your Gmail first with `/connect`",
            ephemeral=True
        )
        return

    filters = await add_filter(interaction.user.id, category.value)

    await interaction.response.send_message(
        f"You'll be notified about **{category.name}** emails\n"
        f"Active filters: `{', '.join(filters) if filters else 'None'}`",
        ephemeral=True
    )


@bot.tree.command(name="unnotify", description="Stop a specific notification type")
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
            "Please connect your Gmail first with `/connect`",
            ephemeral=True
        )
        return

    filters = await remove_filter(interaction.user.id, category.value)

    await interaction.response.send_message(
        f"Removed **{category.name}** from notifications\n"
        f"Active filters: `{', '.join(filters) if filters else 'None'}`",
        ephemeral=True
    )


@bot.tree.command(name="mystatus", description="Check your current setup")
async def mystatus(interaction: discord.Interaction):
    user = await get_user(interaction.user.id)

    if not user:
        await interaction.response.send_message(
            "Not connected. Use `/connect` to get started.",
            ephemeral=True
        )
        return

    stats = await get_user_stats(interaction.user.id)

    embed = discord.Embed(title="Your Setup", color=discord.Color.blue())
    embed.add_field(name="Gmail", value="Connected", inline=True)
    embed.add_field(
        name="Channel",
        value=f"<#{user['channel_id']}>" if user['channel_id'] else "Not set",
        inline=True
    )
    embed.add_field(
        name="Notifying",
        value=", ".join(user['filters']) if user['filters'] else "None",
        inline=False
    )
    embed.add_field(
        name="Status",
        value="Active" if user['is_active'] else "Paused",
        inline=True
    )
    embed.add_field(
        name="Notifications",
        value=str(stats.get('notification_count', 0)),
        inline=True
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="pause", description="Stop notifications")
async def pause(interaction: discord.Interaction):
    success = await pause_user(interaction.user.id)

    if success:
        await interaction.response.send_message(
            "Notifications paused. Use `/resume` when ready.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "Not connected. Use `/connect` first.",
            ephemeral=True
        )


@bot.tree.command(name="resume", description="Start notifications again")
async def resume(interaction: discord.Interaction):
    success = await resume_user(interaction.user.id)

    if success:
        await interaction.response.send_message(
            "▶️ Notifications resumed!",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "Not connected. Use `/connect` first.",
            ephemeral=True
        )


@bot.tree.command(name="disconnect", description="Remove your Gmail and data")
async def disconnect(interaction: discord.Interaction):
    await interaction.response.send_message(
        "⚠️ **Are you sure?** This deletes all your data.\n"
        "Type `/disconnect-confirm` to confirm.",
        ephemeral=True
    )


@bot.tree.command(name="disconnect-confirm", description="Confirm data deletion")
async def disconnect_confirm(interaction: discord.Interaction):
    await delete_user(interaction.user.id)
    await interaction.response.send_message(
        "Your data has been deleted. You can reconnect with `/connect` anytime.",
        ephemeral=True
    )


@bot.tree.command(name="help", description="Show all commands")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Available Commands",
        description="Everything you can do with this bot",
        color=discord.Color.green()
    )
    embed.add_field(
        name="Setup",
        value="`/connect` — Connect your Gmail\n"
              "`/setchannel` — Set notification channel",
        inline=False
    )
    embed.add_field(
        name="Customize",
        value="`/notify` — Choose which emails to get\n"
              "`/unnotify` — Remove a notification type\n"
              "`/mystatus` — Check your setup",
        inline=False
    )
    embed.add_field(
        name="Control",
        value="`/pause` — Stop notifications\n"
              "`/resume` — Start notifications\n"
              "`/disconnect` — Remove your data",
        inline=False
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ─── Background Email Check ───

@tasks.loop(seconds=60)
async def check_emails():
    """Check Gmail for all active users every 60 seconds"""
    users = await get_active_users()
    log.info(f"Checking {len(users)} active users...")

    for user in users:
        if not user['channel_id']:
            continue

        try:
            emails = await fetch_new_emails(
                user['refresh_token'],
                list(user['filters']) if user['filters'] else []
            )

            channel = bot.get_channel(user['channel_id'])
            if not channel:
                log.warning(f"Channel {user['channel_id']} not found")
                continue

            for email in emails:
                embed = discord.Embed(
                    title=email['subject'][:256] or "(no subject)",
                    description=email['preview'][:300],
                    color=discord.Color.blurple()
                )
                embed.set_author(name=email['from'])

                await channel.send(embed=embed)
                await log_notification(
                    user['discord_id'],
                    email['from'],
                    email['subject']
                )
                log.info(f"Sent: {email['subject'][:50]} to {user['discord_id']}")

        except Exception as e:
            log.error(f"Error for user {user['discord_id']}: {e}")


# ─── Run ───

if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))