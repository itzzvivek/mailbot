import pytest
import base64
from app.core.security import (
    derive_encryption_key,
    encrypt_token,
    decrypt_token,
    hash_passcode,
    verify_passcode,
    generate_api_key,
    hash_api_key,
)


class TestEncryption:
    """Test token encryption/decryption"""

    def test_encrypt_decrypt_roundtrip(self):
        """Encrypted token should decrypt correctly with same passcode"""
        token = "my_secret_oauth_token"
        passcode = "user_passcode_123"

        encrypted, salt = encrypt_token(token, passcode)
        decrypted = decrypt_token(encrypted, passcode, salt)

        assert decrypted == token

    def test_encrypt_produces_different_output(self):
        """Same token should encrypt differently each time (random salt)"""
        token = "my_secret_oauth_token"
        passcode = "user_passcode_123"

        encrypted1, salt1 = encrypt_token(token, passcode)
        encrypted2, salt2 = encrypt_token(token, passcode)

        assert encrypted1 != encrypted2
        assert salt1 != salt2

    def test_decrypt_with_wrong_passcode_fails(self):
        """Wrong passcode should fail to decrypt"""
        token = "my_secret_oauth_token"
        passcode = "correct_passcode"
        wrong_passcode = "wrong_passcode"

        encrypted, salt = encrypt_token(token, passcode)

        with pytest.raises(ValueError, match="Invalid passcode"):
            decrypt_token(encrypted, wrong_passcode, salt)

    def test_decrypt_with_wrong_salt_fails(self):
        """Wrong salt should fail to decrypt"""
        token = "my_secret_oauth_token"
        passcode = "user_passcode"

        encrypted, salt = encrypt_token(token, passcode)
        wrong_salt = "wrong_salt_value"

        with pytest.raises(ValueError):
            decrypt_token(encrypted, passcode, wrong_salt)

    def test_derive_key_is_deterministic(self):
        """Same passcode + salt should produce same key"""
        passcode = "test_passcode"
        salt = "test_salt"

        key1 = derive_encryption_key(passcode, salt)
        key2 = derive_encryption_key(passcode, salt)

        assert key1 == key2

    def test_derive_key_differs_with_salt(self):
        """Different salts should produce different keys"""
        passcode = "test_passcode"

        key1 = derive_encryption_key(passcode, "salt1")
        key2 = derive_encryption_key(passcode, "salt2")

        assert key1 != key2


class TestPasscodeHashing:
    """Test passcode hashing and verification"""

    def test_hash_and_verify_passcode(self):
        """Correct passcode should verify"""
        passcode = "my_secure_passcode"

        hashed, salt = hash_passcode(passcode)
        assert verify_passcode(passcode, hashed) is True

    def test_wrong_passcode_fails_verification(self):
        """Wrong passcode should fail verification"""
        passcode = "my_secure_passcode"
        wrong_passcode = "wrong_passcode"

        hashed, salt = hash_passcode(passcode)
        assert verify_passcode(wrong_passcode, hashed) is False

    def test_hash_produces_different_output(self):
        """Same passcode should hash differently (bcrypt salt)"""
        passcode = "my_secure_passcode"

        hashed1, salt1 = hash_passcode(passcode)
        hashed2, salt2 = hash_passcode(passcode)

        assert hashed1 != hashed2


class TestAPIKeys:
    """Test API key generation and hashing"""

    def test_generate_api_key_is_unique(self):
        """Generated API keys should be unique"""
        keys = [generate_api_key() for _ in range(100)]
        assert len(set(keys)) == 100

    def test_generate_api_key_length(self):
        """API keys should be sufficiently long"""
        key = generate_api_key()
        assert len(key) >= 32

    def test_hash_api_key_is_deterministic(self):
        """Same API key should produce same hash"""
        api_key = "test_api_key_123"

        hash1 = hash_api_key(api_key)
        hash2 = hash_api_key(api_key)

        assert hash1 == hash2

    def test_different_api_keys_different_hashes(self):
        """Different API keys should produce different hashes"""
        hash1 = hash_api_key("key1")
        hash2 = hash_api_key("key2")

        assert hash1 != hash2