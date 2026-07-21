import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")  # optional

GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]

# Gmail categories/labels a user can filter on. Maps a friendly name
# (used in slash commands) to the Gmail IMAP label it corresponds to.
GMAIL_FILTER_OPTIONS = {
    "primary": "CATEGORY_PERSONAL",
    "important": "\\Important",
    "updates": "CATEGORY_UPDATES",
    "social": "CATEGORY_SOCIAL",
    "promotions": "CATEGORY_PROMOTIONS",
    "forums": "CATEGORY_FORUMS",
    "starred": "\\Starred",
}

STORAGE_FILE = "storage.json"
IMAP_HOST = "imap.gmail.com"
IMAP_IDLE_TIMEOUT_SECONDS = 240  # well under Gmail's ~29 min IDLE cutoff
IMAP_RECONNECT_DELAY_SECONDS = 15
