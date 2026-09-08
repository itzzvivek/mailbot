import hashlib
import secrets
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitive import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import bcrypt
from app.config import settings

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
