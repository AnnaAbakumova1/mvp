"""
Enhanced dish matcher v2 with improved pipeline.

Integrates:
- PDF parsing with OCR fallback
- Browser rendering for JS-heavy sites
- Async task queue for heavy operations
- Result caching

Pipeline:
1. Find restaurant website (site_finder)
2. Parse menu (menu_parser_v2) with fallback chain
3. Search for dish in extracted text
4. Return result with metadata
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, List

from models import MenuItem, SearchResult, Restaurant, RestaurantStatus
from services.site_finder import site_finder
from services.menu_parser_v2 import menu_parser_v2, MenuParseResult, MenuSource
from services.task_queue import task_queue, TaskPriority, TaskResult
from utils.text_utils import find_dish_in_text, extract_price, normalize_text

logger = logging.getLogger(__name__)


@dataclass
class DishSearchResult:
    """Extended search result with metadata."""
    restaurant: Restaurant
    status: RestaurantStatus
    menu_url: Optional[str] = None
    menu_item: Optional[MenuItem] = None
    menu_source: Optional[MenuSource] = None
    error_message: Optional[str] = None
    
    def to_search_result(self) -> SearchResult:
        """Convert to legacy SearchResult for compatibility."""
        return SearchResult(
            restaurant=self.restaurant,
            status=self.status,
            menu_url=self.menu_url,
            menu_item=self.menu_item,
            error_message=self.error_message,
        )


class DishMatcherV2:
    """
    Enhanced dish matcher with multi-strategy parsing.
    
    Features:
    - Supports PDF menus with OCR fallback
    - Browser rendering for JS-heavy sites
    - Parallel processing via task queue
    - Caching at multiple levels
    """
    
    async def search_dish(
        self,
        restaurant: Restaurant,
        dish_name: str,
        use_task_queue: bool = False,
    ) -> DishSearchResult:
        """
        Search for dish in restaurant's menu.
        
        Args:
            restaurant: Restaurant to search in
            dish_name: Name of dish to find
            use_task_queue: Use async task queue for heavy operations
            
        Returns:
            DishSearchResult with status and findings
        """
        result = DishSearchResult(
            restaurant=restaurant,
            status=RestaurantStatus.PENDING
        )
        
        # Step 1: Find website
        website = await site_finder.find_website(restaurant)
        
        if not website:
            result.status = RestaurantStatus.SITE_NOT_FOUND
            logger.info(f"No website for: {restaurant.name}")
            return result
        
        # Update restaurant with website
        result.restaurant = Restaurant(
            id=restaurant.id,
            name=restaurant.name,
            address=restaurant.address,
            lat=restaurant.lat,
            lon=restaurant.lon,
            website=website,
        )
        
        # Step 2: Parse menu
        if use_task_queue:
            parse_result = await self._search_via_queue(website, dish_name)
        else:
            parse_result = await menu_parser_v2.find_and_parse_menu(
                website_url=website,
                dish_name=dish_name,
                use_browser_fallback=True,
                timeout=30
            )
        
        # Step 3: Process result
        if not parse_result.success:
            result.status = RestaurantStatus.MENU_UNAVAILABLE
            result.error_message = parse_result.error or "Menu not found"
            logger.info(f"Menu unavailable for {restaurant.name}: {result.error_message}")
            return result
        
        result.menu_url = parse_result.menu_url
        result.menu_source = parse_result.source
        
        # Step 4: Check if dish was found
        if not parse_result.dish_found:
            result.status = RestaurantStatus.MENU_UNAVAILABLE
            result.error_message = "Dish not found in menu"
            logger.info(f"Dish '{dish_name}' not found in {restaurant.name}")
            return result
        
        # Step 5: Build menu item
        matched_name = self._extract_dish_name(
            parse_result.menu_text,
            parse_result.dish_position,
            dish_name
        )
        
        menu_item = MenuItem(
            name=matched_name,
            price=parse_result.price,
            price_raw=parse_result.price_raw,
        )
        
        result.menu_item = menu_item
        
        if parse_result.price is not None:
            result.status = RestaurantStatus.FOUND
            logger.info(f"Found '{matched_name}' at {restaurant.name}: {parse_result.price}")
        else:
            result.status = RestaurantStatus.FOUND_NO_PRICE
            logger.info(f"Found '{matched_name}' at {restaurant.name}, price unknown")
        
        return result
    
    async def _search_via_queue(
        self,
        website: str,
        dish_name: str
    ) -> MenuParseResult:
        """Execute search via task queue for non-blocking processing."""
        
        result = await task_queue.submit_and_wait(
            task_type="menu_search",
            params={
                "website_url": website,
                "dish_name": dish_name,
            },
            timeout=45.0,
            priority=TaskPriority.NORMAL,
        )
        
        if result.success and isinstance(result.result, MenuParseResult):
            return result.result
        
        # Convert dict result to MenuParseResult
        if result.success and isinstance(result.result, dict):
            return MenuParseResult(
                success=result.result.get("success", False),
                menu_url=result.result.get("menu_url"),
                menu_text=result.result.get("menu_text"),
                dish_found=result.result.get("dish_found", False),
                dish_position=result.result.get("dish_position"),
                price=result.result.get("price"),
                price_raw=result.result.get("price_raw"),
                error=result.result.get("error"),
            )
        
        return MenuParseResult(
            success=False,
            error=result.error or "Task queue error"
        )
    
    async def search_dish_batch(
        self,
        restaurants: List[Restaurant],
        dish_name: str,
        max_concurrent: int = 3,
        use_task_queue: bool = False,
    ) -> List[DishSearchResult]:
        """
        Search for dish in multiple restaurants concurrently.
        
        Args:
            restaurants: List of restaurants to search
            dish_name: Dish to find
            max_concurrent: Max concurrent searches
            use_task_queue: Use task queue for heavy operations
            
        Returns:
            List of DishSearchResult
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def search_one(restaurant: Restaurant) -> DishSearchResult:
            async with semaphore:
                try:
                    return await self.search_dish(
                        restaurant,
                        dish_name,
                        use_task_queue=use_task_queue
                    )
                except Exception as e:
                    logger.error(f"Search error for {restaurant.name}: {e}")
                    return DishSearchResult(
                        restaurant=restaurant,
                        status=RestaurantStatus.MENU_UNAVAILABLE,
                        error_message=str(e)
                    )
        
        tasks = [search_one(r) for r in restaurants]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions
        valid_results = []
        for result in results:
            if isinstance(result, DishSearchResult):
                valid_results.append(result)
            elif isinstance(result, Exception):
                logger.error(f"Batch search error: {result}")
        
        return valid_results
    
    async def search_dish_progressive(
        self,
        restaurants: List[Restaurant],
        dish_name: str,
        target_count: int = 3,
        on_found: Optional[callable] = None,
    ) -> List[DishSearchResult]:
        """
        Search restaurants progressively, stopping when target count is reached.
        
        Calls on_found callback each time a dish is found.
        
        Args:
            restaurants: List of restaurants
            dish_name: Dish to find
            target_count: Stop after finding this many
            on_found: Async callback(result) called when dish is found
            
        Returns:
            List of successful results
        """
        found_results = []
        semaphore = asyncio.Semaphore(2)  # Lower concurrency for progressive
        
        async def search_one(restaurant: Restaurant) -> Optional[DishSearchResult]:
            if len(found_results) >= target_count:
                return None
            
            async with semaphore:
                if len(found_results) >= target_count:
                    return None
                
                result = await self.search_dish(restaurant, dish_name)
                
                if result.status in (RestaurantStatus.FOUND, RestaurantStatus.FOUND_NO_PRICE):
                    found_results.append(result)
                    
                    if on_found:
                        try:
                            await on_found(result)
                        except Exception as e:
                            logger.error(f"on_found callback error: {e}")
                    
                    return result
                
                return None
        
        # Process in batches
        batch_size = 5
        for i in range(0, len(restaurants), batch_size):
            if len(found_results) >= target_count:
                break
            
            batch = restaurants[i:i + batch_size]
            tasks = [search_one(r) for r in batch]
            await asyncio.gather(*tasks, return_exceptions=True)
        
        return found_results
    
    def _extract_dish_name(
        self,
        text: Optional[str],
        position: Optional[int],
        search_query: str
    ) -> str:
        """Extract actual dish name from menu text."""
        if not text or position is None:
            return search_query.title()
        
        try:
            # Get context around match
            start = max(0, position - 10)
            end = min(len(text), position + 50)
            context = text[start:end]
            
            # Look for capitalized phrase or phrase before price
            words = context.split()
            
            if len(words) >= 2:
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
        
        return search_query.title()


# Global instance
dish_matcher_v2 = DishMatcherV2()


# --- Convenience functions for backward compatibility ---

async def search_dish(restaurant: Restaurant, dish_name: str) -> SearchResult:
    """
    Search for dish in restaurant (backward compatible).
    
    Use dish_matcher_v2.search_dish() for extended features.
    """
    result = await dish_matcher_v2.search_dish(restaurant, dish_name)
    return result.to_search_result()
