import logging

import discord
from discord import app_commands
from discord.ext import commands

from config import DISCORD_GUILD_ID, GMAIL_FILTER_OPTIONS
from storage import get_channel_filters, set_channel_filters

log = logging.getLogger("bot")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

FILTER_CHOICES = [
    app_commands.Choice(name=name, value=name) for name in GMAIL_FILTER_OPTIONS
]


@bot.event
async def on_ready():
    if DISCORD_GUILD_ID:
        guild = discord.Object(id=int(DISCORD_GUILD_ID))
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()
    log.info("Logged in as %s", bot.user)


@bot.tree.command(name="gmail-filter-set", description="Choose which mail categories post to this channel")
@app_commands.choices(category=FILTER_CHOICES)
async def gmail_filter_set(interaction: discord.Interaction, category: app_commands.Choice[str]):
    current = get_channel_filters(interaction.channel_id)
    if category.value not in current:
        current.append(category.value)
    set_channel_filters(interaction.channel_id, current)
    await interaction.response.send_message(
        f"✅ This channel now shows **{category.value}** mail. "
        f"Active filters: {', '.join(current)}",
        ephemeral=True,
    )


@bot.tree.command(name="gmail-filter-remove", description="Stop a category from posting to this channel")
@app_commands.choices(category=FILTER_CHOICES)
async def gmail_filter_remove(interaction: discord.Interaction, category: app_commands.Choice[str]):
    current = get_channel_filters(interaction.channel_id)
    if category.value in current:
        current.remove(category.value)
    set_channel_filters(interaction.channel_id, current)
    remaining = ", ".join(current) if current else "(none — this channel is now silent)"
    await interaction.response.send_message(f"🗑️ Removed **{category.value}**. Active filters: {remaining}", ephemeral=True)


@bot.tree.command(name="gmail-filter-show", description="Show which mail categories post to this channel")
async def gmail_filter_show(interaction: discord.Interaction):
    current = get_channel_filters(interaction.channel_id)
    text = ", ".join(current) if current else "none set"
    await interaction.response.send_message(f"Active filters for this channel: **{text}**", ephemeral=True)


async def post_new_mail(channel_id: int, message: dict):
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.NotFound:
            log.warning("Channel %s not found, skipping", channel_id)
            return

    embed = discord.Embed(
        title=message["subject"][:256] or "(no subject)",
        description=message["snippet"][:300],
        url=message["link"],
        color=discord.Color.blurple(),
    )
    embed.set_author(name=message["from"])
    if message.get("date"):
        embed.set_footer(text=message["date"])

    await channel.send(embed=embed)
