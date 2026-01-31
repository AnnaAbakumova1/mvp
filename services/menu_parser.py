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
    "/menu",
    "/меню",
    "/menu.html",
    "/food",
    "/dishes",
    "/carta",
]


class MenuParser:
    """Service for finding and parsing restaurant menu pages."""
    
    async def find_menu_url(self, website_url: str) -> Optional[str]:
        """
        Find menu page URL starting from restaurant's main website.
        
        Strategy:
        1. Load main page
        2. Search for links containing menu keywords
        3. Try common menu paths if no link found
        
        Args:
            website_url: Restaurant's main website URL
            
        Returns:
            Menu page URL or None
        """
        logger.debug(f"Finding menu for: {website_url}")
        
        # Ensure URL has scheme
        if not website_url.startswith("http"):
            website_url = f"https://{website_url}"
        
        # Load main page
        html = await http_client.get(website_url)
        if not html:
            return None
        
        try:
            soup = BeautifulSoup(html, "lxml")
            
            # Strategy 1: Find links with menu keywords
            menu_url = self._find_menu_link(soup, website_url)
            if menu_url:
                logger.info(f"Found menu link: {menu_url}")
                return menu_url
            
            # Strategy 2: Check if main page IS the menu
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
        
        return None
    
    def _find_menu_link(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Find menu link in page HTML."""
        
        # Check all links
        for link in soup.find_all("a", href=True):
            href = link.get("href", "").lower()
            text = link.get_text().lower()
            
            # Skip PDF files (not supported in MVP)
            if href.endswith(".pdf"):
                continue
            
            # Check if link text or URL contains menu keywords
            for keyword in MENU_KEYWORDS:
                if keyword in href or keyword in text:
                    full_url = urljoin(base_url, link["href"])
                    return full_url
        
        # Check navigation menus specifically
        nav_elements = soup.find_all(["nav", "header", "ul"])
        for nav in nav_elements:
            for link in nav.find_all("a", href=True):
                text = link.get_text().lower()
                for keyword in MENU_KEYWORDS:
                    if keyword in text:
                        full_url = urljoin(base_url, link["href"])
                        return full_url
        
        return None
    
    def _page_looks_like_menu(self, soup: BeautifulSoup) -> bool:
        """Check if page content looks like a menu."""
        text = soup.get_text().lower()
        
        # Count menu-related keywords
        menu_indicators = [
            "меню", "блюд", "цена", "порция", "грамм",
            "салат", "суп", "горячее", "десерт", "напитки",
            "₽", "руб", "рубл",
        ]
        
        count = sum(1 for indicator in menu_indicators if indicator in text)
        
        # If many menu indicators present, likely a menu page
        return count >= 5
    
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
    
    async def get_menu_text(self, menu_url: str) -> Optional[str]:
        """
        Load menu page and extract text content.
        
        Args:
            menu_url: URL of menu page
            
        Returns:
            Extracted text content or None
        """
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
