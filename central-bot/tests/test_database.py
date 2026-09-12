import pytest
from datetime import datetime
from app.database import (
    create_user,
    get_user_by_discord_id,
    get_user_by_api_key,
    update_user_token,
    update_user_state,
    get_user_filters,
    save_user_filter,
    delete_user_filter,
    delete_user,
    log_notification,
    get_user_stats,
)


class TestUserOperations:
    """Test user CRUD operations"""

    def test_create_user(self, db_session):
        """Creating a user should persist it"""
        user = create_user("discord_123", "api_key_abc")

        assert user.discord_id == "discord_123"
        assert user.api_key == "api_key_abc"
        assert user.is_active is False
        assert user.created_at is not None

    def test_get_user_by_discord_id(self, test_user):
        """Should retrieve user by Discord ID"""
        found = get_user_by_discord_id(test_user.discord_id)

        assert found is not None
        assert found.discord_id == test_user.discord_id
        assert found.api_key == test_user.api_key

    def test_get_user_by_api_key(self, test_user):
        """Should retrieve user by API key"""
        found = get_user_by_api_key(test_user.api_key)

        assert found is not None
        assert found.discord_id == test_user.discord_id

    def test_get_nonexistent_user(self, db_session):
        """Should return None for missing user"""
        assert get_user_by_discord_id("nonexistent") is None
        assert get_user_by_api_key("nonexistent") is None

    def test_update_user_token(self, test_user):
        """Should update user's encrypted token"""
        update_user_token(
            test_user.discord_id,
            "encrypted_token_data",
            "salt_value",
            "passcode_hash",
            "passcode_salt"
        )

        updated = get_user_by_discord_id(test_user.discord_id)
        assert updated.encrypted_token == "encrypted_token_data"
        assert updated.token_salt == "salt_value"
        assert updated.passcode_hash == "passcode_hash"

    def test_update_user_state(self, test_user):
        """Should update user's active state"""
        update_user_state(test_user.discord_id, True)

        updated = get_user_by_discord_id(test_user.discord_id)
        assert updated.is_active is True
        assert updated.resumed_at is not None

        update_user_state(test_user.discord_id, False)
        updated = get_user_by_discord_id(test_user.discord_id)
        assert updated.is_active is False
        assert updated.paused_at is not None

    def test_delete_user(self, test_user):
        """Should delete user and all related data"""
        # Add some data first
        save_user_filter(test_user.discord_id, "channel_1", "category", "primary")
        log_notification(test_user.discord_id, "sender", "subject")

        # Delete user
        delete_user(test_user.discord_id)

        # Verify deletion
        assert get_user_by_discord_id(test_user.discord_id) is None
        assert get_user_filters(test_user.discord_id, "channel_1") == []


class TestFilterOperations:
    """Test filter CRUD operations"""

    def test_save_user_filter(self, test_user):
        """Should save a filter"""
        save_user_filter(
            test_user.discord_id,
            "channel_123",
            "category",
            "primary"
        )

        filters = get_user_filters(test_user.discord_id, "channel_123")
        assert len(filters) == 1
        assert filters[0].filter_value == "primary"

    def test_multiple_filters(self, test_user):
        """Should save multiple filters for same channel"""
        save_user_filter(test_user.discord_id, "channel_123", "category", "primary")
        save_user_filter(test_user.discord_id, "channel_123", "category", "important")
        save_user_filter(test_user.discord_id, "channel_123", "category", "social")

        filters = get_user_filters(test_user.discord_id, "channel_123")
        assert len(filters) == 3

        values = [f.filter_value for f in filters]
        assert "primary" in values
        assert "important" in values
        assert "social" in values

    def test_filters_are_channel_specific(self, test_user):
        """Filters should be isolated per channel"""
        save_user_filter(test_user.discord_id, "channel_A", "category", "primary")
        save_user_filter(test_user.discord_id, "channel_B", "category", "social")

        filters_a = get_user_filters(test_user.discord_id, "channel_A")
        filters_b = get_user_filters(test_user.discord_id, "channel_B")

        assert len(filters_a) == 1
        assert filters_a[0].filter_value == "primary"
        assert len(filters_b) == 1
        assert filters_b[0].filter_value == "social"

    def test_delete_user_filter(self, test_user):
        """Should delete a specific filter"""
        save_user_filter(test_user.discord_id, "channel_1", "category", "primary")
        save_user_filter(test_user.discord_id, "channel_1", "category", "social")

        delete_user_filter(test_user.discord_id, "channel_1", "category", "primary")

        filters = get_user_filters(test_user.discord_id, "channel_1")
        assert len(filters) == 1
        assert filters[0].filter_value == "social"


class TestNotificationOperations:
    """Test notification logging"""

    def test_log_notification(self, test_user):
        """Should log a notification"""
        log_notification(test_user.discord_id, "sender@test.com", "Test Subject")

        stats = get_user_stats(test_user.discord_id)
        assert stats["notification_count"] == 1

    def test_multiple_notifications(self, test_user):
        """Should track multiple notifications"""
        for i in range(5):
            log_notification(test_user.discord_id, f"sender{i}@test.com", f"Subject {i}")

        stats = get_user_stats(test_user.discord_id)
        assert stats["notification_count"] == 5

    def test_notification_truncates_long_content(self, test_user):
        """Should truncate long sender/subject"""
        long_string = "a" * 500

        log_notification(test_user.discord_id, long_string, long_string)

        stats = get_user_stats(test_user.discord_id)
        assert stats["notification_count"] == 1


class TestUserStats:
    """Test user statistics"""

    def test_get_user_stats_empty(self, test_user):
        """Stats should work for user with no data"""
        stats = get_user_stats(test_user.discord_id)

        assert stats["filter_count"] == 0
        assert stats["notification_count"] == 0
        assert stats["is_active"] is False

    def test_get_user_stats_with_data(self, test_user):
        """Stats should reflect user's data"""
        save_user_filter(test_user.discord_id, "channel_1", "category", "primary")
        save_user_filter(test_user.discord_id, "channel_1", "category", "social")
        log_notification(test_user.discord_id, "sender", "subject")
        update_user_state(test_user.discord_id, True)

        stats = get_user_stats(test_user.discord_id)

        assert stats["filter_count"] == 2
        assert stats["notification_count"] == 1
        assert stats["is_active"] is True