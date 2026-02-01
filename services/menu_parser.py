"""
Menu page discovery and HTML parsing.
"""
import logging
import re
from typing import Optional, List
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from utils.http_client import http_client

logger = logging.getLogger(__name__)

# Keywords to identify menu pages
MENU_KEYWORDS = [
    "menu", "меню", "carta", "dishes", "блюда",
    "food", "кухня", "еда", "kitchen", "ассортимент",
]

# Common menu URL paths
COMMON_MENU_PATHS = [
    "/",  # Главная страница может быть меню
    "/#menu",  # Anchor-based menu sections
    "/menu",
    "/меню",
    "/menu.html",
    "/food",
    "/dishes",
    "/carta",
    "/catalog",
    "/products",
    "/assortment",
    "/kitchen",
    "/кухня",
    "/ассортимент",
    "/pizza",  # Common for pizzerias
    "/пицца",
]


class MenuParser:
    """Service for finding and parsing restaurant menu pages."""
    
    async def find_menu_url(self, website_url: str, dish: str = "") -> Optional[str]:
        """
        Find menu page URL starting from restaurant's main website.
        
        Strategy (hybrid approach):
        1. Static parser: Load main page, check for menu
        2. Static parser: Search for menu links
        3. Static parser: Try common paths
        4. Agent fallback: Use browser-based agent if enabled
        
        Args:
            website_url: Restaurant's main website URL
            dish: Dish name to search for (optional, for agent)
            
        Returns:
            Menu page URL or None
        """
        logger.debug(f"Finding menu for: {website_url}")
        
        # Ensure URL has scheme
        if not website_url.startswith("http"):
            website_url = f"https://{website_url}"
        
        # === STATIC PARSING (fast and cheap) ===
        
        # Load main page
        html = await http_client.get(website_url)
        if not html:
            logger.warning(f"Failed to load main page: {website_url}")
            # Try agent as fallback
            return await self._try_agent_fallback(website_url, dish)
        
        try:
            soup = BeautifulSoup(html, "lxml")
            
            # Strategy 1: Find links with menu keywords (including anchors like #menu)
            menu_url = self._find_menu_link(soup, website_url)
            if menu_url:
                logger.info(f"Found menu link: {menu_url}")
                return menu_url
            
            # Strategy 2: Check if main page IS the menu (no specific menu link found)
            if self._page_looks_like_menu(soup):
                logger.info(f"Main page appears to be menu: {website_url}")
                return website_url
            
            # Strategy 3: Try common paths
            menu_url = await self._try_common_paths(website_url)
            if menu_url:
                logger.info(f"Found menu at common path: {menu_url}")
                return menu_url
            
        except Exception as e:
            logger.error(f"Error finding menu: {e}")
        
        # === AGENT FALLBACK (slow but smart) ===
        logger.info(f"Static parser failed, trying agent for: {website_url}")
        return await self._try_agent_fallback(website_url, dish)
    
    async def _try_agent_fallback(self, website_url: str, dish: str = "") -> Optional[str]:
        """Try browser-based agent as fallback."""
        from config import settings
        
        if not settings.agent_enabled:
            logger.info("Agent is disabled")
            return None
        
        try:
            from services.agent_menu_finder import menu_finder_agent
            
            result = await menu_finder_agent.find_menu_and_dish(
                site_url=website_url,
                dish=dish,
                timeout=settings.agent_timeout_seconds,
                max_steps=settings.agent_max_steps
            )
            
            if result.menu_url:
                logger.info(f"[AGENT] Found menu: {result.menu_url}")
                return result.menu_url
            else:
                logger.info(f"[AGENT] No menu found, status: {result.status}")
                return None
                
        except ImportError as e:
            logger.warning(f"Agent not available (playwright not installed?): {e}")
            return None
        except Exception as e:
            logger.error(f"Agent error: {e}")
            return None
    
    def _find_menu_link(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Find menu link in page HTML."""
        
        menu_links = []  # Collect all potential menu links
        anchor_links = []  # Links with #menu anchors
        parsed_base = urlparse(base_url)
        base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"
        
        # Check all links
        for link in soup.find_all("a", href=True):
            href = link.get("href", "").strip()
            href_lower = href.lower()
            text = link.get_text().lower().strip()
            
            # Skip PDF files (not supported in MVP)
            if href_lower.endswith(".pdf"):
                continue
            
            # Fix malformed URLs like "/https://..." or "/http://..."
            if href.startswith("/https://") or href.startswith("/http://"):
                href = href[1:]  # Remove leading slash
                href_lower = href.lower()
            
            # Check if link text or URL contains menu keywords
            for keyword in MENU_KEYWORDS:
                if keyword in href_lower or keyword in text:
                    full_url = urljoin(base_url, href)
                    
                    # Detect anchor links: #menu, /#menu, or full URLs like site.com/#menu
                    # These point to the same page, just a section
                    parsed_href = urlparse(full_url)
                    is_same_page_anchor = (
                        parsed_href.fragment and  # Has #something
                        (not parsed_href.path or parsed_href.path == "/" or parsed_href.path == "")
                    )
                    
                    # Also check relative anchors
                    is_relative_anchor = (
                        href.startswith("#") or 
                        href.startswith("/#")
                    )
                    
                    is_anchor = is_same_page_anchor or is_relative_anchor
                    
                    if is_anchor:
                        anchor_url = f"{base_domain}/#{parsed_href.fragment}" if parsed_href.fragment else full_url
                        if anchor_url not in anchor_links:
                            anchor_links.append(anchor_url)
                    else:
                        if full_url not in menu_links:
                            menu_links.append(full_url)
                    break
        
        # Also find "Открыть меню" style links (common on Tilda sites)
        for link in soup.find_all("a", href=True):
            text = link.get_text().lower().strip()
            href = link.get("href", "")
            
            if "открыть" in text and ("меню" in text or "menu" in href.lower()):
                full_url = urljoin(base_url, href)
                if full_url not in menu_links and not href.startswith("#"):
                    menu_links.append(full_url)
        
        # Check navigation menus specifically
        nav_elements = soup.find_all(["nav", "header", "ul"])
        for nav in nav_elements:
            for link in nav.find_all("a", href=True):
                text = link.get_text().lower()
                href = link.get("href", "").strip()
                
                # Fix malformed URLs
                if href.startswith("/https://") or href.startswith("/http://"):
                    href = href[1:]
                
                for keyword in MENU_KEYWORDS:
                    if keyword in text:
                        # Detect anchor links
                        is_anchor = (
                            href.startswith("#") or 
                            href.startswith("/#") or
                            (href.startswith("/") and "#" in href and href.index("#") < 10)
                        )
                        
                        if is_anchor:
                            anchor = href.lstrip("/").rstrip("/")
                            if not anchor.startswith("#"):
                                anchor = "#" + anchor.split("#")[-1]
                            full_url = f"{base_domain}/{anchor}"
                            if full_url not in anchor_links:
                                anchor_links.append(full_url)
                        else:
                            full_url = urljoin(base_url, href)
                            if full_url not in menu_links:
                                menu_links.append(full_url)
                        break
        
        # Prefer real page links over anchor links
        if menu_links:
            logger.debug(f"Found {len(menu_links)} menu page links: {menu_links[:3]}")
            return menu_links[0]
        
        # Fall back to anchor links (like #menu) - return URL with anchor
        if anchor_links:
            logger.debug(f"Found {len(anchor_links)} anchor links: {anchor_links[:3]}")
            return anchor_links[0]
        
        return None
    
    def _page_looks_like_menu(self, soup: BeautifulSoup) -> bool:
        """Check if page content looks like a menu."""
        text = soup.get_text().lower()
        
        # Count menu-related keywords
        menu_indicators = [
            "меню", "блюд", "цена", "порция", "грамм",
            "салат", "суп", "горячее", "десерт", "напитки",
            "₽", "руб", "рубл", "заказ", "доставка",
            "breakfast", "lunch", "dinner", "appetizer",
            "main course", "dessert", "beverage", "price",
        ]
        
        count = sum(1 for indicator in menu_indicators if indicator in text)
        
        # If many menu indicators present, likely a menu page
        logger.debug(f"Menu indicators count: {count}")
        return count >= 3  # Снизил порог с 5 до 3
    
    async def _try_common_paths(self, base_url: str) -> Optional[str]:
        """Try common menu URL paths."""
        parsed = urlparse(base_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        
        for path in COMMON_MENU_PATHS:
            url = f"{base}{path}"
            
            html = await http_client.get(url)
            if html:
                try:
                    soup = BeautifulSoup(html, "lxml")
                    if self._page_looks_like_menu(soup):
                        return url
                except Exception:
                    pass
        
        return None
    
    async def get_menu_text(self, menu_url: str, use_browser: bool = False) -> Optional[str]:
        """
        Load menu page and extract text content.
        
        Args:
            menu_url: URL of menu page
            use_browser: If True, use Playwright for JavaScript rendering
            
        Returns:
            Extracted text content or None
        """
        if use_browser:
            return await self._get_menu_text_with_browser(menu_url)
        
        html = await http_client.get(menu_url)
        if not html:
            return None
        
        try:
            soup = BeautifulSoup(html, "lxml")
            
            # Remove script and style elements
            for element in soup(["script", "style", "noscript", "iframe"]):
                element.decompose()
            
            # Get text
            text = soup.get_text(separator=" ", strip=True)
            
            # Clean up whitespace
            text = re.sub(r"\s+", " ", text)
            
            return text
            
        except Exception as e:
            logger.error(f"Error extracting menu text: {e}")
            return None
    
    async def _get_menu_text_with_browser(self, menu_url: str) -> Optional[str]:
        """
        Load menu page with Playwright (JavaScript rendering).
        
        Used for sites like Tilda that load content dynamically.
        """
        try:
            from playwright.async_api import async_playwright
            
            logger.info(f"[BROWSER] Loading {menu_url} with Playwright")
            
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(headless=True)
            
            try:
                context = await browser.new_context(
                    viewport={'width': 1280, 'height': 720},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )
                page = await context.new_page()
                
                # Block images for faster loading
                await page.route("**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf}", 
                               lambda route: route.abort())
                
                await page.goto(menu_url, wait_until='domcontentloaded', timeout=30000)
                
                # Wait for content to load
                await page.wait_for_timeout(2000)
                
                # Get rendered text
                text = await page.evaluate('''() => {
                    return document.body.innerText || document.body.textContent || '';
                }''')
                
                # Clean up whitespace
                text = re.sub(r"\s+", " ", text) if text else None
                
                logger.info(f"[BROWSER] Extracted {len(text) if text else 0} chars")
                return text
                
            finally:
                await browser.close()
                await playwright.stop()
                
        except ImportError:
            logger.warning("[BROWSER] Playwright not installed")
            return None
        except Exception as e:
            logger.error(f"[BROWSER] Error: {e}")
            return None
    
    async def get_menu_html(self, menu_url: str) -> Optional[str]:
        """
        Load menu page and return raw HTML.
        
        Useful for more sophisticated parsing.
        
        Returns:
            Raw HTML or None
        """
        return await http_client.get(menu_url)


# Global service instance
menu_parser = MenuParser()
