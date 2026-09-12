import pytest
from datetime import datetime, timedelta
from unittest.mock import patch


class TestHealthEndpoints:
    """Test health check endpoints"""

    def test_root_endpoint(self, api_client):
        """Root endpoint should return healthy"""
        response = api_client.get("/")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "Gmail Discord Bot"


class TestNotifyEndpoint:
    """Test /api/notify endpoint"""

    def test_notify_with_valid_key(self, api_client, test_user):
        """Valid API key should accept notification"""
        # First activate the user
        from app.database import update_user_state
        update_user_state(test_user.discord_id, True)

        response = api_client.post(
            "/api/notify",
            json={
                "sender": "sender@test.com",
                "subject": "Test Subject",
                "preview": "Test preview...",
                "date": "2026-09-04T10:00:00",
                "discord_channel": "123456789",
                "labels": ["INBOX"]
            },
            headers={"X-API-Key": test_user.api_key}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "received"

    def test_notify_without_api_key(self, api_client):
        """Missing API key should return 422 (header required)"""
        response = api_client.post(
            "/api/notify",
            json={
                "sender": "sender@test.com",
                "subject": "Test Subject",
                "discord_channel": "123456789"
            }
        )

        assert response.status_code == 422

    def test_notify_with_invalid_key(self, api_client):
        """Invalid API key should return 401"""
        response = api_client.post(
            "/api/notify",
            json={
                "sender": "sender@test.com",
                "subject": "Test Subject",
                "discord_channel": "123456789"
            },
            headers={"X-API-Key": "invalid_key_123"}
        )

        assert response.status_code == 401
        assert "Invalid API key" in response.json()["detail"]

    def test_notify_when_paused(self, api_client, test_user):
        """Paused user should get 403"""
        # Ensure user is paused (default)
        response = api_client.post(
            "/api/notify",
            json={
                "sender": "sender@test.com",
                "subject": "Test Subject",
                "discord_channel": "123456789"
            },
            headers={"X-API-Key": test_user.api_key}
        )

        assert response.status_code == 403
        assert "paused" in response.json()["detail"].lower()

    def test_notify_logs_notification(self, api_client, test_user):
        """Notification should be logged to database"""
        from app.database import update_user_state, get_user_stats

        update_user_state(test_user.discord_id, True)

        api_client.post(
            "/api/notify",
            json={
                "sender": "sender@test.com",
                "subject": "Test Subject",
                "discord_channel": "123456789"
            },
            headers={"X-API-Key": test_user.api_key}
        )

        stats = get_user_stats(test_user.discord_id)
        assert stats["notification_count"] == 1


class TestConnectEndpoint:
    """Test /api/connect endpoint"""

    def test_connect_stores_encrypted_token(self, api_client, test_user):
        """Should encrypt and store token"""
        response = api_client.post(
            "/api/connect",
            json={
                "oauth_token": "test_refresh_token",
                "passcode": "my_passcode_123"
            },
            headers={"X-API-Key": test_user.api_key}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "connected"

        # Verify token is stored encrypted
        from app.database import get_user_by_discord_id
        user = get_user_by_discord_id(test_user.discord_id)
        assert user.encrypted_token is not None
        assert user.encrypted_token != "test_refresh_token"  # Should be encrypted

    def test_connect_without_api_key(self, api_client):
        """Should require API key"""
        response = api_client.post(
            "/api/connect",
            json={"oauth_token": "token", "passcode": "pass"}
        )
        assert response.status_code == 422

    def test_connect_with_invalid_key(self, api_client):
        """Should reject invalid API key"""
        response = api_client.post(
            "/api/connect",
            json={"oauth_token": "token", "passcode": "pass"},
            headers={"X-API-Key": "invalid_key"}
        )
        assert response.status_code == 401

    def test_connect_activates_user(self, api_client, test_user):
        """Connecting should activate user"""
        api_client.post(
            "/api/connect",
            json={"oauth_token": "token", "passcode": "pass"},
            headers={"X-API-Key": test_user.api_key}
        )

        from app.database import get_user_by_discord_id
        user = get_user_by_discord_id(test_user.discord_id)
        assert user.is_active is True


class TestResumeEndpoint:
    """Test /api/resume endpoint"""

    def test_resume_with_correct_passcode(self, api_client, test_user_with_token):
        """Correct passcode should resume user"""
        user = test_user_with_token["user"]
        passcode = test_user_with_token["passcode"]

        response = api_client.post(
            "/api/resume",
            json={"passcode": passcode},
            headers={"X-API-Key": user.api_key}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "resumed"

    def test_resume_with_wrong_passcode(self, api_client, test_user_with_token):
        """Wrong passcode should fail"""
        user = test_user_with_token["user"]

        response = api_client.post(
            "/api/resume",
            json={"passcode": "wrong_passcode"},
            headers={"X-API-Key": user.api_key}
        )

        assert response.status_code == 401
        assert "Incorrect passcode" in response.json()["detail"]

    def test_resume_without_token(self, api_client, test_user):
        """Resume without token should fail"""
        response = api_client.post(
            "/api/resume",
            json={"passcode": "passcode"},
            headers={"X-API-Key": test_user.api_key}
        )

        assert response.status_code == 400
        assert "No Gmail token" in response.json()["detail"]


class TestPauseEndpoint:
    """Test /api/pause endpoint"""

    def test_pause_user(self, api_client, test_user_with_token):
        """Should pause active user"""
        user = test_user_with_token["user"]

        # First activate
        from app.database import update_user_state
        update_user_state(user.discord_id, True)

        response = api_client.post(
            "/api/pause",
            headers={"X-API-Key": user.api_key}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "paused"

        # Verify user is paused
        from app.database import get_user_by_discord_id
        updated = get_user_by_discord_id(user.discord_id)
        assert updated.is_active is False


class TestStatusEndpoint:
    """Test /api/status endpoint"""

    def test_status_returns_user_info(self, api_client, test_user):
        """Should return user status"""
        response = api_client.get(
            "/api/status",
            headers={"X-API-Key": test_user.api_key}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is False
        assert data["has_token"] is False

    def test_status_with_token(self, api_client, test_user_with_token):
        """Should show has_token=True when token exists"""
        user = test_user_with_token["user"]

        response = api_client.get(
            "/api/status",
            headers={"X-API-Key": user.api_key}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["has_token"] is True