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
    default_radius_meters: int = Field(default=500, env="DEFAULT_RADIUS_METERS")
    max_restaurants_per_search: int = Field(default=20, env="MAX_RESTAURANTS_PER_SEARCH")
    request_timeout_seconds: int = Field(default=20, env="REQUEST_TIMEOUT_SECONDS")
    
    # Rate limiting
    yandex_delay_seconds: float = Field(default=2.0, env="YANDEX_DELAY_SECONDS")
    
    # Yandex search toggle (fallback only)
    enable_yandex_search: bool = Field(default=True, env="ENABLE_YANDEX_SEARCH")
    
    # Agent settings (browser-based menu finder)
    agent_enabled: bool = Field(default=True, env="AGENT_ENABLED")
    agent_timeout_seconds: int = Field(default=15, env="AGENT_TIMEOUT_SECONDS")
    agent_max_steps: int = Field(default=3, env="AGENT_MAX_STEPS")
    
    # Groq API (free LLM)
    groq_api_key: str = Field(default="", env="GROQ_API_KEY")
    
    # === NEW: PDF Parsing ===
    pdf_ocr_enabled: bool = Field(default=True, env="PDF_OCR_ENABLED")
    pdf_ocr_language: str = Field(default="rus+eng", env="PDF_OCR_LANGUAGE")
    pdf_max_pages: int = Field(default=5, env="PDF_MAX_PAGES")
    
    # === NEW: Browser Service ===
    browser_timeout_ms: int = Field(default=30000, env="BROWSER_TIMEOUT_MS")
    browser_block_resources: bool = Field(default=True, env="BROWSER_BLOCK_RESOURCES")
    
    # === NEW: Cache Settings ===
    redis_url: str = Field(default="", env="REDIS_URL")  # Empty = use SQLite
    cache_pdf_ttl_seconds: int = Field(default=86400, env="CACHE_PDF_TTL")  # 24h
    cache_html_ttl_seconds: int = Field(default=3600, env="CACHE_HTML_TTL")  # 1h
    
    # === NEW: Task Queue ===
    task_queue_workers: int = Field(default=3, env="TASK_QUEUE_WORKERS")
    task_queue_max_size: int = Field(default=100, env="TASK_QUEUE_MAX_SIZE")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
