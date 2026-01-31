"""
Data models for the restaurant search bot.
"""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class RestaurantStatus(str, Enum):
    """Status of restaurant menu search result."""
    FOUND = "found"                      # Dish found with price
    FOUND_NO_PRICE = "found_no_price"    # Dish found, price unknown
    MENU_UNAVAILABLE = "menu_unavailable"  # Site found, menu not parseable
    SITE_NOT_FOUND = "site_not_found"    # Restaurant website not found
    PENDING = "pending"                  # Not yet processed


class Restaurant(BaseModel):
    """Restaurant data from 2GIS API."""
    id: str
    name: str
    address: str
    lat: float
    lon: float
    website: Optional[str] = None
    
    class Config:
        frozen = True


class MenuItem(BaseModel):
    """Menu item found in restaurant."""
    name: str
    price: Optional[float] = None
    price_raw: Optional[str] = None  # Original price string


class SearchResult(BaseModel):
    """Result of searching for a dish in a restaurant."""
    restaurant: Restaurant
    status: RestaurantStatus = RestaurantStatus.PENDING
    menu_url: Optional[str] = None
    menu_item: Optional[MenuItem] = None
    error_message: Optional[str] = None
    
    def format_for_user(self) -> str:
        """Format result for Telegram message."""
        lines = [f"*{self.restaurant.name}*"]
        lines.append(f"   {self.restaurant.address}")
        
        if self.status == RestaurantStatus.FOUND:
            price_str = f"{self.menu_item.price:.0f} " if self.menu_item.price else "цена не указана"
            lines.append(f"   {self.menu_item.name} — {price_str}")
            if self.menu_url:
                lines.append(f"   {self.menu_url}")
        elif self.status == RestaurantStatus.FOUND_NO_PRICE:
            lines.append(f"   {self.menu_item.name} — цена не указана")
            if self.menu_url:
                lines.append(f"   {self.menu_url}")
        elif self.status == RestaurantStatus.MENU_UNAVAILABLE:
            lines.append("   Меню недоступно онлайн")
            if self.restaurant.website:
                lines.append(f"   Сайт: {self.restaurant.website}")
        elif self.status == RestaurantStatus.SITE_NOT_FOUND:
            lines.append("   Сайт ресторана не найден")
        
        return "\n".join(lines)


class SearchRequest(BaseModel):
    """User search request."""
    dish_name: str
    location: str
    radius_meters: int = Field(default=1000)
    
    # Resolved coordinates
    lat: Optional[float] = None
    lon: Optional[float] = None
