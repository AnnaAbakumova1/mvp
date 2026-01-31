"""
Dish matching service - searches for dishes in menu text and extracts prices.
"""
import logging
from typing import Optional

from models import MenuItem, SearchResult, Restaurant, RestaurantStatus
from services.site_finder import site_finder
from services.menu_parser import menu_parser
from utils.text_utils import find_dish_in_text, extract_price, normalize_text

logger = logging.getLogger(__name__)


class DishMatcher:
    """
    Service for searching dishes in restaurant menus.
    
    Pipeline:
    1. Find restaurant website
    2. Find menu page
    3. Extract text and search for dish
    4. Extract price (best-effort, not guaranteed)
    """
    
    async def search_dish(self, restaurant: Restaurant, dish_name: str) -> SearchResult:
        """
        Search for a dish in a restaurant's menu.
        
        Args:
            restaurant: Restaurant to search in
            dish_name: Name of dish to find
            
        Returns:
            SearchResult with status and menu item if found
        """
        result = SearchResult(restaurant=restaurant)
        
        # Step 1: Find restaurant website
        website = await site_finder.find_website(restaurant)
        
        if not website:
            result.status = RestaurantStatus.SITE_NOT_FOUND
            logger.info(f"No website for {restaurant.name}")
            return result
        
        result.restaurant = Restaurant(
            id=restaurant.id,
            name=restaurant.name,
            address=restaurant.address,
            lat=restaurant.lat,
            lon=restaurant.lon,
            website=website,
        )
        
        # Step 2: Find menu page
        menu_url = await menu_parser.find_menu_url(website)
        
        if not menu_url:
            result.status = RestaurantStatus.MENU_UNAVAILABLE
            result.error_message = "Страница меню не найдена"
            logger.info(f"No menu page for {restaurant.name}")
            return result
        
        result.menu_url = menu_url
        
        # Step 3: Get menu text
        menu_text = await menu_parser.get_menu_text(menu_url)
        
        if not menu_text:
            result.status = RestaurantStatus.MENU_UNAVAILABLE
            result.error_message = "Не удалось загрузить меню"
            logger.info(f"Failed to load menu for {restaurant.name}")
            return result
        
        # Step 4: Search for dish in text
        dish_position = find_dish_in_text(dish_name, menu_text)
        
        if dish_position is None:
            result.status = RestaurantStatus.MENU_UNAVAILABLE
            result.error_message = "Блюдо не найдено в меню"
            logger.info(f"Dish '{dish_name}' not found in {restaurant.name}")
            return result
        
        # Step 5: Extract price (best-effort, not guaranteed)
        price, price_raw = extract_price(menu_text, dish_position)
        
        # Build menu item
        # Try to extract actual dish name from menu (may differ from search query)
        matched_name = self._extract_dish_name(menu_text, dish_position, dish_name)
        
        menu_item = MenuItem(
            name=matched_name,
            price=price,
            price_raw=price_raw,
        )
        
        result.menu_item = menu_item
        
        if price is not None:
            result.status = RestaurantStatus.FOUND
            logger.info(f"Found '{matched_name}' at {restaurant.name}: {price}")
        else:
            result.status = RestaurantStatus.FOUND_NO_PRICE
            logger.info(f"Found '{matched_name}' at {restaurant.name}, price unknown")
        
        return result
    
    def _extract_dish_name(self, text: str, position: int, search_query: str) -> str:
        """
        Try to extract the actual dish name from menu text.
        
        Falls back to search query if extraction fails.
        """
        try:
            # Get context around match
            start = max(0, position - 10)
            end = min(len(text), position + 50)
            context = text[start:end]
            
            # Look for capitalized phrase or phrase before price
            # This is a simple heuristic
            words = context.split()
            
            # Find words that look like a dish name (2-4 words)
            if len(words) >= 2:
                # Take first 2-4 words as dish name
                dish_words = []
                for word in words[:4]:
                    # Stop at price-like patterns
                    if any(c.isdigit() for c in word) and len(word) <= 4:
                        break
                    dish_words.append(word)
                
                if dish_words:
                    return " ".join(dish_words)
            
        except Exception:
            pass
        
        # Fallback to search query
        return search_query.title()


# Global service instance
dish_matcher = DishMatcher()
