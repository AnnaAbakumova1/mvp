# -*- coding: utf-8 -*-
"""Test image OCR on Vesuvio menu."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()


async def test_vesuvio_ocr():
    print("="*60)
    print("TEST: Image OCR on Vesuvio menu")
    print("="*60)
    
    from services.image_ocr import image_ocr_service
    from utils.text_utils import find_dish_in_text, extract_price
    
    url = "https://vesuviopizza.ru/"
    dish = "американо"
    
    print(f"URL: {url}")
    print(f"Dish: {dish}")
    
    # Test OCR
    print("\n[1] Running image OCR...")
    result = await image_ocr_service.extract_text_from_page_images(url)
    
    print(f"\nOCR Result:")
    print(f"  Success: {result.success}")
    print(f"  Images processed: {result.images_processed}")
    print(f"  Text length: {len(result.text)}")
    
    if result.error:
        print(f"  Error: {result.error}")
    
    if result.text:
        print(f"\n[2] Extracted text (first 1500 chars):")
        print("-"*40)
        print(result.text[:1500])
        print("-"*40)
        
        # Search for dish
        print(f"\n[3] Searching for '{dish}'...")
        pos = find_dish_in_text(dish, result.text)
        
        if pos is not None:
            print(f"  [FOUND] at position {pos}")
            price, price_raw = extract_price(result.text, pos)
            print(f"  Price: {price} ({price_raw})")
            
            # Show context
            start = max(0, pos - 30)
            end = min(len(result.text), pos + 100)
            print(f"  Context: ...{result.text[start:end]}...")
        else:
            print(f"  [NOT FOUND]")
            
            # Check what coffee items are in text
            coffee_words = ["кофе", "coffee", "американо", "капучино", "латте", "эспрессо"]
            print(f"\n[4] Checking for coffee words:")
            for word in coffee_words:
                if word in result.text.lower():
                    idx = result.text.lower().find(word)
                    context = result.text[max(0,idx-20):idx+50]
                    print(f"  '{word}' found: ...{context}...")
    
    # Cleanup
    try:
        from services.browser_service import close_browser
        await close_browser()
    except:
        pass
    
    print("\n" + "="*60)
    print("TEST COMPLETED")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(test_vesuvio_ocr())
