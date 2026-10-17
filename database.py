import asyncpg
import os
from pathlib import Path
from typing import Optional, List
from encryption.crypto import encrypt, decrypt
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in .env")

SQL_FILE = Path(__file__).parent / "mailbot.sql"

pool: Optional[asyncpg.Pool] = None


async def init_db():
    """Initialize DB pool, create tables, and migrate old schemas"""
    global pool
    pool = await asyncpg.create_pool(
        DATABASE_URL, min_size=2, max_size=10, command_timeout=60
    )

    async with pool.acquire() as conn:
        if not SQL_FILE.exists():
            raise FileNotFoundError(f"Schema file missing: {SQL_FILE}")

        schema_sql = SQL_FILE.read_text()
        await conn.execute(schema_sql)

        # await conn.execute("""
        #     ALTER TABLE users ADD COLUMN IF NOT EXISTS last_uid BIGINT DEFAULT 0;
        #     ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone TEXT DEFAULT 'Asia/Kolkata';
        # """)
        #
        # # Drop obsolete columns from users (if they exist)
        # await conn.execute("""
        #     ALTER TABLE users DROP COLUMN IF EXISTS channel_id;
        #     ALTER TABLE users DROP COLUMN IF EXISTS filters;
        # """)

    print("Database initialized")


async def close_db():
    global pool
    if pool:
        await pool.close()
        print("Database pool closed")


# ─── User Operations ───

async def save_credentials(
    discord_id: int,
    gmail_address: str,
    app_password: str,
    timezone: str = "Asia/Kolkata",
) -> dict:
    """Create or update user credentials"""
    encrypted_password = encrypt(app_password)

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO users (discord_id, gmail_address, app_password, timezone)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (discord_id)
            DO UPDATE SET
                gmail_address = EXCLUDED.gmail_address,
                app_password = EXCLUDED.app_password,
                timezone = EXCLUDED.timezone,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, discord_id, gmail_address, is_active,
                      last_uid, timezone, created_at, updated_at
        """, discord_id, gmail_address, encrypted_password, timezone)
        return dict(row) if row else {}


async def get_user(discord_id: int) -> Optional[dict]:
    """Get user WITHOUT password (safe for commands)"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, discord_id, gmail_address, is_active,
                   last_uid, timezone, created_at, updated_at
            FROM users
            WHERE discord_id = $1
        """, discord_id)
        return dict(row) if row else None


async def get_user_with_password(discord_id: int) -> Optional[dict]:
    """Get user WITH decrypted password (use sparingly)"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, discord_id, gmail_address, app_password,
                   is_active, last_uid, timezone
            FROM users
            WHERE discord_id = $1
        """, discord_id)
        if not row:
            return None
        user = dict(row)
        user['app_password'] = decrypt(user['app_password'])
        return user


async def get_active_users() -> List[dict]:
    """All active users (legacy — prefer get_all_active_subscriptions)"""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT discord_id, gmail_address, app_password,
                   last_uid, timezone
            FROM users
            WHERE is_active = TRUE
        """)
        users = []
        for row in rows:
            u = dict(row)
            try:
                u['app_password'] = decrypt(u['app_password'])
                users.append(u)
            except ValueError as e:
                print(f"⚠️ Skipping user {u['discord_id']}: {e}")
        return users


# ─── Channel / per-server operations ───

async def set_channel(discord_id: int, guild_id: int, channel_id: int) -> bool:
    """Add or update a channel subscription for this user in this guild"""
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_channels (discord_id, guild_id, channel_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (discord_id, guild_id)
            DO UPDATE SET
                channel_id = EXCLUDED.channel_id,
                updated_at = CURRENT_TIMESTAMP
        """, discord_id, guild_id, channel_id)
        return True


async def add_filter(discord_id: int, guild_id: int, filter_name: str) -> List[str]:
    """Add a filter for this user in this guild"""
    async with pool.acquire() as conn:
        # Selecting "all" wipes everything
        if filter_name == "all":
            row = await conn.fetchrow("""
                UPDATE user_channels
                SET filters = ARRAY['all'], updated_at = CURRENT_TIMESTAMP
                WHERE discord_id = $1 AND guild_id = $2
                RETURNING filters
            """, discord_id, guild_id)
            return list(row['filters']) if row else []

        # Selecting a specific category removes 'all' first
        await conn.execute("""
            UPDATE user_channels
            SET filters = array_remove(filters, 'all'),
                updated_at = CURRENT_TIMESTAMP
            WHERE discord_id = $1 AND guild_id = $2 AND 'all' = ANY(filters)
        """, discord_id, guild_id)

        row = await conn.fetchrow("""
            UPDATE user_channels
            SET filters = array_append(filters, $1),
                updated_at = CURRENT_TIMESTAMP
            WHERE discord_id = $2 AND guild_id = $3
              AND NOT ($1 = ANY(filters))
            RETURNING filters
        """, filter_name, discord_id, guild_id)

        if not row:
            row = await conn.fetchrow("""
                SELECT filters FROM user_channels
                WHERE discord_id = $1 AND guild_id = $2
            """, discord_id, guild_id)

        return list(row['filters']) if row else []


async def remove_filter(discord_id: int, guild_id: int, filter_name: str) -> List[str]:
    """Remove a filter for this user in this guild"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE user_channels
            SET filters = array_remove(filters, $1),
                updated_at = CURRENT_TIMESTAMP
            WHERE discord_id = $2 AND guild_id = $3
            RETURNING filters
        """, filter_name, discord_id, guild_id)
        return list(row['filters']) if row else []


async def get_user_channels(discord_id: int) -> List[dict]:
    """All channel subscriptions for this user"""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT guild_id, channel_id, filters, is_active
            FROM user_channels
            WHERE discord_id = $1
        """, discord_id)
        return [dict(r) for r in rows]


async def get_channel_for_guild(discord_id: int, guild_id: int) -> Optional[dict]:
    """Channel config for this user in this guild"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT channel_id, filters, is_active
            FROM user_channels
            WHERE discord_id = $1 AND guild_id = $2
        """, discord_id, guild_id)
        return dict(row) if row else None


async def get_all_active_subscriptions() -> List[dict]:
    """All (user, guild, channel) combos for the background loop"""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT uc.discord_id, uc.guild_id, uc.channel_id, uc.filters,
                   u.gmail_address, u.app_password, u.last_uid, u.timezone
            FROM user_channels uc
            JOIN users u ON u.discord_id = uc.discord_id
            WHERE uc.is_active = TRUE
              AND u.is_active = TRUE
        """)
        subs = []
        for row in rows:
            s = dict(row)
            try:
                s['app_password'] = decrypt(s['app_password'])
                subs.append(s)
            except ValueError as e:
                print(f"⚠️ Skipping {s['discord_id']}: {e}")
        return subs


# ─── Pause / Resume / Delete ───

async def pause_user(discord_id: int) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE users SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
            WHERE discord_id = $1
        """, discord_id)
        return result == "UPDATE 1"


async def resume_user(discord_id: int) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE users SET is_active = TRUE, updated_at = CURRENT_TIMESTAMP
            WHERE discord_id = $1
        """, discord_id)
        return result == "UPDATE 1"


async def delete_user(discord_id: int) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM users WHERE discord_id = $1", discord_id
        )
        return result == "DELETE 1"


# ─── Logging ───

async def log_notification(discord_id: int, sender: str, subject: str):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO notification_logs (discord_id, sender, subject)
            VALUES ($1, $2, $3)
        """, discord_id, sender[:255], subject[:500])


async def get_user_stats(discord_id: int) -> dict:
    """Basic stats — no channel info (that's per-server now)"""
    async with pool.acquire() as conn:
        user = await conn.fetchrow("""
            SELECT discord_id, gmail_address, is_active, timezone, created_at
            FROM users WHERE discord_id = $1
        """, discord_id)
        if not user:
            return {}
        log_count = await conn.fetchval(
            "SELECT COUNT(*) FROM notification_logs WHERE discord_id = $1",
            discord_id
        )
        return {
            "discord_id": user['discord_id'],
            "gmail_address": user['gmail_address'],
            "is_active": user['is_active'],
            "timezone": user['timezone'],
            "created_at": user['created_at'],
            "notification_count": log_count,
        }


# ─── UID watermark ───

async def get_last_uid(discord_id: int) -> int:
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT last_uid FROM users WHERE discord_id = $1", discord_id
        )
        return val or 0


async def update_last_uid(discord_id: int, uid: int) -> None:
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE users
            SET last_uid = $1, updated_at = CURRENT_TIMESTAMP
            WHERE discord_id = $2
        """, uid, discord_id)
        print(f"update_last_uid({discord_id}) → {uid} | {result}")