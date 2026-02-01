# -*- coding: utf-8 -*-
"""Check Picco menu from restoran.ru"""
import asyncio
import aiohttp


async def check_menu():
    url = "https://restoran.ru/msk/detailed/restaurants/picco-ristorante/menu"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                print(f"Status: {resp.status}")
                text = await resp.text()
                print(f"Content length: {len(text)}")
                
                # Check for soup
                text_lower = text.lower()
                has_soup = "суп" in text_lower
                has_chicken_soup = "куриный суп" in text_lower
                has_chicken = "куриный" in text_lower or "курица" in text_lower
                
                print(f"Contains 'суп': {has_soup}")
                print(f"Contains 'куриный суп': {has_chicken_soup}")
                print(f"Contains 'куриный/курица': {has_chicken}")
                
                # Find soup context
                if has_soup:
                    import re
                    for m in re.finditer(r"суп\w*", text_lower):
                        start = max(0, m.start() - 50)
                        end = min(len(text_lower), m.end() + 50)
                        print(f"\nSoup context: ...{text_lower[start:end]}...")
                        
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(check_menu())
