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
        2. Try known URLs / guessing URL from restaurant name
        3. If not found and Yandex search enabled, try Yandex
        
        Args:
            restaurant: Restaurant object with id and name
            
        Returns:
            Website URL or None
        """
        # Strategy 1: 2GIS web page (already checks name match)
        website = await self._find_on_2gis(restaurant)
        if website:
            logger.info(f"Found website via 2GIS: {website}")
            return website
        
        # Strategy 2: Try known URLs / guessing (fast for known restaurants)
        website = await self._guess_website_url(restaurant)
        if website:
            logger.info(f"Found website via URL guessing: {website}")
            return website
        
        # Strategy 3: Yandex search (fallback, if enabled)
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
        Checks that the URL matches the restaurant name.
        """
        url = TWOGIS_FIRM_URL.format(firm_id=restaurant.id)
        
        logger.debug(f"Fetching 2GIS page: {url}")
        
        html = await http_client.get(url)
        if not html:
            return None
        
        try:
            soup = BeautifulSoup(html, "lxml")
            
            # Collect all potential website links
            all_links = []
            
            # Pattern 1: Links with specific class
            all_links.extend(soup.find_all("a", class_=re.compile(r"website|site|url", re.I)))
            # Pattern 2: All external http links (not 2gis internal)
            all_links.extend(soup.find_all("a", href=re.compile(r"^https?://", re.I)))
            
            # Check each link - return first that matches restaurant name
            for link in all_links:
                href = link.get("href", "")
                
                # Extract real URL from 2GIS tracking links
                # Format: http://link.2gis.ru/...?http://real-url.ru/path
                real_url = self._extract_real_url(href)
                
                if real_url and self._is_valid_website(real_url) and self._is_likely_restaurant_site(real_url, restaurant.name):
                    return real_url
            
            # Pattern 3: Look for text "Сайт:" followed by URL
            text = soup.get_text()
            site_match = re.search(r"[Сс]айт[:\s]+([a-zA-Z0-9][a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,})", text)
            if site_match:
                domain = site_match.group(1)
                url = f"https://{domain}"
                if self._is_likely_restaurant_site(url, restaurant.name):
                    return url
            
        except Exception as e:
            logger.error(f"Error parsing 2GIS page: {e}")
        
        return None
    
    def _extract_real_url(self, url: str) -> Optional[str]:
        """
        Extract real URL from 2GIS tracking links.
        
        2GIS wraps external links in tracking: http://link.2gis.ru/...?http://real-site.ru/
        """
        if not url:
            return None
        
        # Check if it's a 2GIS tracking link
        if "link.2gis.ru" in url or "link.2gis.com" in url:
            # Extract real URL from query string
            # It's usually after the last '?' as: ...?http://real-url
            parts = url.split("?")
            if len(parts) > 1:
                # Get the last part which should contain the real URL
                real_part = parts[-1]
                if real_part.startswith("http"):
                    return real_part
            return None
        
        # Not a tracking link, return as-is
        return url
    
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
    
    async def _guess_website_url(self, restaurant: Restaurant) -> Optional[str]:
        """
        Try to guess restaurant website URL from its name.
        
        Generic patterns for Russian restaurants:
        - brandname.ru
        - brandnamepizza.ru (pizzerias)
        - brandname.rest (restaurants)
        - brandnamemsk.ru (Moscow)
        """
        # Extract brand name (first significant word)
        name_part = restaurant.name.split(',')[0]
        name_words = []
        for word in name_part.split():
            clean_word = ''.join(c for c in word.lower() if c.isalpha())
            if len(clean_word) >= 3:
                name_words.append(clean_word)
        
        if not name_words:
            return None
        
        brand = name_words[0]
        if len(brand) < 3:
            return None
        
        # Generate all transliteration variants
        translit_variants = self._get_translit_variants(brand)
        
        # Common domain patterns for restaurants
        domain_patterns = [
            "{}.ru",
            "{}pizza.ru",
            "{}.rest",
            "{}msk.ru",
            "{}-msk.ru",
            "{}cafe.ru",
            "{}bar.ru",
        ]
        
        # Try each combination
        for variant in translit_variants:
            for pattern in domain_patterns:
                url = f"https://{pattern.format(variant)}/"
                try:
                    html = await http_client.get(url, max_retries=1)
                    if html and len(html) > 500:
                        logger.info(f"Guessed website: {url} for {restaurant.name}")
                        return url
                except Exception:
                    continue
        
        return None
    
    def _get_translit_variants(self, russian_word: str) -> list:
        """
        Generate multiple transliteration variants for a Russian word.
        
        Handles common variations:
        - з → z, s (Везувио → Vezuvio, Vesuvio)
        - и → i, y
        - ы → y, i
        - й → y, i, j
        - х → h, kh
        - ц → ts, c
        - щ → sch, sh
        """
        base = self._simple_translit(russian_word)
        
        variants = {base}
        
        # Common substitution pairs (original, alternatives)
        substitutions = [
            ('z', ['s']),           # з → s (Italian style)
            ('y', ['i', 'j']),      # й/ы → i/j
            ('kh', ['h', 'x']),     # х → h/x
            ('ts', ['c', 'tz']),    # ц → c/tz
            ('sch', ['sh', 'shch']),# щ → sh
            ('yo', ['e', 'io']),    # ё → e/io
            ('yu', ['u', 'iu']),    # ю → u/iu
            ('ya', ['a', 'ia']),    # я → a/ia
        ]
        
        # Apply each substitution
        for original, alternatives in substitutions:
            new_variants = set()
            for variant in variants:
                if original in variant:
                    for alt in alternatives:
                        new_variants.add(variant.replace(original, alt))
            variants.update(new_variants)
        
        return list(variants)
    
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
            # Messengers (not real websites)
            "wa.me",
            "whatsapp.com",
            "t.me",
            "telegram.org",
        ]
        
        url_lower = url.lower()
        return not any(domain in url_lower for domain in excluded_domains)
    
    def _is_likely_restaurant_site(self, url: str, restaurant_name: str) -> bool:
        """
        Check if URL is likely the official restaurant website.
        
        Heuristic: domain OR path must contain at least one word from restaurant name.
        Uses multiple transliteration variants to handle different spellings.
        """
        from urllib.parse import urlparse
        
        parsed = urlparse(url)
        url_to_check = (parsed.netloc + parsed.path).lower()
        
        # Extract significant words from restaurant name (3+ chars, letters only)
        name_words = []
        for word in restaurant_name.split():
            clean_word = ''.join(c for c in word.lower() if c.isalpha())
            if len(clean_word) >= 3:
                name_words.append(clean_word)
        
        # Check if any word appears in domain+path
        for word in name_words:
            # Check Russian word directly
            if word in url_to_check:
                return True
            
            # Get all transliteration variants and check each
            variants = self._get_translit_variants(word)
            for variant in variants:
                if variant in url_to_check:
                    return True
        
        logger.debug(f"Rejecting {url} - URL doesn't match restaurant '{restaurant_name}'")
        return False
    
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
