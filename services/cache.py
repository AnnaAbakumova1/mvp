"""
Caching service with SQLite backend (Redis-compatible interface).
Used for caching parsed PDF menus and expensive operations.
"""
import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional, Any, Union
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Cache directory
CACHE_DIR = Path(__file__).parent.parent / ".cache"
CACHE_DB = CACHE_DIR / "menu_cache.db"


class CacheBackend:
    """Abstract cache backend interface."""
    
    async def get(self, key: str) -> Optional[str]:
        raise NotImplementedError
    
    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        raise NotImplementedError
    
    async def delete(self, key: str) -> bool:
        raise NotImplementedError
    
    async def exists(self, key: str) -> bool:
        raise NotImplementedError


class SQLiteCache(CacheBackend):
    """
    SQLite-based cache backend.
    Thread-safe, async-compatible via run_in_executor.
    """
    
    def __init__(self, db_path: Path = CACHE_DB):
        self.db_path = db_path
        self._ensure_db()
    
    def _ensure_db(self) -> None:
        """Create cache directory and database schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at REAL,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_expires ON cache(expires_at)")
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        """Get SQLite connection with proper settings."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def _get_sync(self, key: str) -> Optional[str]:
        """Synchronous get operation."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()
            
            if not row:
                return None
            
            # Check expiration
            if row["expires_at"] and row["expires_at"] < time.time():
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                conn.commit()
                return None
            
            return row["value"]
    
    def _set_sync(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """Synchronous set operation."""
        expires_at = time.time() + ttl if ttl else None
        
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO cache (key, value, expires_at)
                VALUES (?, ?, ?)
            """, (key, value, expires_at))
            conn.commit()
        return True
    
    def _delete_sync(self, key: str) -> bool:
        """Synchronous delete operation."""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            conn.commit()
            return cursor.rowcount > 0
    
    def _exists_sync(self, key: str) -> bool:
        """Synchronous exists check."""
        return self._get_sync(key) is not None
    
    def _cleanup_sync(self) -> int:
        """Remove expired entries."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM cache WHERE expires_at IS NOT NULL AND expires_at < ?",
                (time.time(),)
            )
            conn.commit()
            return cursor.rowcount
    
    async def get(self, key: str) -> Optional[str]:
        """Async get operation."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_sync, key)
    
    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """Async set operation."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._set_sync, key, value, ttl)
    
    async def delete(self, key: str) -> bool:
        """Async delete operation."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._delete_sync, key)
    
    async def exists(self, key: str) -> bool:
        """Async exists check."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._exists_sync, key)
    
    async def cleanup(self) -> int:
        """Async cleanup of expired entries."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._cleanup_sync)


class RedisCache(CacheBackend):
    """
    Redis-based cache backend.
    Requires redis[hiredis] package.
    """
    
    def __init__(self, url: str = "redis://localhost:6379/0"):
        self.url = url
        self._client = None
    
    async def _get_client(self):
        """Lazy initialization of Redis client."""
        if self._client is None:
            try:
                import redis.asyncio as redis
                self._client = redis.from_url(self.url, decode_responses=True)
            except ImportError:
                logger.warning("redis package not installed, falling back to SQLite")
                return None
        return self._client
    
    async def get(self, key: str) -> Optional[str]:
        client = await self._get_client()
        if not client:
            return None
        try:
            return await client.get(f"menu_cache:{key}")
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            return None
    
    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        client = await self._get_client()
        if not client:
            return False
        try:
            await client.set(f"menu_cache:{key}", value, ex=ttl)
            return True
        except Exception as e:
            logger.error(f"Redis set error: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        client = await self._get_client()
        if not client:
            return False
        try:
            result = await client.delete(f"menu_cache:{key}")
            return result > 0
        except Exception as e:
            logger.error(f"Redis delete error: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        client = await self._get_client()
        if not client:
            return False
        try:
            return await client.exists(f"menu_cache:{key}") > 0
        except Exception as e:
            logger.error(f"Redis exists error: {e}")
            return False
    
    async def close(self):
        if self._client:
            await self._client.close()


class MenuCache:
    """
    High-level menu caching interface.
    Supports both Redis and SQLite backends with automatic fallback.
    """
    
    # Default TTL: 24 hours for PDF menus, 1 hour for HTML
    PDF_TTL = 86400  # 24 hours
    HTML_TTL = 3600  # 1 hour
    
    def __init__(self, backend: Optional[CacheBackend] = None):
        self._backend = backend
    
    async def _get_backend(self) -> CacheBackend:
        """Get or create cache backend with fallback."""
        if self._backend is None:
            from config import settings
            
            # Try Redis first if configured
            redis_url = getattr(settings, 'redis_url', None)
            if redis_url:
                redis_cache = RedisCache(redis_url)
                # Test connection
                try:
                    client = await redis_cache._get_client()
                    if client:
                        await client.ping()
                        self._backend = redis_cache
                        logger.info("Using Redis cache backend")
                        return self._backend
                except Exception as e:
                    logger.warning(f"Redis unavailable: {e}, falling back to SQLite")
            
            # Fallback to SQLite
            self._backend = SQLiteCache()
            logger.info("Using SQLite cache backend")
        
        return self._backend
    
    @staticmethod
    def _make_key(prefix: str, url: str, extra: str = "") -> str:
        """Generate cache key from URL."""
        content = f"{url}:{extra}"
        hash_val = hashlib.sha256(content.encode()).hexdigest()[:16]
        return f"{prefix}:{hash_val}"
    
    async def get_pdf_text(self, pdf_url: str) -> Optional[str]:
        """Get cached PDF text."""
        backend = await self._get_backend()
        key = self._make_key("pdf", pdf_url)
        
        cached = await backend.get(key)
        if cached:
            logger.debug(f"Cache hit for PDF: {pdf_url}")
            return cached
        
        logger.debug(f"Cache miss for PDF: {pdf_url}")
        return None
    
    async def set_pdf_text(self, pdf_url: str, text: str) -> bool:
        """Cache PDF text."""
        backend = await self._get_backend()
        key = self._make_key("pdf", pdf_url)
        
        result = await backend.set(key, text, ttl=self.PDF_TTL)
        if result:
            logger.debug(f"Cached PDF text for: {pdf_url}")
        return result
    
    async def get_menu_html(self, url: str) -> Optional[str]:
        """Get cached menu HTML (from Playwright)."""
        backend = await self._get_backend()
        key = self._make_key("html", url)
        return await backend.get(key)
    
    async def set_menu_html(self, url: str, html: str) -> bool:
        """Cache menu HTML."""
        backend = await self._get_backend()
        key = self._make_key("html", url)
        return await backend.set(key, html, ttl=self.HTML_TTL)
    
    async def get_menu_text(self, url: str) -> Optional[str]:
        """Get cached extracted menu text."""
        backend = await self._get_backend()
        key = self._make_key("text", url)
        return await backend.get(key)
    
    async def set_menu_text(self, url: str, text: str) -> bool:
        """Cache extracted menu text."""
        backend = await self._get_backend()
        key = self._make_key("text", url)
        return await backend.set(key, text, ttl=self.HTML_TTL)
    
    async def cleanup(self) -> int:
        """Cleanup expired entries (SQLite only)."""
        backend = await self._get_backend()
        if isinstance(backend, SQLiteCache):
            count = await backend.cleanup()
            logger.info(f"Cleaned up {count} expired cache entries")
            return count
        return 0


# Global cache instance
menu_cache = MenuCache()
