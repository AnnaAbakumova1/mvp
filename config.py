"""
Configuration module - loads settings from .env file
"""
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Telegram
    telegram_bot_token: str = Field(..., env="TELEGRAM_BOT_TOKEN")
    
    # 2GIS
    twogis_api_key: str = Field(..., env="TWOGIS_API_KEY")
    
    # Search settings
    default_radius_meters: int = Field(default=1000, env="DEFAULT_RADIUS_METERS")
    max_restaurants_per_search: int = Field(default=20, env="MAX_RESTAURANTS_PER_SEARCH")
    request_timeout_seconds: int = Field(default=10, env="REQUEST_TIMEOUT_SECONDS")
    
    # Rate limiting
    yandex_delay_seconds: float = Field(default=2.0, env="YANDEX_DELAY_SECONDS")
    
    # Yandex search toggle (fallback only)
    enable_yandex_search: bool = Field(default=True, env="ENABLE_YANDEX_SEARCH")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
