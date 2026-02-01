# -*- coding: utf-8 -*-
"""Test static parser on Picco Ristorante"""
import asyncio
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
load_dotenv()


async def test_picco_static():
    """Test static parser on picco.rest"""
    from services.menu_parser import menu_parser
    from utils.text_utils import find_dish_in_text, normalize_for_search
    
    url = "https://picco.rest/"
    dish = "куриный суп"
    
    print("="*60)
    print("TEST: Picco Ristorante (Static Parser)")
    print(f"URL: {url}")
    print(f"Dish: {dish}")
    print("="*60)
    
    # Step 1: Find menu URL
    print("\n[1] Finding menu URL...")
    menu_url = await menu_parser.find_menu_url(url, dish)
    
    if not menu_url:
        print("[FAIL] Could not find menu URL")
        return
    
    print(f"[OK] Menu URL: {menu_url}")
    
    # Step 2: Get menu text
    print("\n[2] Getting menu text...")
    menu_text = await menu_parser.get_menu_text(menu_url)
    
    if not menu_text:
        print("[FAIL] Could not get menu text")
        return
    
    print(f"[OK] Menu text length: {len(menu_text)} chars")
    
    # Step 3: Search for dish
    print("\n[3] Searching for dish...")
    normalized = normalize_for_search(menu_text)
    
    # Check what's in the menu
    print(f"  'суп' in text: {'суп' in normalized}")
    print(f"  'куриный' in text: {'куриный' in normalized}")
    print(f"  'куриный суп' in text: {'куриный суп' in normalized}")
    print(f"  'пицца' in text: {'пицца' in normalized}")
    print(f"  'паста' in text: {'паста' in normalized}")
    
    pos = find_dish_in_text(dish, menu_text)
    
    if pos is not None:
        print(f"\n[FOUND] Dish found at position: {pos}")
        # Show context
        start = max(0, pos - 50)
        end = min(len(normalized), pos + 100)
        print(f"Context: ...{normalized[start:end]}...")
    else:
        print(f"\n[NOT FOUND] Dish '{dish}' not found in menu")
    
    # Show some menu sample
    print("\n[4] Menu sample (first 1000 chars):")
    print(normalized[:1000])


if __name__ == "__main__":
    asyncio.run(test_picco_static())
