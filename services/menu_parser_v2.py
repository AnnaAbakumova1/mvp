"""
Enhanced menu parser v2 with PDF support, JS rendering, and caching.

Pipeline:
1. Static HTML fetch + parse (fast)
2. PDF detection and extraction (if found)
3. Browser rendering for JS sites (fallback)
4. Result caching at each step

All operations are async and non-blocking.
"""
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional, List, Tuple
from urllib.parse import urljoin, urlparse
from enum import Enum

from bs4 import BeautifulSoup

from services.cache import menu_cache
from services.pdf_parser import pdf_parser
from services.browser_service import BrowserService, render_js_page
from utils.http_client import http_client
from utils.text_utils import find_dish_in_text, extract_price

logger = logging.getLogger(__name__)


class MenuSource(Enum):
    """Source of menu content."""
    STATIC_HTML = "static_html"
    BROWSER_RENDER = "browser_render"
    PDF_TEXT = "pdf_text"
    PDF_OCR = "pdf_ocr"


@dataclass
class MenuParseResult:
    """Result of menu parsing."""
    success: bool
    menu_url: Optional[str] = None
    menu_text: Optional[str] = None
    source: Optional[MenuSource] = None
    dish_found: bool = False
    dish_position: Optional[int] = None
    price: Optional[float] = None
    price_raw: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "menu_url": self.menu_url,
            "menu_text_length": len(self.menu_text) if self.menu_text else 0,
            "source": self.source.value if self.source else None,
            "dish_found": self.dish_found,
            "price": self.price,
            "error": self.error,
        }


# Keywords for menu detection
MENU_KEYWORDS = [
    "menu", "меню", "carta", "dishes", "блюда",
    "food", "кухня", "еда", "kitchen", "ассортимент",
]

# Common menu URL paths
COMMON_MENU_PATHS = [
    "/menu", "/меню", "/food", "/dishes", "/kitchen",
    "/кухня", "/catalog", "/ассортимент", "/carta",
]

# Minimum text length to consider content valid
MIN_CONTENT_LENGTH = 200


class MenuParserV2:
    """
    Enhanced menu parser with multi-strategy approach.
    """
    
    async def find_and_parse_menu(
        self,
        website_url: str,
        dish_name: str = "",
        use_browser_fallback: bool = True,
        timeout: int = 30,
    ) -> MenuParseResult:
        """
        Main entry point: find menu and optionally search for dish.
        
        Strategy:
        1. Check cache for menu text
        2. Fetch main page statically
        3. Check for PDF menu links
        4. Find and follow menu page links
        5. If content is minimal, try browser rendering
        6. Search for dish in extracted content
        
        Args:
            website_url: Restaurant website URL
            dish_name: Dish to search for (optional)
            use_browser_fallback: Use Playwright if static fails
            timeout: Overall timeout in seconds
            
        Returns:
            MenuParseResult with findings
        """
        logger.info(f"[MENU_V2] Starting: {website_url}, dish: '{dish_name}'")
        
        # Normalize URL
        if not website_url.startswith("http"):
            website_url = f"https://{website_url}"
        
        try:
            return await asyncio.wait_for(
                self._parse_menu_internal(website_url, dish_name, use_browser_fallback),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"[MENU_V2] Timeout for: {website_url}")
            return MenuParseResult(success=False, error="Timeout")
        except Exception as e:
            logger.error(f"[MENU_V2] Error: {e}")
            return MenuParseResult(success=False, error=str(e))
    
    async def _parse_menu_internal(
        self,
        website_url: str,
        dish_name: str,
        use_browser_fallback: bool
    ) -> MenuParseResult:
        """Internal parsing logic."""
        
        # === STEP 1: Check cache ===
        cached_text = await menu_cache.get_menu_text(website_url)
        if cached_text and len(cached_text) >= MIN_CONTENT_LENGTH:
            logger.info(f"[MENU_V2] Cache hit for: {website_url}")
            return self._process_menu_text(
                cached_text, website_url, dish_name, MenuSource.STATIC_HTML
            )
        
        # === STEP 2: Static fetch main page ===
        html = await http_client.get(website_url)
        if not html:
            logger.warning(f"[MENU_V2] Failed to fetch: {website_url}")
            
            # Try browser as fallback for blocked sites
            if use_browser_fallback:
                return await self._try_browser_fallback(website_url, dish_name)
            
            return MenuParseResult(success=False, error="Failed to fetch page")
        
        soup = BeautifulSoup(html, "lxml")
        
        # === STEP 3: Check for PDF menu ===
        pdf_result = await self._try_pdf_menu(soup, website_url, dish_name)
        if pdf_result.success:
            return pdf_result
        
        # === STEP 4: Extract and analyze main page ===
        main_text = self._extract_text(soup)
        
        # Check if main page IS the menu
        if self._page_looks_like_menu(main_text, website_url):
            logger.info(f"[MENU_V2] Main page is menu: {website_url}")
            
            result = self._process_menu_text(
                main_text, website_url, dish_name, MenuSource.STATIC_HTML
            )
            
            # Cache if successful
            if result.success and main_text:
                await menu_cache.set_menu_text(website_url, main_text)
            
            return result
        
        # === STEP 5: Find menu link and follow ===
        menu_url = await self._find_menu_url(soup, html, website_url)
        
        if menu_url and menu_url != website_url:
            logger.info(f"[MENU_V2] Found menu link: {menu_url}")
            
            # Check for PDF menu URL
            if pdf_parser.is_pdf_url(menu_url):
                return await self._parse_pdf_menu(menu_url, dish_name)
            
            # Fetch menu page
            menu_html = await http_client.get(menu_url)
            if menu_html:
                menu_soup = BeautifulSoup(menu_html, "lxml")
                
                # Check for PDF links on menu page
                pdf_result = await self._try_pdf_menu(menu_soup, menu_url, dish_name)
                if pdf_result.success:
                    return pdf_result
                
                menu_text = self._extract_text(menu_soup)
                
                if menu_text and len(menu_text) >= MIN_CONTENT_LENGTH:
                    result = self._process_menu_text(
                        menu_text, menu_url, dish_name, MenuSource.STATIC_HTML
                    )
                    
                    if result.success:
                        await menu_cache.set_menu_text(menu_url, menu_text)
                    
                    return result
        
        # === STEP 6: Try common paths ===
        for path in COMMON_MENU_PATHS:
            test_url = urljoin(website_url, path)
            
            if pdf_parser.is_pdf_url(test_url):
                pdf_result = await self._parse_pdf_menu(test_url, dish_name)
                if pdf_result.success:
                    return pdf_result
                continue
            
            test_html = await http_client.get(test_url)
            if test_html:
                test_soup = BeautifulSoup(test_html, "lxml")
                test_text = self._extract_text(test_soup)
                
                if test_text and self._page_looks_like_menu(test_text, test_url):
                    result = self._process_menu_text(
                        test_text, test_url, dish_name, MenuSource.STATIC_HTML
                    )
                    
                    if result.success:
                        await menu_cache.set_menu_text(test_url, test_text)
                    
                    return result
        
        # === STEP 7: Browser fallback for JS-heavy sites ===
        if use_browser_fallback:
            # Check if content is suspiciously short (likely JS-rendered)
            if len(main_text) < MIN_CONTENT_LENGTH:
                logger.info(f"[MENU_V2] Short content, trying browser: {website_url}")
                return await self._try_browser_fallback(website_url, dish_name)
        
        # Nothing found
        return MenuParseResult(
            success=False,
            menu_url=website_url,
            menu_text=main_text,
            error="Menu not found"
        )
    
    async def _try_pdf_menu(
        self,
        soup: BeautifulSoup,
        base_url: str,
        dish_name: str
    ) -> MenuParseResult:
        """Try to find and parse PDF menu links."""
        
        # Find PDF links
        pdf_links = await pdf_parser.find_pdf_links(str(soup), base_url)
        
        if not pdf_links:
            return MenuParseResult(success=False)
        
        logger.info(f"[MENU_V2] Found {len(pdf_links)} PDF links")
        
        # Try each PDF (prioritized by relevance)
        for pdf_url in pdf_links[:3]:  # Limit to 3 PDFs
            result = await self._parse_pdf_menu(pdf_url, dish_name)
            if result.success:
                return result
        
        return MenuParseResult(success=False)
    
    async def _parse_pdf_menu(self, pdf_url: str, dish_name: str) -> MenuParseResult:
        """Parse a PDF menu."""
        logger.info(f"[MENU_V2] Parsing PDF: {pdf_url}")
        
        text = await pdf_parser.extract_text_from_url(pdf_url)
        
        if not text or len(text) < MIN_CONTENT_LENGTH:
            return MenuParseResult(
                success=False,
                menu_url=pdf_url,
                error="PDF text extraction failed"
            )
        
        # Determine source (direct or OCR)
        # This is a heuristic - OCR text often has more errors
        has_ocr_artifacts = bool(re.search(r"[|]{2,}|[_]{3,}", text))
        source = MenuSource.PDF_OCR if has_ocr_artifacts else MenuSource.PDF_TEXT
        
        return self._process_menu_text(text, pdf_url, dish_name, source)
    
    async def _try_browser_fallback(
        self,
        url: str,
        dish_name: str
    ) -> MenuParseResult:
        """Use browser to render JS-heavy page."""
        logger.info(f"[MENU_V2] Browser fallback for: {url}")
        
        result = await render_js_page(url, timeout=25000)
        
        if not result.success:
            return MenuParseResult(
                success=False,
                menu_url=url,
                error=f"Browser rendering failed: {result.error}"
            )
        
        text = result.text
        
        if not text or len(text) < MIN_CONTENT_LENGTH:
            # Try finding menu link in rendered HTML
            browser_service = await BrowserService.get_instance()
            menu_links = await browser_service.find_menu_links(result.html, url)
            
            if menu_links:
                # Follow first menu link
                menu_url = menu_links[0]["href"]
                logger.info(f"[MENU_V2] Following browser menu link: {menu_url}")
                
                menu_result = await render_js_page(menu_url, timeout=20000)
                if menu_result.success and len(menu_result.text) >= MIN_CONTENT_LENGTH:
                    return self._process_menu_text(
                        menu_result.text,
                        menu_url,
                        dish_name,
                        MenuSource.BROWSER_RENDER
                    )
            
            return MenuParseResult(
                success=False,
                menu_url=url,
                menu_text=text,
                source=MenuSource.BROWSER_RENDER,
                error="Insufficient content after browser render"
            )
        
        return self._process_menu_text(text, result.url, dish_name, MenuSource.BROWSER_RENDER)
    
    async def _find_menu_url(
        self,
        soup: BeautifulSoup,
        html: str,
        base_url: str
    ) -> Optional[str]:
        """Find menu URL in page."""
        
        menu_links = []
        
        # Check all links
        for link in soup.find_all("a", href=True):
            href = link.get("href", "").strip()
            text = link.get_text().lower().strip()
            
            # Skip empty, anchor-only, or javascript links
            if not href or href.startswith("javascript:"):
                continue
            
            # Score link relevance
            score = 0
            for kw in MENU_KEYWORDS:
                if kw in text:
                    score += 10
                if kw in href.lower():
                    score += 5
            
            if score > 0:
                full_url = urljoin(base_url, href)
                menu_links.append((score, full_url))
        
        # Sort by score descending
        menu_links.sort(key=lambda x: x[0], reverse=True)
        
        # Return best match
        if menu_links:
            return menu_links[0][1]
        
        return None
    
    def _extract_text(self, soup: BeautifulSoup) -> str:
        """Extract clean text from HTML."""
        # Remove non-content elements
        for el in soup(["script", "style", "noscript", "iframe", "header", "footer", "nav"]):
            el.decompose()
        
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text)
        
        return text
    
    def _page_looks_like_menu(self, text: str, url: str = "") -> bool:
        """Check if text looks like a menu."""
        text_lower = text.lower()
        url_lower = url.lower()
        
        # URL indicators
        if any(kw in url_lower for kw in ["/menu", "/food", "/dishes", "/кухня"]):
            return True
        
        # Text indicators
        menu_indicators = [
            "меню", "блюд", "цена", "порция", "грамм",
            "салат", "суп", "горячее", "десерт", "напитки",
            "закуск", "₽", "руб", "menu", "dishes", "price"
        ]
        
        count = sum(1 for ind in menu_indicators if ind in text_lower)
        return count >= 3
    
    def _process_menu_text(
        self,
        text: str,
        menu_url: str,
        dish_name: str,
        source: MenuSource
    ) -> MenuParseResult:
        """Process extracted menu text and search for dish."""
        
        result = MenuParseResult(
            success=True,
            menu_url=menu_url,
            menu_text=text,
            source=source
        )
        
        # Search for dish if provided
        if dish_name:
            position = find_dish_in_text(dish_name, text)
            
            if position is not None:
                result.dish_found = True
                result.dish_position = position
                
                # Extract price
                price, price_raw = extract_price(text, position)
                result.price = price
                result.price_raw = price_raw
                
                logger.info(f"[MENU_V2] Dish found: {dish_name}, price: {price}")
            else:
                logger.info(f"[MENU_V2] Dish not found: {dish_name}")
        
        return result
    
    async def get_menu_text(
        self,
        url: str,
        use_browser: bool = False
    ) -> Optional[str]:
        """
        Simple method to get menu text from URL.
        Compatible with old API.
        """
        if use_browser:
            result = await render_js_page(url)
            return result.text if result.success else None
        
        # Check cache
        cached = await menu_cache.get_menu_text(url)
        if cached:
            return cached
        
        # Fetch and parse
        html = await http_client.get(url)
        if not html:
            return None
        
        soup = BeautifulSoup(html, "lxml")
        text = self._extract_text(soup)
        
        if text and len(text) >= MIN_CONTENT_LENGTH:
            await menu_cache.set_menu_text(url, text)
        
        return text
    
    async def find_menu_url(self, website_url: str, dish: str = "") -> Optional[str]:
        """
        Find menu URL on website.
        Compatible with old API.
        """
        result = await self.find_and_parse_menu(website_url, dish)
        return result.menu_url if result.success else None


# Global instance
menu_parser_v2 = MenuParserV2()
