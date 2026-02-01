# -*- coding: utf-8 -*-
"""Check coffeemania menu for chicken soup"""
import asyncio
import aiohttp


async def check_menu():
    url = "https://coffeemania.ru/"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                print(f"Status: {resp.status}")
                text = await resp.text()
                print(f"Content length: {len(text)}")
                
                # Check for soup
                text_lower = text.lower()
                has_soup = "суп" in text_lower
                has_chicken_soup = "куриный суп" in text_lower
                has_chicken = "куриный" in text_lower or "курица" in text_lower
                
                print(f"Contains 'sup': {has_soup}")
                print(f"Contains 'kuriniy sup': {has_chicken_soup}")
                print(f"Contains 'kuriniy/kurica': {has_chicken}")
                
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(check_menu())
