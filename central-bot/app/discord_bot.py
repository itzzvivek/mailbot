from pydoc import describe

import discord
from discord import app_commands
from discord.ext import commands
import logging
import secrets
import httpx
from datetime import datetime

from app.database import (
    create_user, get_user_by_discord_id, delete_user,
    get_user_filters, save_user_filter, delete_user_filter,
    get_user_stats, update_user_state, get_user_by_api_key
)
from app.core.security import generate_api_key, token_cache
from app.config import settings
from unicodedata import category

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# filter options
FILTER_CHOICES = [
    app_commands.Choice(name="Primary", value="primary"),
    app_commands.Choice(name="Important", value="important"),
    app_commands.Choice(name="Social", value="social"),
    app_commands.Choice(name="Updates", value="updates"),
    app_commands.Choice(name="Promotions", value="promotions"),
    app_commands.Choice(name="Forums", value="forums"),
]

@bot.event
async def on_ready():
    """sync commands when bot starts"""
    try:
        await bot.tree.sync()
        logger.info(f"Synced commands globally")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")

    logger.info(f"Logged in as {bot.user}")

@bot.tree.command(
    name="gmail-register",
    description="Register your Gmail account with this bot"
)

async def register(interaction: discord.Interaction):
    """Register user and generate API key"""
    user_id = str(interaction.user.id)

    # Check if already register
    existing = get_user_by_discord_id(user_id)
    if existing:
        embed = discord.Embed(
            title="Already Registered!",
            description=f"Your API key is below",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="API Key",
            value=f"`{existing.api_key}`",
            inline=False
        )
        embed.add_field(
            name="Next Steps",
            value="Use `/gmail-connect ` to connect your Gmail.",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Generate API key
    api_key = generate_api_key()
    user = create_user(user_id, api_key)

    embed = discord.Embed(
        title="Register Complete!",
        description="Your Gmail -> Discord bot is ready.",
        color=discord.Color.green()
    )
    embed.add_field(
        name="Your API key",
        value=f"`{api_key}`",
        inline=False
    )
    embed.add_field(
        name="Connect Gmail",
        value=(
            "1. Download the local agent:\n"
            " `git clone https://github.com/itzzvivek/mailbot`\n"
            "2. Run: `python agent.py --setup`\n"
            "3. Enter this API key when  prompted\n"
            "4. Follow the OAuth flow\n"
            "5. Set a passcode when prompted"
        ),
        inline=False
    )
    embed.add_field(
        name="Security",
        value=(
            "• Your Gmail credentials **never leave** your machine\n"
            "• Your OAuth token is encrypted with **your passcode**\n"
            "• You can pause anytime with `/gmail-pause`\n"
            "• Revoke access anytime via Google"
        ),
        inline=False
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)
    logger.info(f"User registered: {interaction.user.name}({user_id})")

@bot.tree.command(
    name="gmail-connect",
    description="Connect your Gmail (you need the local agent)",
)
async def connect_gmail(interaction: discord.Interaction):
    """Guild user through Gmail connection"""
    user_id = str(interaction.user.id)
    user = get_user_by_discord_id(user_id)

    if not user:
        await interaction.response.send_message(
            "You need to register first with `/gmail-register`",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="Connect you Gmail",
        description=f"Follow these steps to connect your Gmail.",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="Step 1: Download Agent",
        value="`git clone https://github.com/itzzvivek/mailbot`",
        inline=False
    )
    embed.add_field(
        name="Step 2: Run Setup",
        value="`cd mailbot && python agent.py --setup`",
        inline=False
    )
    embed.add_field(
        name="Step 3: Enter Credentials",
        value=(
            f"* API Key: `{user.api_key}`\n"
            "* Gmail: Your email\n",
            "* Passcode: Create a personal passcode"
        ),
        inline=False
    )
    embed.add_field(
        name="Step 4: OAuth Flow",
        value="A browser will open. Login to Gmail and grant access.",
        inline=False
    )
    embed.add_field(
        name="Your Passcode",
        value=(
            "Your passcode encrypt your Gmail tokem.\n",
            "You'll need it to resume after pausing.\n"
            "**Keep it secure!**"
        ),
        inline=False
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(
    name="gmail-pause",
    description="Pause Gmail monitoring(clears credentials from memory)",
)
async def pause_gmail(interaction: discord.Interaction):
    """Pause Gmail monitoring"""
    user_id = str(interaction.user.id)
    user = get_user_by_discord_id(user_id)

    if not user:
        await interaction.response.send_message(
            "You need to register first with `/gmail-register`",
            ephemeral=True
        )
        return

    # Clear cached token
    token_cache.clear_token(user_id)

    # Update user state
    update_user_state(user_id, False)

    await interaction.response.send_message(
        "Gmail monitoring paused.\n"
        "• Credentials cleared from memory\n"
        "• Use `/gmail-resume <passcode>` to resume\n"
        "• Token will need to be decrypted with your passcode",
        ephemeral=True
    )
    logger.info(f"User paused: {interaction.user.name}({user_id})")

@bot.tree.command(
    name="gmail-resume",
    description="Resume Gmail monitoring(requires passcodes)",
)
async def resume_gmail(interaction: discord.Interaction, passcode:str):
    """Resume Gmail monitoring with passcode"""
    user_id = str(interaction.user.id)
    user = get_user_by_discord_id(user_id)

    if not user:
        await interaction.response.send_message(
            "Your need to register first with `/gmail-register`",
            ephemeral=True
        )
        return

    if not user.encrypted_token:
        await interaction.response.send_message(
            "No Gmail token found. Use `/gmail-connect` first",
            ephemeral=True
        )
        return

    # The actual decryption happens in the local agent
    # For Discord, we just trigger the resume
    # The local agent will handle the decryption

    #update user state
    update_user_state(user_id, True)

    await interaction.response.send_message(
        "Gmail monitoring resumed.\n"
        "• Your local agent will decrypt the token\n"
        "• Token active for 1 hour\n"
        "• Use `/gmail-pause` to pause anytime",
        ephemeral=True
    )
    logger.info(f"User resumed: {interaction.user.name}({user_id})")

@bot.tree.command(
    name="gmail-status",
    description="Check your registration and monitoring status",
)
async def status_gmail(interaction: discord.Interaction):
    """Check user's current status"""
    user_id = str(interaction.user.id)
    user = get_user_by_discord_id(user_id)

    if not user:
        await interaction.response.send_message(
            "You need to register first with `/gmail-register`",
            ephemeral=True
        )
        return

    stats = get_user_stats(user_id)
    filters = get_user_filters(user_id, str(interaction.user.id))

    # Check if token is in cache
    cached_token = token_cache.get_token(user_id)

    embed = discord.Embed(
        title="Your status",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="API Key",
        value=f"`{user.api_key}`",
        inline=False
    )
    embed.add_field(
        name="Status",
        value=f"Activate" if user.activate else "Paused",
        inline=True
    )
    embed.add_field(
        name="Token",
        value=f"In memory" if cached_token else "Encrypted",
        inline=False
    )
    embed.add_field(
        name="Notifications",
        value=str(stats.get('notifications', 0)),
        inline=True
    )
    embed.add_field(
        name="Active Filters",
        value=", ".join([f.filter_value for f in filters]) or "None",
        inline=False
    )
    embed.add_field(
        name="Registered",
        value=user.created_at.strftime("%m/%d/%Y, %H:%M"),
        inline=False
    )
    embed.add_field(
        name="Registered",
        value=user.created_at.strftime("%m/%d/%Y, %H:%M"),
        inline=True
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(
    name="gmail-filter-add",
    description="Add a filter for this channel"
)
@app_commands.choices(category=FILTER_CHOICES)
async def add_filter(
        interaction: discord.Interaction,
        category: app_commands.Choice[str]
):
    """Add a filter for the current channel"""
    user_id = str(interaction.user.id)
    channel_id = str(interaction.channel_id)\

    # Check if registered
    user = get_user_by_discord_id(user_id)
    if not user:
        await interaction.response.send_message(
            "You need to register first with  `/gmail-register`",
            ephemeral=True
        )
        return

    # save filter
    save_user_filter(user_id, channel_id, "category", category.value)

    #Get updated filters
    filters = get_user_filters(user_id, channel_id)
    filter_values = [f.filter_value for f in filters]

    await interaction.response.send_message(
        f"Added filter: **{category.name}**\n"
        f"Active filters: {', '.join(filter_values) or 'None'}",
        ephemeral=True
    )

    logger.info(f"Filter added: {user_id} | {channel_id} | {category.value}")

@bot.tree.command(
    name="gmail-filter-remove",
    description="Remove a filter for this channel"
)

