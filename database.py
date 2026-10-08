import asyncpg
import os
from typing import Optional, List
from encryption.crypto import encrypt, decrypt
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in .env")

# Connection pool
pool: Optional[asyncpg.Pool] = None


async def init_db():
    """Initialize database connection pool"""
    global pool
    pool = await asyncpg.create_pool(
        DATABASE_URL, min_size=2, max_size=10, command_timeout=60
    )

    async with pool.acquire() as conn:
        await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    discord_id BIGINT UNIQUE NOT NULL,
                    gmail_address TEXT NOT NULL,
                    app_password TEXT NOT NULL,
                    channel_id BIGINT,
                    filters TEXT[] DEFAULT '{}',
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS notification_logs (
                    id SERIAL PRIMARY KEY,
                    discord_id BIGINT NOT NULL,
                    sender VARCHAR(255),
                    subject VARCHAR(500),
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (discord_id) REFERENCES users(discord_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id);
                CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active);
            """)
    print("Database initialized")


async def close_db():
    """Close database connection pool"""
    global pool
    if pool:
        await pool.close()
        print("Database pool closed")


# ─── User Operations ───

async def save_credentials(discord_id: int, gmail_address: str, app_password: str) -> dict:
    """Create or update user with Gmail Credentials"""
    encrypted_password = encrypt(app_password)

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO users (discord_id, gmail_address, app_password)
            VALUES ($1, $2, $3)
            ON CONFLICT (discord_id)
            DO UPDATE SET
                gmail_address = EXCLUDED.gmail_address,
                app_password = EXCLUDED.app_password,
                updated_at = CURRENT_TIMESTAMP
            RETURNING *
        """, discord_id, gmail_address, encrypted_password)
        return dict(row) if row else {}

async def get_user(discord_id: int) -> Optional[dict]:
    """Get user WITHOUT decrypted password"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, discord_id, gmail_address, channel_id, filters, is_active, created_at, updated_at
            FROM users WHERE discord_id = $1
        """, discord_id)
        return dict(row) if row else None


async def get_active_users() -> List[dict]:
    """Get all active users (for background email check)"""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT discord_id, gmail_address, app_password, channel_id, filters, last_uid
            FROM users
            WHERE is_active = TRUE AND channel_id IS NOT NULL
        """)
        users = []
        for row in rows:
            u = dict(row)
            try:
                u['app_password'] = decrypt(u['app_password'])
                users.append(u)
            except ValueError as e:
                print(f"Skipping user {u['discord_id']}: {e}")
        return users


async def set_channel(discord_id: int, channel_id: int) -> bool:
    """Set notification channel for user"""
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE users
            SET channel_id = $1, updated_at = CURRENT_TIMESTAMP
            WHERE discord_id = $2
        """, channel_id, discord_id)
        return result == "UPDATE 1"


async def add_filter(discord_id: int, filter_name: str) -> List[str]:
    async with pool.acquire() as conn:
        # Case 1: User selected 'all' → wipe all filters, set only 'all'
        if filter_name == "all":
            row = await conn.fetchrow("""
                UPDATE users
                SET filters = ARRAY['all'],
                    updated_at = CURRENT_TIMESTAMP
                WHERE discord_id = $1
                RETURNING filters
            """, discord_id)
            return list(row['filters']) if row else []

        # Case 2: User selected a specific category
        # First, remove 'all' if present
        await conn.execute("""
            UPDATE users
            SET filters = array_remove(filters, 'all'),
                updated_at = CURRENT_TIMESTAMP
            WHERE discord_id = $1 AND 'all' = ANY(filters)
        """, discord_id)

        # Then add the category (if not already present)
        row = await conn.fetchrow("""
            UPDATE users
            SET filters = array_append(filters, $1),
                updated_at = CURRENT_TIMESTAMP
            WHERE discord_id = $2
              AND NOT ($1 = ANY(filters))
            RETURNING filters
        """, filter_name, discord_id)

        # If the row wasn't updated (filter already existed), just fetch current
        if not row:
            row = await conn.fetchrow(
                "SELECT filters FROM users WHERE discord_id = $1",
                discord_id
            )

        return list(row['filters']) if row else []


async def remove_filter(discord_id: int, filter_name: str) -> List[str]:
    """Remove a filter from user's filters array"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE users
            SET filters = array_remove(filters, $1),
                updated_at = CURRENT_TIMESTAMP
            WHERE discord_id = $2
            RETURNING filters
        """, filter_name, discord_id)
        return list(row['filters']) if row else []


async def pause_user(discord_id: int) -> bool:
    """Pause notifications for user"""
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE users
            SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
            WHERE discord_id = $1
        """, discord_id)
        return result == "UPDATE 1"


async def resume_user(discord_id: int) -> bool:
    """Resume notifications for user"""
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE users
            SET is_active = TRUE, updated_at = CURRENT_TIMESTAMP
            WHERE discord_id = $1
        """, discord_id)
        return result == "UPDATE 1"


async def delete_user(discord_id: int) -> bool:
    """Delete user and all their data"""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM users WHERE discord_id = $1",
            discord_id
        )
        return result == "DELETE 1"


# ─── Notification Logging ───

async def log_notification(discord_id: int, sender: str, subject: str):
    """Log a notification for audit"""
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO notification_logs (discord_id, sender, subject)
            VALUES ($1, $2, $3)
        """, discord_id, sender[:255], subject[:500])


async def get_user_stats(discord_id: int) -> dict:
    """Get user statistics"""
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE discord_id = $1",
            discord_id
        )

        if not user:
            return {}

        log_count = await conn.fetchval("""
            SELECT COUNT(*) FROM notification_logs WHERE discord_id = $1
        """, discord_id)

        return {
            "discord_id": user['discord_id'],
            "channel_id": user['channel_id'],
            "filters": list(user['filters']),
            "is_active": user['is_active'],
            "gmail_address": user['gmail_address'],
            "created_at": user['created_at'],
            "notification_count": log_count
        }

async def get_user_with_password(discord_id: int) -> Optional[dict]:
    """Get user WITH decrypted password"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, discord_id, gmail-address, app_password, channel_id, filters, is_active
            FROM users WHERE discord_id = $1
        """, discord_id)
        if not row:
            return None

        user = dict(row)
        user['app_password'] = decrypt(user['app_password'])
        return user

async def get_last_uid(discord_id: int) -> int:
    """Return the highest UID the bot has already seen for this user"""
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT last_uid FROM users WHERE discord_id = $1", discord_id)
        return val or 0

async def update_last_uid(discord_id: int, uid: int) -> None:
    """store the highest UID seen so far"""
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users
            SET last_uid = $1, updated_at = CURRENT_TIMESTAMP
            WHERE discord_id = $2"""
        , uid, discord_id)
