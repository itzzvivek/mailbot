"""
End-to-end integration tests for the complete flow
"""
import pytest
from datetime import datetime


class TestCompleteUserJourney:
    """Test the complete user journey from registration to notification"""

    def test_full_flow(self, api_client, db_session):
        """Test: Register → Connect → Resume → Notify → Pause → Revoke"""

        # ===== 1. REGISTER =====
        from app.database import create_user, get_user_by_discord_id
        from app.core.security import generate_api_key

        discord_id = "integration_test_user"
        api_key = generate_api_key()

        user = create_user(discord_id, api_key)
        assert user is not None
        assert user.is_active is False

        # ===== 2. CONNECT (with passcode) =====
        passcode = "user_passcode_123"
        oauth_token = "test_oauth_refresh_token"

        response = api_client.post(
            "/api/connect",
            json={"oauth_token": oauth_token, "passcode": passcode},
            headers={"X-API-Key": api_key}
        )
        assert response.status_code == 200

        # Verify token is encrypted
        user = get_user_by_discord_id(discord_id)
        assert user.encrypted_token is not None
        assert user.encrypted_token != oauth_token
        assert user.is_active is True  # Auto-activated on connect

        # ===== 3. ADD FILTERS =====
        from app.database import save_user_filter, get_user_filters

        save_user_filter(discord_id, "channel_123", "category", "primary")
        save_user_filter(discord_id, "channel_123", "category", "important")

        filters = get_user_filters(discord_id, "channel_123")
        assert len(filters) == 2

        # ===== 4. SEND NOTIFICATION =====
        response = api_client.post(
            "/api/notify",
            json={
                "sender": "boss@company.com",
                "subject": "Meeting tomorrow",
                "preview": "Hi, we have a meeting...",
                "discord_channel": "channel_123"
            },
            headers={"X-API-Key": api_key}
        )
        assert response.status_code == 200

        # Verify notification logged
        from app.database import get_user_stats
        stats = get_user_stats(discord_id)
        assert stats["notification_count"] == 1

        # ===== 5. PAUSE =====
        response = api_client.post(
            "/api/pause",
            headers={"X-API-Key": api_key}
        )
        assert response.status_code == 200

        # Verify paused
        user = get_user_by_discord_id(discord_id)
        assert user.is_active is False

        # ===== 6. NOTIFICATION WHILE PAUSED (should fail) =====
        response = api_client.post(
            "/api/notify",
            json={
                "sender": "spam@test.com",
                "subject": "Spam",
                "discord_channel": "channel_123"
            },
            headers={"X-API-Key": api_key}
        )
        assert response.status_code == 403

        # ===== 7. RESUME =====
        response = api_client.post(
            "/api/resume",
            json={"passcode": passcode},
            headers={"X-API-Key": api_key}
        )
        assert response.status_code == 200

        # ===== 8. REVOKE =====
        from app.database import delete_user

        delete_user(discord_id)

        # Verify user is gone
        assert get_user_by_discord_id(discord_id) is None

        # Verify API key no longer works
        response = api_client.get(
            "/api/status",
            headers={"X-API-Key": api_key}
        )
        assert response.status_code == 401


class TestSecurityScenarios:
    """Test security-related scenarios"""

    def test_stolen_database_is_useless(self, db_session):
        """Even with DB access, tokens can't be decrypted without passcode"""
        from app.database import create_user, update_user_token, get_user_by_discord_id
        from app.core.security import generate_api_key, encrypt_token, hash_passcode

        discord_id = "victim_user"
        api_key = generate_api_key()
        create_user(discord_id, api_key)

        # User's actual passcode (attacker doesn't know this)
        real_passcode = "user_secret_passcode"
        oauth_token = "sensitive_oauth_token"

        encrypted, salt = encrypt_token(oauth_token, real_passcode)
        passcode_hash, passcode_salt = hash_passcode(real_passcode)

        update_user_token(discord_id, encrypted, salt, passcode_hash, passcode_salt)

        # ===== ATTACKER SCENARIO =====
        # Attacker has stolen the database (encrypted_token, salt, passcode_hash)
        user = get_user_by_discord_id(discord_id)
        stolen_encrypted = user.encrypted_token
        stolen_salt = user.token_salt

        # Attacker tries to decrypt with common passcodes
        from app.core.security import decrypt_token

        common_passcodes = ["password", "123456", "admin", "test"]

        for passcode in common_passcodes:
            with pytest.raises(ValueError):
                decrypt_token(stolen_encrypted, passcode, stolen_salt)

        # Attacker can't access the real token
        # ✅ Database theft = useless without user's passcode

    def test_api_key_uniqueness(self, db_session):
        """Each user should have a unique API key"""
        from app.database import create_user
        from app.core.security import generate_api_key

        keys = set()
        for i in range(50):
            api_key = generate_api_key()
            create_user(f"user_{i}", api_key)
            keys.add(api_key)

        assert len(keys) == 50  # All unique

    def test_paused_user_data_cleared_from_cache(self, api_client, test_user_with_token):
        """Pausing should clear cached token"""
        user = test_user_with_token["user"]
        passcode = test_user_with_token["passcode"]

        # Resume to put token in cache
        api_client.post(
            "/api/resume",
            json={"passcode": passcode},
            headers={"X-API-Key": user.api_key}
        )

        # Verify token in cache
        from app.core.security import token_cache
        assert token_cache.get_token(user.discord_id) is not None

        # Pause
        api_client.post(
            "/api/pause",
            headers={"X-API-Key": user.api_key}
        )

        # Verify token cleared from cache
        assert token_cache.get_token(user.discord_id) is None