# -*- coding: utf-8 -*-
"""
Final test: Hybrid pipeline (static parser + agent fallback)
Tests:
- Muu: SHOULD find "куриный суп"
- Picco: should NOT find "куриный суп"
"""
import asyncio
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()


async def test_find_dish(name: str, url: str, dish: str, expected_found: bool):
    """
    Test finding dish using the hybrid pipeline.
    Uses menu_parser which automatically falls back to agent if static fails.
    """
    from services.menu_parser import menu_parser
    from utils.text_utils import find_dish_in_text, extract_price
    
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"URL: {url}")
    print(f"Dish: {dish}")
    print(f"Expected: {'FOUND' if expected_found else 'NOT FOUND'}")
    print("="*60)
    
    # Step 1: Find menu URL (uses static parser, then agent fallback)
    print("\n[1] Finding menu...")
    menu_url = await menu_parser.find_menu_url(url, dish)
    
    if not menu_url:
        print("[FAIL] Could not find menu")
        return not expected_found  # Pass if we expected NOT_FOUND
    
    print(f"[OK] Menu: {menu_url}")
    
    # Step 2: Get menu text
    print("\n[2] Loading menu text...")
    menu_text = await menu_parser.get_menu_text(menu_url)
    
    if not menu_text:
        print("[FAIL] Could not load menu text")
        return not expected_found
    
    print(f"[OK] Text length: {len(menu_text)} chars")
    
    # Step 3: Search for dish
    print("\n[3] Searching for dish...")
    pos = find_dish_in_text(dish, menu_text)
    
    if pos is not None:
        print(f"[FOUND] Dish at position {pos}")
        price, price_raw = extract_price(menu_text, pos)
        if price:
            print(f"[OK] Price: {price} ({price_raw})")
        else:
            print("[INFO] Price not found")
        
        result = True
    else:
        print(f"[NOT FOUND] Dish not in menu")
        result = False
    
    # Check expectation
    if result == expected_found:
        print(f"\n[PASS] Result matches expectation!")
        return True
    else:
        print(f"\n[FAIL] Expected {'FOUND' if expected_found else 'NOT FOUND'}, got {'FOUND' if result else 'NOT FOUND'}")
        return False


async def main():
    """Run all tests."""
    print("="*60)
    print("HYBRID PIPELINE FINAL TESTS")
    print("="*60)
    
    dish = "куриный суп"
    
    test_cases = [
        # (name, url, dish, expected_found)
        ("Muu Steakhouse", "https://muumsk.ru/", dish, True),
        ("Picco Ristorante", "https://picco.rest/", dish, False),
    ]
    
    results = []
    
    for name, url, dish, expected in test_cases:
        try:
            passed = await test_find_dish(name, url, dish, expected)
            results.append((name, passed))
        except Exception as e:
            logger.error(f"Error testing {name}: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status} {name}")
    
    passed_count = sum(1 for _, p in results if p)
    total = len(results)
    
    print(f"\nTotal: {passed_count}/{total} tests passed")
    
    if passed_count == total:
        print("\nALL TESTS PASSED!")
    else:
        print("\nSOME TESTS FAILED!")


if __name__ == "__main__":
    asyncio.run(main())
