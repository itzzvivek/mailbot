import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DISCORD_BOT_TOKEN: str
    DISCORD_GUILD_ID: int

    DATABASE_URL: str

    ENCRYPTION_SALT: str
    API_KEY_LENGTH: int
    API_SECRET_KEY: str

    REDIS_URL: Optional[str] = None

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_PERIOD: int = 60


    model_config = SettingsConfigDict(
        env_file = "../.env",
        env_file_encoding = "utf-8",
    )

settings = Settings()


