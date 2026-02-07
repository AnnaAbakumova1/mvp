#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quick test: Find "Зеленый салат" near "мукомольный проезд 2"

Run: python run_search.py
"""
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()


async def main():
    print("="*60)
    print("ПОИСК: Зеленый салат")
    print("АДРЕС: мукомольный проезд 2")
    print("="*60)
    
    # Import services
    from services.geo import geo_service
    from services.site_finder import site_finder
    from services.menu_parser_v2 import menu_parser_v2
    from utils.text_utils import find_dish_in_text, extract_price
    
    dish = "зеленый салат"
    address = "мукомольный проезд 2"
    
    # Step 1: Geocode
    print(f"\n[1] Геокодирование: {address}")
    coords = await geo_service.geocode(address)
    
    if not coords:
        print("ОШИБКА: Не удалось найти адрес")
        return
    
    lat, lon = coords
    print(f"    Координаты: {lat}, {lon}")
    
    # Step 2: Find restaurants
    print(f"\n[2] Поиск ресторанов в радиусе 500м...")
    restaurants = await geo_service.search_restaurants(lat, lon, radius_meters=500)
    print(f"    Найдено: {len(restaurants)} ресторанов")
    
    # Step 3: Search for dish
    print(f"\n[3] Поиск блюда '{dish}'...")
    print("-"*60)
    
    found_results = []
    
    for r in restaurants[:10]:  # Check first 10
        print(f"\n>>> {r.name}")
        
        # Find website
        website = await site_finder.find_website(r)
        if not website:
            print("    Сайт не найден")
            continue
        
        print(f"    Сайт: {website}")
        
        # Parse menu
        result = await menu_parser_v2.find_and_parse_menu(
            website_url=website,
            dish_name=dish,
            use_browser_fallback=True,
            timeout=25
        )
        
        if result.dish_found:
            price_str = f"{result.price:.0f} ₽" if result.price else "цена не указана"
            print(f"    ✓ НАЙДЕНО! {dish} — {price_str}")
            print(f"    Меню: {result.menu_url}")
            found_results.append({
                "name": r.name,
                "dish": dish,
                "price": result.price,
                "menu_url": result.menu_url,
                "source": result.source.value if result.source else "unknown"
            })
        else:
            print(f"    ✗ Блюдо не найдено")
            if result.menu_text:
                # Check for any salad
                text_lower = result.menu_text.lower()
                if "салат" in text_lower:
                    print(f"    (в меню есть другие салаты)")
    
    # Summary
    print("\n" + "="*60)
    print("РЕЗУЛЬТАТ")
    print("="*60)
    
    if found_results:
        print(f"\nНайдено '{dish}' в {len(found_results)} ресторанах:\n")
        for i, r in enumerate(found_results, 1):
            price_str = f"{r['price']:.0f} ₽" if r['price'] else "цена не указана"
            print(f"{i}. {r['name']}")
            print(f"   {r['dish']} — {price_str}")
            print(f"   🔗 {r['menu_url']}")
            print()
    else:
        print(f"\nБлюдо '{dish}' не найдено в ресторанах рядом с '{address}'")
        print("\nПопробуйте:")
        print("  - Изменить название блюда (например: 'салат', 'микс салат')")
        print("  - Увеличить радиус поиска")
    
    # Cleanup
    try:
        from services.browser_service import close_browser
        await close_browser()
    except:
        pass


if __name__ == "__main__":
    asyncio.run(main())
