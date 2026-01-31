"""
Restaurant website finder using 2GIS web pages and Yandex search (fallback).
"""
import logging
import re
from typing import Optional
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from config import settings
from models import Restaurant
from utils.http_client import http_client

logger = logging.getLogger(__name__)

# 2GIS web URL template
TWOGIS_FIRM_URL = "https://2gis.ru/moscow/firm/{firm_id}"

# Yandex search URL (HTML version)
YANDEX_SEARCH_URL = "https://yandex.ru/search/"


class SiteFinder:
    """
    Service for finding restaurant websites.
    
    Primary source: 2GIS web pages (parsing HTML)
    Fallback: Yandex search (if enabled in config)
    """
    
    async def find_website(self, restaurant: Restaurant) -> Optional[str]:
        """
        Find official website for a restaurant.
        
        Strategy:
        1. Try 2GIS web page for the restaurant
        2. If not found and Yandex search enabled, try Yandex
        
        Args:
            restaurant: Restaurant object with id and name
            
        Returns:
            Website URL or None
        """
        # Strategy 1: 2GIS web page
        website = await self._find_on_2gis(restaurant)
        if website:
            logger.info(f"Found website via 2GIS: {website}")
            return website
        
        # Strategy 2: Yandex search (fallback, if enabled)
        if settings.enable_yandex_search:
            website = await self._find_via_yandex(restaurant)
            if website:
                logger.info(f"Found website via Yandex: {website}")
                return website
        
        logger.info(f"No website found for: {restaurant.name}")
        return None
    
    async def _find_on_2gis(self, restaurant: Restaurant) -> Optional[str]:
        """
        Parse 2GIS web page to find restaurant website.
        
        The website link is typically in the contact section of the firm page.
        """
        url = TWOGIS_FIRM_URL.format(firm_id=restaurant.id)
        
        logger.debug(f"Fetching 2GIS page: {url}")
        
        html = await http_client.get(url)
        if not html:
            return None
        
        try:
            soup = BeautifulSoup(html, "lxml")
            
            # Look for website links in various possible locations
            # Pattern 1: Link with specific class or data attribute
            website_patterns = [
                # Links containing "website" in class
                soup.find_all("a", class_=re.compile(r"website|site|url", re.I)),
                # Links with href starting with http and not 2gis
                soup.find_all("a", href=re.compile(r"^https?://(?!.*2gis)", re.I)),
            ]
            
            for links in website_patterns:
                for link in links:
                    href = link.get("href", "")
                    # Filter out social media and irrelevant links
                    if self._is_valid_website(href):
                        return href
            
            # Pattern 2: Look for text "Сайт:" followed by URL
            text = soup.get_text()
            site_match = re.search(r"[Сс]айт[:\s]+([a-zA-Z0-9][a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,})", text)
            if site_match:
                domain = site_match.group(1)
                return f"https://{domain}"
            
        except Exception as e:
            logger.error(f"Error parsing 2GIS page: {e}")
        
        return None
    
    async def _find_via_yandex(self, restaurant: Restaurant) -> Optional[str]:
        """
        Search for restaurant website using Yandex HTML search.
        
        This is a FALLBACK method with mandatory rate limiting.
        Can be disabled via ENABLE_YANDEX_SEARCH=false in config.
        """
        query = f'"{restaurant.name}" официальный сайт меню'
        
        params = {
            "text": query,
            "lr": "213",  # Moscow region
        }
        
        logger.debug(f"Yandex search: {query}")
        
        # Rate limiting is handled by http_client
        html = await http_client.get(YANDEX_SEARCH_URL, params=params)
        if not html:
            return None
        
        try:
            soup = BeautifulSoup(html, "lxml")
            
            # Find search result links
            # Yandex organic results typically have specific classes
            result_links = soup.find_all("a", href=re.compile(r"^https?://"))
            
            for link in result_links[:10]:  # Check first 10 links
                href = link.get("href", "")
                
                # Skip Yandex internal links and known aggregators
                if self._is_valid_website(href) and self._is_likely_restaurant_site(href, restaurant.name):
                    return href
            
        except Exception as e:
            logger.error(f"Error parsing Yandex results: {e}")
        
        return None
    
    def _is_valid_website(self, url: str) -> bool:
        """Check if URL is a valid restaurant website."""
        if not url or not url.startswith("http"):
            return False
        
        # Exclude known non-restaurant domains
        excluded_domains = [
            "2gis.ru",
            "yandex.ru",
            "google.com",
            "vk.com",
            "facebook.com",
            "instagram.com",
            "twitter.com",
            "youtube.com",
            "wikipedia.org",
            "tripadvisor.ru",
            "afisha.ru",
            "restoclub.ru",
            "zoon.ru",
            "delivery-club.ru",
            "eda.yandex.ru",
        ]
        
        url_lower = url.lower()
        return not any(domain in url_lower for domain in excluded_domains)
    
    def _is_likely_restaurant_site(self, url: str, restaurant_name: str) -> bool:
        """
        Check if URL is likely the official restaurant website.
        
        Heuristic: domain contains restaurant name words.
        """
        url_lower = url.lower()
        
        # Extract significant words from restaurant name (3+ chars)
        name_words = [w.lower() for w in restaurant_name.split() if len(w) >= 3]
        
        # Check if any word appears in URL
        for word in name_words:
            # Transliterate common Russian letters for URL matching
            word_translit = self._simple_translit(word)
            if word in url_lower or word_translit in url_lower:
                return True
        
        # If no match, still accept as it might be an unrelated domain name
        return True
    
    def _simple_translit(self, text: str) -> str:
        """Simple Russian to Latin transliteration for URL matching."""
        translit_map = {
            "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
            "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
            "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
            "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
            "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch",
            "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
            "э": "e", "ю": "yu", "я": "ya",
        }
        
        result = []
        for char in text.lower():
            result.append(translit_map.get(char, char))
        
        return "".join(result)


# Global service instance
site_finder = SiteFinder()
