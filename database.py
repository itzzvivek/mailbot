# database.py
import asyncpg
import os
from typing import Optional, List, Dict, Any
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")

# Connection pool
pool: Optional[asyncpg.Pool] = None


async def init_db():
    """Initialize database connection pool"""
    global pool
    pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=2,
        max_size=10,
        command_timeout=60
    )
    print("✅ Database pool created")


async def close_db():
    """Close database connection pool"""
    global pool
    if pool:
        await pool.close()
        print("✅ Database pool closed")


# ─── User Operations ───

async def create_user(discord_id: int, refresh_token: str) -> dict:
    """Create or update a user"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO users (discord_id, refresh_token)
            VALUES ($1, $2)
            ON CONFLICT (discord_id)
            DO UPDATE SET
                refresh_token = EXCLUDED.refresh_token,
                updated_at = CURRENT_TIMESTAMP
            RETURNING *
        """, discord_id, refresh_token)
        return dict(row)


async def get_user(discord_id: int) -> Optional[dict]:
    """Get user by Discord ID"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE discord_id = $1",
            discord_id
        )
        return dict(row) if row else None


async def get_active_users() -> List[dict]:
    """Get all active users (for background email check)"""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT discord_id, refresh_token, channel_id, filters
            FROM users
            WHERE is_active = TRUE AND channel_id IS NOT NULL
        """)
        return [dict(row) for row in rows]


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
    """Add a filter to user's filters array"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE users
            SET filters = array_append(filters, $1),
                updated_at = CURRENT_TIMESTAMP
            WHERE discord_id = $2
              AND NOT ($1 = ANY(filters))
            RETURNING filters
        """, filter_name, discord_id)

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
            "created_at": user['created_at'],
            "notification_count": log_count
        }