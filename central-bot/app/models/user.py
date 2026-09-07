from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.ext.declarative import delclarative_base
from datetime import datetime
import uuid


Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    discover_id = Column(String, unique=True, nullable=False)
    api_key = Column(String, unique=True, nullable=False)

    #Encryption Gmail Token

    encrypted_token = Column(Text, nullable=True)
    token_salt = Column(String, nullable=True)
    passcode_hash = Column(String, nullable=True)
    passcode_salt = Column(String, nullable=True)

    # User preferences
    is_active = Column(Boolean, default=False)
    paused_at = Column(DateTime, nullable=True)
    resumed_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.utcnow)

    #Matrics
    notification_count = Column(Integer, default=0)
    last_notification = Column(DateTime, nullable=True)

class UserFilter(Base):
    __tablename__ = 'user_filters'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    discover_id = Column(String, index=True, nullable=False)
    channel_id = Column(String, nullable=False)
    filter_type= Column(String, nullable=False)
    filter_type = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class NotificationLog(Base):
    __tablename__ = 'notification_logs'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    discover_id = Column(String, index=True, nullable=False)
    sender = Column(String)
    subject = Column(String)
    sent_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="sent")

