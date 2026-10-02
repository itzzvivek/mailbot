import os
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv

load_dotenv()

_key = os.getenv("ENCRYPTION_KEY")
if not _key:
    raise ValueError("ENCRYPTION_KEY is not set in .env")

try:
    _fernet = Fernet(_key.encode())
except Exception as e:
    raise ValueError(f"ENCRYPTION_KEY is invalid: {e}")

def encrypt(plaintext: str) ->str:
    """Encrypt a string. Return base64-encoded ciphertext."""
    if plaintext is None:
        return None

    return _fernet.encrypt(plaintext.encode()).decode()

def decrypt(ciphertext: str) -> str:
    """Decrypt a previously-encrypted string."""
    if ciphertext is None:
        return None

    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        raise ValueError(
            "Decryption failed - ENCRYPTION_KEY may have changed"
            "or the ciphertext is corrupted"
        )