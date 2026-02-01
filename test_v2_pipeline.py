# -*- coding: utf-8 -*-
"""
Full pipeline test with V2 services.

Tests:
- Geocoding: мукомольный проезд 2
- Restaurant search via 2GIS
- Menu parsing with PDF + browser fallback
- Dish search: куриный суп, зеленый салат
"""
import asyncio
import logging
import sys
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

load_dotenv()


async def test_geocoding():
    """Test geocoding the address."""
    print("\n" + "="*60)
    print("TEST 1: Geocoding")
    print("="*60)
    
    from services.geo import geo_service
    
    address = "мукомольный проезд 2"
    print(f"Address: {address}")
    
    coords = await geo_service.geocode(address)
    
    if coords:
        lat, lon = coords
        print(f"[OK] Coordinates: lat={lat}, lon={lon}")
        return coords
    else:
        print("[FAIL] Geocoding failed")
        return None


async def test_restaurant_search(lat: float, lon: float):
    """Test restaurant search."""
    print("\n" + "="*60)
    print("TEST 2: Restaurant Search")
    print("="*60)
    
    from services.geo import geo_service
    
    print(f"Searching near: ({lat}, {lon})")
    print(f"Radius: 500m")
    
    restaurants = await geo_service.search_restaurants(lat, lon, radius_meters=500)
    
    print(f"\nFound {len(restaurants)} restaurants:")
    for i, r in enumerate(restaurants[:10], 1):
        print(f"  {i}. {r.name} - {r.address}")
    
    if len(restaurants) > 10:
        print(f"  ... and {len(restaurants) - 10} more")
    
    return restaurants


async def test_site_finder(restaurants):
    """Test website finder."""
    print("\n" + "="*60)
    print("TEST 3: Website Finder")
    print("="*60)
    
    from services.site_finder import site_finder
    
    results = []
    
    for r in restaurants[:5]:  # Test first 5
        print(f"\n{r.name}:")
        website = await site_finder.find_website(r)
        
        if website:
            print(f"  [OK] Website: {website}")
            results.append((r, website))
        else:
            print(f"  [--] No website found")
    
    return results


async def test_menu_parser_v2(website: str, dish: str):
    """Test V2 menu parser with all features."""
    print(f"\n--- Testing menu parser V2 ---")
    print(f"URL: {website}")
    print(f"Dish: {dish}")
    
    from services.menu_parser_v2 import menu_parser_v2
    
    result = await menu_parser_v2.find_and_parse_menu(
        website_url=website,
        dish_name=dish,
        use_browser_fallback=True,
        timeout=30
    )
    
    print(f"\nResult:")
    print(f"  Success: {result.success}")
    print(f"  Menu URL: {result.menu_url}")
    print(f"  Source: {result.source}")
    print(f"  Text length: {len(result.menu_text) if result.menu_text else 0}")
    print(f"  Dish found: {result.dish_found}")
    
    if result.dish_found:
        print(f"  Price: {result.price} ({result.price_raw})")
    
    return result


async def test_dish_matcher_v2(restaurants, dish: str):
    """Test V2 dish matcher."""
    print("\n" + "="*60)
    print(f"TEST 4: Dish Matcher V2 - '{dish}'")
    print("="*60)
    
    from services.dish_matcher_v2 import dish_matcher_v2
    from models import RestaurantStatus
    
    found_count = 0
    
    for r in restaurants[:5]:  # Test first 5
        print(f"\n{r.name}:")
        
        result = await dish_matcher_v2.search_dish(r, dish)
        
        if result.status == RestaurantStatus.FOUND:
            print(f"  [FOUND] {result.menu_item.name} - {result.menu_item.price} руб")
            print(f"  Menu: {result.menu_url}")
            print(f"  Source: {result.menu_source}")
            found_count += 1
        elif result.status == RestaurantStatus.FOUND_NO_PRICE:
            print(f"  [FOUND] {result.menu_item.name} - цена не указана")
            print(f"  Menu: {result.menu_url}")
            found_count += 1
        elif result.status == RestaurantStatus.SITE_NOT_FOUND:
            print(f"  [--] No website")
        elif result.status == RestaurantStatus.MENU_UNAVAILABLE:
            print(f"  [--] Menu unavailable: {result.error_message}")
        else:
            print(f"  [--] Status: {result.status}")
    
    print(f"\n[SUMMARY] Found '{dish}' in {found_count}/{min(5, len(restaurants))} restaurants")
    return found_count


async def test_pdf_parser():
    """Test PDF parser."""
    print("\n" + "="*60)
    print("TEST 5: PDF Parser")
    print("="*60)
    
    from services.pdf_parser import pdf_parser
    
    # Test with a known PDF menu (if available)
    test_pdf_url = None  # Add a test PDF URL if available
    
    if test_pdf_url:
        print(f"Testing PDF: {test_pdf_url}")
        text = await pdf_parser.extract_text_from_url(test_pdf_url)
        
        if text:
            print(f"[OK] Extracted {len(text)} chars")
            print(f"First 200 chars: {text[:200]}...")
        else:
            print("[FAIL] Could not extract text")
    else:
        print("[SKIP] No test PDF URL configured")
        
        # Test PDF detection
        test_urls = [
            "https://example.com/menu.pdf",
            "https://example.com/food",
            "https://example.com/download?format=pdf",
        ]
        
        print("\nPDF URL detection:")
        for url in test_urls:
            is_pdf = pdf_parser.is_pdf_url(url)
            print(f"  {url}: {is_pdf}")


async def test_browser_service():
    """Test browser service."""
    print("\n" + "="*60)
    print("TEST 6: Browser Service")
    print("="*60)
    
    from services.browser_service import render_js_page
    
    test_url = "https://muumsk.ru/"
    print(f"Testing: {test_url}")
    
    result = await render_js_page(test_url, timeout=20000)
    
    print(f"\nResult:")
    print(f"  Success: {result.success}")
    print(f"  Final URL: {result.url}")
    print(f"  HTML length: {len(result.html)}")
    print(f"  Text length: {len(result.text)}")
    
    if result.error:
        print(f"  Error: {result.error}")
    
    return result


async def test_cache():
    """Test cache service."""
    print("\n" + "="*60)
    print("TEST 7: Cache Service")
    print("="*60)
    
    from services.cache import menu_cache
    
    test_url = "https://test.example.com/menu"
    test_text = "Test menu content: Салат Цезарь - 450 руб"
    
    # Test set
    print(f"Setting cache for: {test_url}")
    await menu_cache.set_menu_text(test_url, test_text)
    print("[OK] Cache set")
    
    # Test get
    cached = await menu_cache.get_menu_text(test_url)
    if cached == test_text:
        print("[OK] Cache retrieved correctly")
    else:
        print(f"[FAIL] Cache mismatch: {cached}")
    
    # Cleanup
    backend = await menu_cache._get_backend()
    await backend.delete(menu_cache._make_key("text", test_url))
    print("[OK] Cache cleaned up")


async def main():
    """Run all tests."""
    print("="*60)
    print("FULL PIPELINE TEST (V2 SERVICES)")
    print("="*60)
    print("Address: мукомольный проезд 2")
    print("Dishes: куриный суп, зеленый салат")
    print("="*60)
    
    # Test 1: Geocoding
    coords = await test_geocoding()
    if not coords:
        print("\n[ABORT] Cannot continue without coordinates")
        return
    
    lat, lon = coords
    
    # Test 2: Restaurant search
    restaurants = await test_restaurant_search(lat, lon)
    if not restaurants:
        print("\n[ABORT] No restaurants found")
        return
    
    # Test 3: Website finder
    await test_site_finder(restaurants)
    
    # Test 4a: Dish matcher - куриный суп
    await test_dish_matcher_v2(restaurants, "куриный суп")
    
    # Test 4b: Dish matcher - зеленый салат
    await test_dish_matcher_v2(restaurants, "зеленый салат")
    
    # Test 5: PDF parser
    await test_pdf_parser()
    
    # Test 6: Browser service
    try:
        await test_browser_service()
    except Exception as e:
        print(f"[SKIP] Browser test failed: {e}")
    
    # Test 7: Cache
    await test_cache()
    
    # Cleanup
    print("\n" + "="*60)
    print("CLEANUP")
    print("="*60)
    
    try:
        from services.browser_service import close_browser
        await close_browser()
        print("[OK] Browser closed")
    except Exception as e:
        print(f"[--] Browser cleanup: {e}")
    
    print("\n" + "="*60)
    print("ALL TESTS COMPLETED")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
