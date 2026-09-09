from fastapi import APIRouter, HTTPException, Header, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import logging

from app.database import(
    get_user_by_api_key, log_notification, get_user_by_discord_id, get_user_filters,
    update_user_token, update_user_state, create_user, get_user_state, delete_user
)
from app.core.security import(
    encrypt_token, decrypt_token, generate_api_key,
    hash_passcode, verify_passcode, token_cache
)
from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# Pydantic Models
class EmailNotification(BaseModel):
    sender: str = Field(..., description="Email sender")
    subject: str = Field(..., description="Email subject")
    preview: Optional[str] = Field(None, description="Email preview (first 100 chars")
    date: Optional[datetime] = Field(None, description="Email date")
    discord_channel: Optional[str] = Field(None, description="Discord channel ID")
    label: Optional[List[str]] = Field(default=[])

class TokenRequest(BaseModel):
    oauth_token: str
    passcode: str

class PasscodeRequest(BaseModel):
    passcode: str

class FilerRequest(BaseModel):
    filter_type: str
    filter_value: str

@router.post("/api/notify")
async def receive_notification(
    notification: EmailNotification,
    x_api_key: str = Header(...)
):
    """Receive email metadata from local agent"""
    logger.info(f"receive_notification from {notification}")

    # Validate API Key
    user = get_user_by_api_key(x_api_key)
    if not user:
        raise HTTPException(status_code=401, details="Invalid API Key")

    #Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="User is paused. User /gmail-resume to activate."
        )

    #Log notification
    log_notification(
        user.discord_id,
        notification.sender,
        notification.subject,
    )

    # Get user's filters for this channel
    filters = get_user_filters(notification.filter_type, notification.filter_value)

    # Store notification in Redis (for future use)
    # TODO: Store in Redis

    return {
        "status": "received",
        "message": "Notification logged",
        "timestamp": datetime.utcnow().isoformat()
    }

@router.post("/api/connect")
async def connect_gmail(request: TokenRequest, x_api_key: str = Header(...)):
    """Store encrypted Gmail token with passcode"""
    user = get_user_by_api_key(x_api_key)
    if not user:
        raise HTTPException(status_code=401, details="Invalid API Key")

    # Hash passcode
    passcode_hash, passcode_salt = hash_passcode(request.passcode)

    # Encrypt token with passcode
    encrypted_token, salt = encrypt_token(request.oauth_token, request.passcode)

    # store in database
    update_user_token(
        user.discord_id,
        encrypted_token,
        salt,
        passcode_hash,
        passcode_salt
    )

    #Automatically resume if passcode is set
    update_user_state(user.discord_id, True)

    return {
        "status": "connected",
        "message": "Gmail connected and encrypted with your passcode"
    }

@router.post("api/resume")
async def resume_gmail(request: PasscodeRequest, x_api_key: str = Header(...)):
    """Resume Gmail monitoring (decrypting token with passcode)"""
    user = get_user_by_api_key(x_api_key)
    if not user:
        raise HTTPException(status_code=401, details="Invalid API Key")

    if not user.encrypted_token:
        raise HTTPException(status_code=400, details="No Gmail token found. Use /gmail-connect first")

    # Verify passcode
    if not verify_passcode(request.passcode, user.passcode_hash):
        raise HTTPException(status_code=401, details="Incorrect passcode")

    #Decrypt token
    try:
        token = decrypt_token(user.encrypted_token, request.passcode, user.token_salt)
    except ValueError:
        raise HTTPException(status_code=401, details="Incorrect passcode or corrupted token")

    # Store decrypted token on cache (1 hour TTL)
    token_cache.store_token(user.discover_id, ttl=360)

    #update user state
    update_user_state(user.discord_id, True)

    return {
        "status": "resumed",
        "message": "Gmail resumed for 1 hours"
    }

@router.post("/api/pause")
async def pause_gmail(x_api_key: str = Header(...)):
    """Pause Gmail monitoring"""
    user = get_user_by_api_key(x_api_key)
    if not user:
        raise HTTPException(status_code=401, details="Invalid API Key")
    
    # Clear cached token
    token_cache.clear_token(user.discord_id)
    
    # update user state
    update_user_state(user.discord_id, False)
    
    return {
        "status": "paused",
        "message": "Gmail monitoring paused. Credentials cleared from memory."
    }

@router.get("/api/status")
async def get_status(x_api_key: str = Header(...)):
    """Get user's current status"""

    user = get_user_by_api_key(x_api_key)
    if not user:
        raise HTTPException(status_code=401, details="Invalid API Key")

    #clear cached token
    token_cache.clear_token(user.discord_id)

    #update user state
    update_user_state(user.discord_id, False)

    return {
        "status": "paused",
        "message": "Gmail monitoring paused. Credentials cleared from memory."
    }

@router.get("/api/status")
async def get_status(x_api_key: str = Header(...)):
    """Get user's current status"""
    user = get_user_by_api_key(x_api_key)
    if not user:
        raise HTTPException(status_code=401, details="Invalid API Key")
    stats = get_user_state(user.discord_id)

    return {
        "is-active": user.is_active,
        "has_token": bool(user),
        "stats": stats,
        "paused": user.paushed_at,
        "resumed": user.resumed_at,
    }