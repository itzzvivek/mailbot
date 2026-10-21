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
    global pool
    pool = await asyncpg.create_pool(
        DATABASE_URL, min_size=2, max_size=10, command_timeout=60
    )
    async with pool.acquire() as conn:
        if not SQL_FILE.exists():
            raise FileNotFoundError(f"Schema file missing: {SQL_FILE}")
        await conn.execute(SQL_FILE.read_text())
    print("✅ Database initialized")


async def close_db():
    global pool
    if pool:
        await pool.close()
        print("✅ Database pool closed")


# ─── Users ───

async def ensure_user(discord_id: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (discord_id) VALUES ($1)
            ON CONFLICT (discord_id) DO NOTHING
        """, discord_id)


async def get_user(discord_id: int) -> Optional[dict]:
    """User identity only (no Gmail fields)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, discord_id, is_active, created_at, updated_at
            FROM users WHERE discord_id = $1
        """, discord_id)
        return dict(row) if row else None


# ─── Gmail accounts ───

async def add_gmail_account(
    discord_id: int,
    gmail_address: str,
    app_password: str,
    timezone: str = "Asia/Kolkata",
) -> dict:
    """Add or update a Gmail account. Returns the account row."""
    encrypted = encrypt(app_password)
    await ensure_user(discord_id)

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO gmail_accounts
                (discord_id, gmail_address, app_password, timezone)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (discord_id, gmail_address)
            DO UPDATE SET
                app_password = EXCLUDED.app_password,
                timezone = EXCLUDED.timezone,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, discord_id, gmail_address, timezone, last_uid, is_active
        """, discord_id, gmail_address, encrypted, timezone)
        return dict(row) if row else {}


async def get_gmail_accounts(discord_id: int) -> List[dict]:
    """All Gmail accounts for this user (no passwords)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, gmail_address, timezone, last_uid, is_active
            FROM gmail_accounts
            WHERE discord_id = $1
            ORDER BY id ASC
        """, discord_id)
        return [dict(r) for r in rows]


async def get_gmail_account_by_email(discord_id: int, email: str) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, discord_id, gmail_address, timezone, last_uid, is_active
            FROM gmail_accounts
            WHERE discord_id = $1 AND gmail_address = $2
        """, discord_id, email)
        return dict(row) if row else None


async def get_gmail_account_for_guild(discord_id: int, guild_id: int) -> Optional[dict]:
    """Which Gmail account is linked to this server?"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT ga.id, ga.gmail_address, ga.timezone, ga.last_uid
            FROM gmail_accounts ga
            JOIN user_channels uc ON uc.gmail_account_id = ga.id
            WHERE ga.discord_id = $1 AND uc.guild_id = $2
        """, discord_id, guild_id)
        return dict(row) if row else None


async def delete_gmail_account(account_id: int) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM gmail_accounts WHERE id = $1", account_id
        )
        return result == "DELETE 1"


# ─── Channels (per Gmail account) ───

async def set_channel_for_account(
    account_id: int, guild_id: int, channel_id: int
) -> bool:
    """Link an account to a server's channel."""
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_channels (gmail_account_id, guild_id, channel_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (gmail_account_id, guild_id)
            DO UPDATE SET
                channel_id = EXCLUDED.channel_id,
                updated_at = CURRENT_TIMESTAMP
        """, account_id, guild_id, channel_id)
        return True


async def get_channels_for_account(account_id: int) -> List[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT guild_id, channel_id, filters, is_active
            FROM user_channels
            WHERE gmail_account_id = $1
        """, account_id)
        return [dict(r) for r in rows]


async def add_filter_to_channel(
    account_id: int, guild_id: int, filter_name: str
) -> List[str]:
    async with pool.acquire() as conn:
        if filter_name == "all":
            row = await conn.fetchrow("""
                UPDATE user_channels
                SET filters = ARRAY['all'], updated_at = CURRENT_TIMESTAMP
                WHERE gmail_account_id = $1 AND guild_id = $2
                RETURNING filters
            """, account_id, guild_id)
            return list(row['filters']) if row else []

        await conn.execute("""
            UPDATE user_channels
            SET filters = array_remove(filters, 'all'),
                updated_at = CURRENT_TIMESTAMP
            WHERE gmail_account_id = $1 AND guild_id = $2 AND 'all' = ANY(filters)
        """, account_id, guild_id)

        row = await conn.fetchrow("""
            UPDATE user_channels
            SET filters = array_append(filters, $1),
                updated_at = CURRENT_TIMESTAMP
            WHERE gmail_account_id = $2 AND guild_id = $3
              AND NOT ($1 = ANY(filters))
            RETURNING filters
        """, filter_name, account_id, guild_id)

        if not row:
            row = await conn.fetchrow("""
                SELECT filters FROM user_channels
                WHERE gmail_account_id = $1 AND guild_id = $2
            """, account_id, guild_id)
        return list(row['filters']) if row else []


async def remove_filter_from_channel(
    account_id: int, guild_id: int, filter_name: str
) -> List[str]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE user_channels
            SET filters = array_remove(filters, $1),
                updated_at = CURRENT_TIMESTAMP
            WHERE gmail_account_id = $2 AND guild_id = $3
            RETURNING filters
        """, filter_name, account_id, guild_id)
        return list(row['filters']) if row else []


async def get_channel_config(account_id: int, guild_id: int) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT channel_id, filters, is_active
            FROM user_channels
            WHERE gmail_account_id = $1 AND guild_id = $2
        """, account_id, guild_id)
        return dict(row) if row else None


# ─── Background loop ───

async def get_all_active_subscriptions() -> List[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                ga.id            AS gmail_account_id,
                ga.discord_id    AS discord_id,
                ga.gmail_address AS gmail_address,
                ga.app_password  AS app_password,
                ga.last_uid      AS last_uid,
                ga.timezone      AS timezone,
                uc.guild_id      AS guild_id,
                uc.channel_id    AS channel_id,
                uc.filters       AS filters
            FROM user_channels uc
            JOIN gmail_accounts ga ON ga.id = uc.gmail_account_id
            WHERE uc.is_active = TRUE
              AND ga.is_active = TRUE
        """)
        subs = []
        for row in rows:
            s = dict(row)
            try:
                s['app_password'] = decrypt(s['app_password'])
                subs.append(s)
            except ValueError as e:
                print(f"⚠️ Skipping account {s['gmail_account_id']}: {e}")
        return subs


async def update_last_uid_for_account(account_id: int, uid: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE gmail_accounts
            SET last_uid = $1, updated_at = CURRENT_TIMESTAMP
            WHERE id = $2
        """, uid, account_id)


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
    """Cascade deletes gmail_accounts + user_channels + logs via FK."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM users WHERE discord_id = $1", discord_id
        )
        return result == "DELETE 1"


# ─── Logging ───

async def log_notification(
    discord_id: int, account_id: int, sender: str, subject: str
) -> None:
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO notification_logs
                (discord_id, gmail_account_id, sender, subject)
            VALUES ($1, $2, $3, $4)
        """, discord_id, account_id, sender[:255], subject[:500])


async def get_user_stats(discord_id: int) -> dict:
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT is_active FROM users WHERE discord_id = $1", discord_id
        )
        if not user:
            return {}
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM notification_logs WHERE discord_id = $1",
            discord_id
        )
        accounts = await conn.fetchval(
            "SELECT COUNT(*) FROM gmail_accounts WHERE discord_id = $1",
            discord_id
        )
        return {
            "is_active": user['is_active'],
            "notification_count": count,
            "account_count": accounts,
        }