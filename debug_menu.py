# -*- coding: utf-8 -*-
"""Debug menu content to understand matching issues."""
import asyncio
import re
from services.menu_parser import menu_parser
from utils.text_utils import normalize_for_search


async def check():
    url = "https://otello.ru/"
    menu_text = await menu_parser.get_menu_text(url)
    
    if not menu_text:
        print("No menu text found")
        return
    
    normalized = normalize_for_search(menu_text)
    
    print("=== Menu text (first 2000 chars) ===")
    print(normalized[:2000])
    print()
    print("=== Word presence check ===")
    
    words_to_check = [
        "суп",
        "куриный",
        "курин",
        "курица",
        "куриный суп",
        "борщ",
        "салат",
    ]
    
    for word in words_to_check:
        present = word in normalized
        print(f"'{word}': {present}")
    
    print()
    print("=== Context around 'суп' ===")
    for m in re.finditer(r"суп\w*", normalized):
        start = max(0, m.start() - 50)
        end = min(len(normalized), m.end() + 50)
        print(f"Position {m.start()}: ...{normalized[start:end]}...")


if __name__ == "__main__":
    asyncio.run(check())
