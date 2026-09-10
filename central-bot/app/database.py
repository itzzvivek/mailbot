from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, List
import logging


from app.config import settings
from app.models.user import User, UserFilter, NotificationLog, Base

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@contextmanager
def get_db():
    """Database session context manager"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        db.close()

def init_db():
    """Initialize the database tables"""
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized")

# User operations
def create_user(discord_id: str, api_key: str) -> User:
    """Create a new user"""
    with get_db() as db:
        user = User(
            discord_id = discord_id,
            api_key = api_key,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

def get_user_by_discord_id(discord_id: str) -> Optional[User]:
    """Get a user by discord id"""
    with get_db() as db:
        return db.query(User).filter(User.discord_id == discord_id).first()

def get_user_by_api_key(api_key: str) -> Optional[User]:
    """Get a user by api_key"""
    with get_db() as db:
        return db.query(User).filter(User.api_key == api_key).first()

def update_user_token(discord_id: str, encrypted_token: str, salt: str, passcode_hash: str, passcode_salt: str):
    """Update user's encrypted token"""
    with get_db() as db:
        user = db.query(User).filter(User.discord_id == discord_id).first()
        if user:
            user.encrypted_token = encrypted_token
            user.token_salt = salt
            user.passcode_hash = passcode_hash
            user.passcode_salt = passcode_salt
            user.updated_at = datetime.utcnow()
            db.commit()
            return user
    return None

def update_user_state(discord_id: str, is_activ: bool):
    """Update user's state"""
    with get_db() as db:
        user = db.query(User).flter(User.discord_id == discord_id).first()
        if user:
            user.is_activated = is_activ
            user.paused_at = datetime.utcnow() if not is_activ else user.paused_at
            user.resumed_at = datetime.utcnow() if not is_activ else user.resumed_at
            user.updated_at = datetime.utcnow()
            db.commit()
            return user
    return None

def get_user_filters(discord_id: str, channel_id: str) -> List[UserFilter]:
    """Get filer for a user in specific channel"""
    with get_db() as db:
        return db.query(UserFilter).filter(
            UserFilter.discord_id == discord_id,
            UserFilter.channel_id == channel_id,
        ).all()

def save_user_filter(discord_id: str, channel_id: str, filter_type: str, filter_value: str):
    """Save a filter for a user"""
    with get_db() as db:
        filter_obj = UserFilter(
            discord_id = discord_id,
            channel_id = channel_id,
            filter_type = filter_type,
            filter_value = filter_value,
        )
        db.add(filter_obj)
        db.commit()

def delete_user_filter(discord_id: str, channel_id: str, filter_type: str, filter_value: str):
    """Delete a filter"""
    with get_db() as db:
        db.query(UserFilter).filter(
            UserFilter.discord_id == discord_id,
            UserFilter.channel_id == channel_id,
            UserFilter.filter_type == filter_type,
            UserFilter.filter_value == filter_value
        ).delete()
        db.commit()

def delete_user(discord_id: str):
    """Delete all user data"""
    with get_db() as db:
        # Cascade delete handles filters and logs
        db.query(User).filter(User.discord_id == discord_id).delete()
        db.commit()

def log_notification(discord_id: str, sender: str, subject: str, status: str = "sent"):
    """Log a notification"""
    with get_db() as db:
        log = NotificationLog(
            discord_id = discord_id,
            sender = sender[:255] if sender else None,
            subject = subject[:255] if subject else None,
            status = status,
        )
        db.add(log)
        #update user notification count
        user = db.query(User).filter(User.discord_id == discord_id).first()
        if user:
            user.notification_count += 1
            user.last_notification = datetime.utcnow()
        db.commit()

def get_user_stats(discord_id: str):
    """Get user statistics"""
    with get_db() as db:
        user = db.query(User).filter(User.discord_id == discord_id).first()
        if not user:
            return {}
        filter_count = db.query(UserFilter).filter(UserFilter.discord_id == discord_id).count()
        notification_count = db.query(NotificationLog).filter(NotificationLog.discord_id == discord_id).count()

        return {
            "filter_count":  filter_count,
            "notification_count": notification_count,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "last_notification": user.last_notification,
        }