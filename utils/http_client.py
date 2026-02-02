"""
Async HTTP client with rate limiting, retries, and timeout handling.
"""
import asyncio
import logging
from typing import Optional, Dict, Any
from collections import defaultdict
import time
import socket

import aiohttp
from aiohttp import ClientTimeout, ClientError

from config import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """Token bucket rate limiter per domain."""
    
    def __init__(self, requests_per_second: float = 1.0):
        self.requests_per_second = requests_per_second
        self.min_interval = 1.0 / requests_per_second
        self._last_request_time: Dict[str, float] = defaultdict(float)
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
    
    async def acquire(self, domain: str) -> None:
        """Wait until we can make a request to this domain."""
        async with self._locks[domain]:
            now = time.monotonic()
            elapsed = now - self._last_request_time[domain]
            
            if elapsed < self.min_interval:
                wait_time = self.min_interval - elapsed
                logger.debug(f"Rate limiting {domain}: waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
            
            self._last_request_time[domain] = time.monotonic()


class HttpClient:
    """Async HTTP client with rate limiting and error handling."""
    
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._rate_limiter = RateLimiter(requests_per_second=1.0)
        self._yandex_rate_limiter = RateLimiter(
            requests_per_second=1.0 / settings.yandex_delay_seconds
        )
        self._twogis_rate_limiter = RateLimiter(requests_per_second=10.0)
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = ClientTimeout(total=settings.request_timeout_seconds)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                }
            )
        return self._session
    
    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc or "unknown"
    
    def _get_rate_limiter(self, url: str) -> RateLimiter:
        """Get appropriate rate limiter for URL."""
        domain = self._get_domain(url)
        
        if "yandex" in domain:
            return self._yandex_rate_limiter
        elif "2gis" in domain:
            return self._twogis_rate_limiter
        else:
            return self._rate_limiter
    
    async def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        max_retries: int = 3,
        skip_rate_limit: bool = False,
    ) -> Optional[str]:
        """
        Perform GET request with rate limiting and retries.
        
        Args:
            url: Target URL
            params: Query parameters
            headers: Additional headers
            max_retries: Maximum retry attempts
            skip_rate_limit: Skip rate limiting (for APIs with their own limits)
            
        Returns:
            Response text or None on failure
        """
        domain = self._get_domain(url)
        
        if not skip_rate_limit:
            rate_limiter = self._get_rate_limiter(url)
            await rate_limiter.acquire(domain)
        
        session = await self._get_session()
        
        for attempt in range(max_retries):
            try:
                logger.debug(f"GET {url} (attempt {attempt + 1}/{max_retries})")
                
                async with session.get(url, params=params, headers=headers) as response:
                    logger.debug(f"Response: {response.status} from {domain}")
                    
                    if response.status == 200:
                        return await response.text()
                    
                    elif response.status == 429:
                        # Rate limited - exponential backoff
                        wait_time = 2 ** attempt
                        logger.warning(f"Rate limited by {domain}, waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                        continue
                    
                    elif response.status == 403:
                        logger.warning(f"Access forbidden for {url}")
                        return None
                    
                    elif response.status >= 500:
                        # Server error - retry once
                        logger.warning(f"Server error {response.status} from {domain}")
                        if attempt == 0:
                            await asyncio.sleep(1)
                            continue
                        return None
                    
                    else:
                        logger.warning(f"Unexpected status {response.status} from {url}")
                        return None
                        
            except asyncio.TimeoutError:
                # Timeout - do NOT retry, site is slow/down
                logger.warning(f"Timeout for {url} - skipping")
                return None
            
            except (socket.gaierror, OSError) as e:
                # DNS resolution failed or network error - site doesn't exist
                logger.warning(f"DNS/Network error for {url}: {e}")
                return None
                
            except ClientError as e:
                logger.error(f"Client error for {url}: {e}")
                return None
                
            except Exception as e:
                logger.error(f"Unexpected error for {url}: {e}")
                return None
        
        return None
    
    async def get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        max_retries: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """
        Perform GET request and parse JSON response.
        
        Returns:
            Parsed JSON dict or None on failure
        """
        domain = self._get_domain(url)
        rate_limiter = self._get_rate_limiter(url)
        await rate_limiter.acquire(domain)
        
        session = await self._get_session()
        
        for attempt in range(max_retries):
            try:
                logger.debug(f"GET JSON {url} (attempt {attempt + 1}/{max_retries})")
                
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    
                    elif response.status == 429:
                        wait_time = 2 ** attempt
                        logger.warning(f"Rate limited by {domain}, waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                        continue
                    
                    elif response.status >= 500:
                        if attempt == 0:
                            await asyncio.sleep(1)
                            continue
                        return None
                    
                    else:
                        logger.warning(f"JSON request failed with status {response.status}")
                        return None
            
            except asyncio.TimeoutError:
                logger.warning(f"Timeout for JSON {url} - skipping")
                return None
            
            except (socket.gaierror, OSError) as e:
                logger.warning(f"DNS/Network error for {url}: {e}")
                return None
                        
            except Exception as e:
                logger.error(f"Error fetching JSON from {url}: {e}")
                return None
        
        return None
    
    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()


# Global client instance
http_client = HttpClient()
