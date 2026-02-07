# -*- coding: utf-8 -*-
"""
Test: зеленый салат at Picco Ristorante
Address: мукомольный проезд 2
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


async def test_picco_green_salad():
    """Test finding 'зеленый салат' at Picco Ristorante."""
    print("="*60)
    print("TEST: Зеленый салат at Picco Ristorante")
    print("="*60)
    
    from services.menu_parser_v2 import menu_parser_v2
    from utils.text_utils import find_dish_in_text, extract_price, normalize_for_search
    
    url = "https://picco.rest/"
    dish = "зеленый салат"
    
    print(f"URL: {url}")
    print(f"Dish: {dish}")
    
    # Test with V2 parser
    print("\n[1] Using menu_parser_v2...")
    result = await menu_parser_v2.find_and_parse_menu(
        website_url=url,
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
        print("\n[PASS] Зеленый салат НАЙДЕН!")
    else:
        print("\n[2] Dish not found, analyzing menu content...")
        
        if result.menu_text:
            text_lower = result.menu_text.lower()
            normalized = normalize_for_search(result.menu_text)
            
            # Check for salad-related terms
            salad_terms = [
                "салат", "salad", "зелен", "green",
                "цезарь", "caesar", "греческий", "greek",
                "овощной", "vegetable", "микс", "mix"
            ]
            
            print("\nSearching for salad-related terms:")
            for term in salad_terms:
                if term in text_lower:
                    # Find position and context
                    pos = text_lower.find(term)
                    start = max(0, pos - 30)
                    end = min(len(text_lower), pos + 50)
                    context = result.menu_text[start:end].replace('\n', ' ')
                    print(f"  '{term}' found: ...{context}...")
            
            # Try alternative dish names
            print("\n[3] Trying alternative dish names...")
            alternatives = [
                "салат",
                "зеленый",
                "green salad",
                "салат зеленый",
                "микс салат",
                "овощной салат",
            ]
            
            for alt in alternatives:
                pos = find_dish_in_text(alt, result.menu_text)
                if pos is not None:
                    price, price_raw = extract_price(result.menu_text, pos)
                    print(f"  '{alt}' FOUND at pos {pos}, price: {price}")
                    
                    # Show context
                    start = max(0, pos - 20)
                    end = min(len(result.menu_text), pos + 80)
                    context = result.menu_text[start:end].replace('\n', ' ')
                    print(f"    Context: {context}")
        else:
            print("  No menu text available")
    
    return result


async def test_full_pipeline_picco():
    """Test full pipeline for Picco."""
    print("\n" + "="*60)
    print("TEST: Full Pipeline - Picco Ristorante")
    print("="*60)
    
    from services.geo import geo_service
    from services.site_finder import site_finder
    from services.dish_matcher_v2 import dish_matcher_v2
    from models import Restaurant, RestaurantStatus
    
    # Step 1: Geocode address
    print("\n[1] Geocoding 'мукомольный проезд 2'...")
    coords = await geo_service.geocode("мукомольный проезд 2")
    
    if not coords:
        print("[FAIL] Geocoding failed")
        return
    
    lat, lon = coords
    print(f"[OK] Coordinates: {lat}, {lon}")
    
    # Step 2: Search restaurants
    print("\n[2] Searching restaurants...")
    restaurants = await geo_service.search_restaurants(lat, lon, radius_meters=500)
    print(f"[OK] Found {len(restaurants)} restaurants")
    
    # Step 3: Find Picco
    print("\n[3] Looking for Picco Ristorante...")
    picco = None
    for r in restaurants:
        if "picco" in r.name.lower() or "пикко" in r.name.lower():
            picco = r
            print(f"[OK] Found: {r.name} - {r.address}")
            break
    
    if not picco:
        print("[INFO] Picco not found in 2GIS results, using direct URL")
        picco = Restaurant(
            id="picco_direct",
            name="Picco Ristorante",
            address="Мукомольный проезд, 2",
            lat=lat,
            lon=lon,
            website="https://picco.rest/"
        )
    
    # Step 4: Search for dish
    print("\n[4] Searching for 'зеленый салат'...")
    result = await dish_matcher_v2.search_dish(picco, "зеленый салат")
    
    print(f"\nResult:")
    print(f"  Status: {result.status}")
    print(f"  Menu URL: {result.menu_url}")
    print(f"  Source: {result.menu_source}")
    
    if result.status == RestaurantStatus.FOUND:
        print(f"  [FOUND] {result.menu_item.name} - {result.menu_item.price} руб")
    elif result.status == RestaurantStatus.FOUND_NO_PRICE:
        print(f"  [FOUND] {result.menu_item.name} - цена не указана")
    else:
        print(f"  [NOT FOUND] {result.error_message}")
    
    return result


async def analyze_picco_menu():
    """Analyze Picco menu content in detail."""
    print("\n" + "="*60)
    print("ANALYSIS: Picco Menu Content")
    print("="*60)
    
    from services.menu_parser_v2 import menu_parser_v2
    from services.browser_service import render_js_page
    
    url = "https://picco.rest/"
    
    # Try static first
    print("\n[1] Static parse...")
    result = await menu_parser_v2.find_and_parse_menu(
        website_url=url,
        dish_name="",  # No dish, just get menu
        use_browser_fallback=False,
        timeout=20
    )
    
    if result.success and result.menu_text:
        print(f"Static: {len(result.menu_text)} chars from {result.menu_url}")
    else:
        print("Static: Failed or no content")
    
    # Try browser
    print("\n[2] Browser render...")
    browser_result = await render_js_page(url, timeout=25000)
    
    if browser_result.success:
        print(f"Browser: {len(browser_result.text)} chars")
        
        # Look for menu sections
        text_lower = browser_result.text.lower()
        
        sections = ["салат", "закуск", "antipasti", "insalata", "горяч", "пицца", "паста"]
        print("\nMenu sections found:")
        for section in sections:
            count = text_lower.count(section)
            if count > 0:
                print(f"  '{section}': {count} occurrences")
        
        # Print salad section if found
        if "салат" in text_lower:
            print("\n[3] Salad mentions in menu:")
            idx = 0
            for _ in range(5):  # Show up to 5 occurrences
                pos = text_lower.find("салат", idx)
                if pos == -1:
                    break
                start = max(0, pos - 30)
                end = min(len(browser_result.text), pos + 70)
                context = browser_result.text[start:end].replace('\n', ' ').strip()
                print(f"  ...{context}...")
                idx = pos + 1
    else:
        print(f"Browser: Failed - {browser_result.error}")
    
    # Cleanup
    try:
        from services.browser_service import close_browser
        await close_browser()
    except:
        pass


async def main():
    """Run all Picco tests."""
    print("="*60)
    print("PICCO RISTORANTE - ЗЕЛЕНЫЙ САЛАТ TEST")
    print("="*60)
    
    # Test 1: Direct menu parsing
    await test_picco_green_salad()
    
    # Test 2: Full pipeline
    await test_full_pipeline_picco()
    
    # Test 3: Detailed analysis
    await analyze_picco_menu()
    
    print("\n" + "="*60)
    print("TESTS COMPLETED")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
