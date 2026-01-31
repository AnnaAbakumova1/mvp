"""
2GIS API integration for restaurant search and geocoding.
"""
import logging
from typing import List, Optional, Tuple

from config import settings
from models import Restaurant
from utils.http_client import http_client

logger = logging.getLogger(__name__)

# 2GIS API endpoints
TWOGIS_GEOCODE_URL = "https://catalog.api.2gis.com/3.0/items/geocode"
TWOGIS_CATALOG_URL = "https://catalog.api.2gis.com/3.0/items"

# Restaurant rubric IDs in 2GIS
RESTAURANT_RUBRIC_IDS = [
    "164",      # Рестораны
    "165",      # Кафе
    "5819",     # Пиццерии
    "170",      # Бары
    "9439",     # Суши-бары
    "5696",     # Кофейни
]


class GeoService:
    """Service for 2GIS API interactions."""
    
    def __init__(self):
        self.api_key = settings.twogis_api_key
    
    async def geocode(self, address: str, city: str = "Москва") -> Optional[Tuple[float, float]]:
        """
        Convert address to coordinates using 2GIS Geocoder.
        
        Args:
            address: Street address or location name
            city: City name (default: Moscow)
            
        Returns:
            Tuple (lat, lon) or None if not found
        """
        query = f"{city}, {address}" if city and city.lower() not in address.lower() else address
        
        params = {
            "q": query,
            "key": self.api_key,
            "fields": "items.point",
            "type": "building,street,adm_div,attraction",
        }
        
        logger.info(f"Geocoding: {query}")
        
        data = await http_client.get_json(TWOGIS_GEOCODE_URL, params=params)
        
        if not data:
            logger.warning(f"Geocoding failed for: {query}")
            return None
        
        items = data.get("result", {}).get("items", [])
        
        if not items:
            logger.warning(f"No geocoding results for: {query}")
            return None
        
        point = items[0].get("point")
        if point:
            lat = point.get("lat")
            lon = point.get("lon")
            logger.info(f"Geocoded {query} -> ({lat}, {lon})")
            return (lat, lon)
        
        return None
    
    async def search_restaurants(
        self,
        lat: float,
        lon: float,
        radius_meters: int = None,
        limit: int = None,
    ) -> List[Restaurant]:
        """
        Search for restaurants near given coordinates.
        
        Args:
            lat: Latitude
            lon: Longitude
            radius_meters: Search radius in meters (default from settings)
            limit: Maximum number of results (default from settings)
            
        Returns:
            List of Restaurant objects
        """
        radius = radius_meters or settings.default_radius_meters
        max_results = limit or settings.max_restaurants_per_search
        
        restaurants = []
        
        # Search for each rubric type
        for rubric_id in RESTAURANT_RUBRIC_IDS:
            if len(restaurants) >= max_results:
                break
                
            params = {
                "key": self.api_key,
                "point": f"{lon},{lat}",
                "radius": radius,
                "rubric_id": rubric_id,
                "fields": "items.point,items.address",
                "page_size": min(20, max_results - len(restaurants)),
            }
            
            logger.debug(f"Searching restaurants with rubric {rubric_id}")
            
            data = await http_client.get_json(TWOGIS_CATALOG_URL, params=params)
            
            if not data:
                continue
            
            items = data.get("result", {}).get("items", [])
            
            for item in items:
                if len(restaurants) >= max_results:
                    break
                
                # Skip duplicates
                item_id = item.get("id", "")
                if any(r.id == item_id for r in restaurants):
                    continue
                
                # Extract restaurant data
                point = item.get("point", {})
                address_info = item.get("address", {})
                
                # Build address string
                address_parts = []
                if address_info.get("components"):
                    for comp in address_info["components"]:
                        if comp.get("type") in ["street_address", "street", "building"]:
                            address_parts.append(comp.get("street", ""))
                            if comp.get("number"):
                                address_parts.append(comp["number"])
                            break
                
                address = ", ".join(filter(None, address_parts)) or item.get("address_name", "")
                
                restaurant = Restaurant(
                    id=item_id,
                    name=item.get("name", "Без названия"),
                    address=address,
                    lat=point.get("lat", lat),
                    lon=point.get("lon", lon),
                    website=None,  # 2GIS API doesn't provide website
                )
                
                restaurants.append(restaurant)
        
        logger.info(f"Found {len(restaurants)} restaurants near ({lat}, {lon})")
        return restaurants


# Global service instance
geo_service = GeoService()
