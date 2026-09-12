import pytest
import os
import tempfile
from datetime import datetime
from unittest.mock import Mock, patch

# Set test environment variables BEFORE importing app

# os.environ["DATABASE_URL"] = "sqlite:///./test_mailbot.db"
# os.environ["ENCRYPTION_SALT"] = "test_salt_32_bytes_long_here_ok"
# os.environ["API_SECRET_KEY"] = "test_api_secret_key"
# os.environ["DISCORD_BOT_TOKEN"] = "test_discord_token"
# os.environ["DISCORD_GUILD_ID"] = "123456789"

from app.database import init_db, get_db, create_user, delete_user
from app.models.user import Base, User, UserFilter, NotificationLog
from app.core.security import generate_api_key, encrypt_token, hash_passcode


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database for each test"""
    # Create tables
    init_db()

    yield

    # Cleanup: delete test database
    if os.path.exists("./test_mailbot.db"):
        os.remove("./test_mailbot.db")


@pytest.fixture
def test_user(db_session):
    """Create a test user"""
    api_key = generate_api_key()
    user = create_user("test_discord_id_123", api_key)
    yield user
    # Cleanup handled by db_session


@pytest.fixture
def test_user_with_token(db_session, test_user):
    """Create a test user with an encrypted token"""
    from app.database import update_user_token

    oauth_token = "test_oauth_refresh_token_abc123"
    passcode = "test_passcode_123"

    encrypted, salt = encrypt_token(oauth_token, passcode)
    passcode_hash, passcode_salt = hash_passcode(passcode)

    update_user_token(
        test_user.discord_id,
        encrypted,
        salt,
        passcode_hash,
        passcode_salt
    )

    return {
        "user": test_user,
        "passcode": passcode,
        "oauth_token": oauth_token,
    }


@pytest.fixture
def api_client():
    """FastAPI test client"""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture
def mock_discord_bot():
    """Mock Discord bot for command tests"""
    with patch("app.discord_bot.bot") as mock_bot:
        mock_bot.user = Mock()
        mock_bot.user.id = 123456789
        mock_bot.user.name = "TestBot"
        yield mock_bot


@pytest.fixture
def mock_redis():
    """Mock Redis client"""
    with patch("app.core.security.redis") as mock:
        mock.get.return_value = None
        mock.setex.return_value = True
        mock.delete.return_value = True
        yield mock