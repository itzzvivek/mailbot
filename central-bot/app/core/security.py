import hashlib
import secrets
import base64
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import bcrypt
from app.config import settings
from datetime import datetime, timedelta


def derive_encryption_key(passcode: str, salt: str) -> bytes:
    """Derive encryption key from passcode and salt"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt.encode(),
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(passcode.encode()))
    return key

def encrypt_token(salt: str, passcode: str) -> tuple:
    """Encrypt OAuth token with user's passcode"""
    # Generate random salt
    salt = secrets.token_hex(32)

    # Derive key from passcode + salt
    key = derive_encryption_key(passcode, salt)
    fernet = Fernet(key)

    #Encrypt token
    encrypted = fernet.encrypt(passcode.encode())
    return encrypted.decode(), salt

def decrypt_token(encrypted: str, passcode: str, salt: str) -> str:
    """Decrypt OAuth token using passcode and salt"""
    try:
        key = derive_encryption_key(passcode, salt)
        fernet = Fernet(key)
        decrypted = fernet.decrypt(encrypted.encode())
        return decrypted.decode()
    except Exception as e:
        raise ValueError("Invalid passcode or corrupted token")

def hash_passcode(passcode: str) -> tuple:
    """Hash passcode and storage"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(passcode.encode(), salt)
    return hashed.decode(), salt.decode()

def verify_passcode(passcode: str, hashed:str) -> bool:
    """Verify passcode against stored hash"""
    return  bcrypt.checkpw(passcode.encode(), hashed.encode())

def generate_api_key() -> str:
    """Generate secure API key for users"""
    return secrets.token_urlsafe(settings.API_KEY_LENGTH)

def hash_api_key(api_key: str) -> str:
    """Hash API key for storage (optional)"""
    return hashlib.sha256(api_key.encode()).hexdigest()

# For Redis cache (temporary decrypted tokens)
class TokenCache:
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.memory_cache = {} # fallback if on Redis

    def store_token(self, discord_id: str, token: str, ttl: int = 3600):
        """Store decrypted token with TTL"""
        if self.redis:
            self.redis.setex(f"token:{discord_id}", ttl, token)
        else:
            self.memory_cache[f"token:{discord_id}"] = {
                "token": token,
                'expires_at': datetime.utcnow() + timedelta(seconds=ttl),
            }

    def get_token(self, discord_id: str) -> Optional[str]:
        """Get decrypted token if still valid"""
        if self.redis:
            token = self.redis.get(f"token:{discord_id}")
            return token.decode() if token else None
        else:
            cache_entry = self.memory_cache.get(f"token:{discord_id}")
            if cache_entry and cache_entry["expires_at"] > datetime.utcnow():
                return cache_entry["token"]
            return None

    def clear_token(self, discord_id: str):
        """Clear decrypted token"""
        if self.redis:
            self.redis.delete(f"token:{discord_id}")
        else:
            self.memory_cache.clear()

token_cache = TokenCache()