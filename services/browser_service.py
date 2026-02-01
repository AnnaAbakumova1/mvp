"""
Browser service for JS-heavy websites.

Uses Playwright to render JavaScript and extract full HTML,
then analyzes it statically for menu content.

Key improvements over previous approach:
1. Uses page.content() to get full rendered HTML (no LLM needed)
2. Caches rendered HTML to avoid re-rendering
3. Reuses browser instance for multiple requests
4. Blocks unnecessary resources for faster loading
"""
import asyncio
import logging
import re
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from services.cache import menu_cache

logger = logging.getLogger(__name__)


@dataclass
class BrowserResult:
    """Result from browser rendering."""
    html: str
    text: str
    url: str  # Final URL after redirects
    success: bool
    error: Optional[str] = None


class BrowserService:
    """
    Singleton browser service for rendering JS-heavy pages.
    
    Maintains a browser instance pool for efficiency.
    """
    
    _instance = None
    _lock = asyncio.Lock()
    
    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._initialized = False
        self._init_lock = asyncio.Lock()
    
    @classmethod
    async def get_instance(cls) -> "BrowserService":
        """Get or create singleton instance."""
        async with cls._lock:
            if cls._instance is None:
                cls._instance = BrowserService()
            return cls._instance
    
    async def _ensure_browser(self) -> bool:
        """Initialize browser if needed."""
        async with self._init_lock:
            if self._initialized and self._browser:
                return True
            
            try:
                from playwright.async_api import async_playwright
                
                logger.info("[BROWSER] Initializing Playwright...")
                
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-gpu",
                    ]
                )
                
                # Create context with optimized settings
                self._context = await self._browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    java_script_enabled=True,
                    ignore_https_errors=True,
                )
                
                self._initialized = True
                logger.info("[BROWSER] Playwright initialized successfully")
                return True
                
            except ImportError:
                logger.error("[BROWSER] Playwright not installed")
                return False
            except Exception as e:
                logger.error(f"[BROWSER] Init error: {e}")
                return False
    
    async def render_page(
        self,
        url: str,
        wait_for: Optional[str] = None,
        timeout: int = 30000,
        block_resources: bool = True
    ) -> BrowserResult:
        """
        Render a page and return full HTML.
        
        Args:
            url: URL to render
            wait_for: Optional CSS selector to wait for
            timeout: Timeout in milliseconds
            block_resources: Block images/fonts for faster loading
            
        Returns:
            BrowserResult with HTML and extracted text
        """
        # Check cache first
        cached_html = await menu_cache.get_menu_html(url)
        if cached_html:
            logger.debug(f"[BROWSER] Cache hit for: {url}")
            text = self._extract_text(cached_html)
            return BrowserResult(
                html=cached_html,
                text=text,
                url=url,
                success=True
            )
        
        if not await self._ensure_browser():
            return BrowserResult(
                html="",
                text="",
                url=url,
                success=False,
                error="Browser not available"
            )
        
        page = None
        try:
            page = await self._context.new_page()
            
            # Block heavy resources for faster loading
            if block_resources:
                await page.route(
                    "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,eot,mp4,webm,ogg,mp3,wav}",
                    lambda route: route.abort()
                )
                # Also block tracking/analytics
                await page.route(
                    "**/{google-analytics,googletagmanager,facebook,yandex.metrica}**",
                    lambda route: route.abort()
                )
            
            logger.info(f"[BROWSER] Loading: {url}")
            
            # Navigate to page
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=timeout
            )
            
            if not response:
                return BrowserResult(
                    html="",
                    text="",
                    url=url,
                    success=False,
                    error="No response from server"
                )
            
            # Wait for additional content if needed
            if wait_for:
                try:
                    await page.wait_for_selector(wait_for, timeout=5000)
                except Exception:
                    pass  # Continue even if selector not found
            
            # Wait for network to settle
            await page.wait_for_load_state("networkidle", timeout=10000)
            
            # Additional wait for JS rendering
            await page.wait_for_timeout(1500)
            
            # Get final URL (after redirects)
            final_url = page.url
            
            # Get full rendered HTML
            html = await page.content()
            
            # Extract visible text
            text = await page.evaluate("""
                () => {
                    // Remove script and style elements
                    const clone = document.body.cloneNode(true);
                    clone.querySelectorAll('script, style, noscript, iframe').forEach(el => el.remove());
                    return clone.innerText || clone.textContent || '';
                }
            """)
            
            # Clean up text
            text = re.sub(r"\s+", " ", text).strip() if text else ""
            
            # Cache the result
            if html and len(html) > 500:
                await menu_cache.set_menu_html(url, html)
            
            logger.info(f"[BROWSER] Rendered {len(html)} chars HTML, {len(text)} chars text")
            
            return BrowserResult(
                html=html,
                text=text,
                url=final_url,
                success=True
            )
            
        except asyncio.TimeoutError:
            logger.warning(f"[BROWSER] Timeout for: {url}")
            return BrowserResult(
                html="",
                text="",
                url=url,
                success=False,
                error="Timeout"
            )
        except Exception as e:
            logger.error(f"[BROWSER] Error rendering {url}: {e}")
            return BrowserResult(
                html="",
                text="",
                url=url,
                success=False,
                error=str(e)
            )
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
    
    def _extract_text(self, html: str) -> str:
        """Extract text from HTML."""
        try:
            soup = BeautifulSoup(html, "lxml")
            for el in soup(["script", "style", "noscript", "iframe"]):
                el.decompose()
            text = soup.get_text(separator=" ", strip=True)
            return re.sub(r"\s+", " ", text)
        except Exception:
            return ""
    
    async def find_menu_links(self, html: str, base_url: str) -> List[Dict[str, str]]:
        """
        Find menu-related links in rendered HTML.
        
        Returns list of {text, href, score} dicts, sorted by relevance.
        """
        try:
            soup = BeautifulSoup(html, "lxml")
            links = []
            
            menu_keywords = [
                "меню", "menu", "блюда", "dishes", "кухня", "kitchen",
                "food", "еда", "карта", "carta", "наши блюда", "our dishes",
                "ассортимент", "каталог", "catalog"
            ]
            
            ignore_keywords = [
                "корзина", "cart", "заказ", "order", "доставка", "delivery",
                "контакт", "contact", "о нас", "about", "бронир", "book",
                "акции", "promo", "новости", "news", "вакансии", "career",
                "отзыв", "review", "вход", "login", "регистр", "register"
            ]
            
            for link in soup.find_all("a", href=True):
                href = link.get("href", "").strip()
                text = link.get_text().lower().strip()
                
                if not href or href.startswith("#") and len(href) < 3:
                    continue
                
                # Skip ignored links
                if any(kw in text or kw in href.lower() for kw in ignore_keywords):
                    continue
                
                # Calculate relevance score
                score = 0
                
                for kw in menu_keywords:
                    if kw in text:
                        score += 10
                    if kw in href.lower():
                        score += 5
                
                # Check URL path
                if "/menu" in href.lower() or "/food" in href.lower():
                    score += 15
                
                if score > 0:
                    full_url = urljoin(base_url, href)
                    
                    # Skip external links
                    parsed_base = urlparse(base_url)
                    parsed_href = urlparse(full_url)
                    if parsed_href.netloc and parsed_href.netloc != parsed_base.netloc:
                        continue
                    
                    links.append({
                        "text": link.get_text().strip()[:50],
                        "href": full_url,
                        "score": score
                    })
            
            # Sort by score descending
            links.sort(key=lambda x: x["score"], reverse=True)
            
            # Deduplicate by href
            seen = set()
            unique_links = []
            for link in links:
                if link["href"] not in seen:
                    seen.add(link["href"])
                    unique_links.append(link)
            
            return unique_links[:10]  # Top 10 links
            
        except Exception as e:
            logger.error(f"[BROWSER] Error finding links: {e}")
            return []
    
    async def close(self):
        """Clean up browser resources."""
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.error(f"[BROWSER] Cleanup error: {e}")
        finally:
            self._initialized = False
            self._playwright = None
            self._browser = None
            self._context = None


# Convenience function
async def render_js_page(url: str, timeout: int = 30000) -> BrowserResult:
    """Render a JS-heavy page and return result."""
    service = await BrowserService.get_instance()
    return await service.render_page(url, timeout=timeout)


async def close_browser():
    """Close the browser service."""
    if BrowserService._instance:
        await BrowserService._instance.close()
        BrowserService._instance = None
