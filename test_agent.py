"""
Test for browser-based menu finder agent.
Tests the full pipeline: static parser -> agent fallback.
"""
import asyncio
import logging
import os
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()


async def test_static_parser():
    """Test static menu parser."""
    print("\n" + "="*60)
    print("TEST 1: Static Menu Parser")
    print("="*60)
    
    from services.menu_parser import menu_parser
    
    test_url = "https://otello.ru/"
    dish = "куриный суп"
    
    print(f"URL: {test_url}")
    print(f"Dish: {dish}")
    
    # Test find_menu_url
    menu_url = await menu_parser.find_menu_url(test_url, dish)
    
    if menu_url:
        print(f"[OK] Menu found: {menu_url}")
        
        # Test get_menu_text
        menu_text = await menu_parser.get_menu_text(menu_url)
        if menu_text:
            print(f"[OK] Menu text loaded: {len(menu_text)} chars")
            # Skip printing raw text due to encoding issues
            
            # Search for dish
            from utils.text_utils import find_dish_in_text, extract_price
            
            pos = find_dish_in_text(dish, menu_text)
            if pos is not None:
                print(f"[OK] Dish found at position: {pos}")
                price, price_raw = extract_price(menu_text, pos)
                print(f"[OK] Price: {price} ({price_raw})")
            else:
                print(f"[FAIL] Dish not found in menu text")
        else:
            print("[FAIL] Could not load menu text")
    else:
        print("[FAIL] Menu not found by static parser")
    
    return menu_url


async def test_agent_directly():
    """Test agent directly."""
    print("\n" + "="*60)
    print("TEST 2: Agent Direct Test")
    print("="*60)
    
    from config import settings
    
    print(f"Agent enabled: {settings.agent_enabled}")
    print(f"Groq API key: {settings.groq_api_key[:20]}..." if settings.groq_api_key else "No key")
    
    if not settings.agent_enabled:
        print("[SKIP] Agent is disabled")
        return None
    
    from services.agent_menu_finder import menu_finder_agent, AgentStatus
    
    test_url = "https://otello.ru/"
    dish = "куриный суп"
    
    print(f"URL: {test_url}")
    print(f"Dish: {dish}")
    print("Starting agent...")
    
    result = await menu_finder_agent.find_menu_and_dish(
        site_url=test_url,
        dish=dish,
        timeout=30,
        max_steps=5
    )
    
    print(f"\nAgent Result:")
    print(f"  Status: {result.status}")
    print(f"  Found: {result.found}")
    print(f"  Menu URL: {result.menu_url}")
    print(f"  Dish fragment: {result.dish_fragment[:200] if result.dish_fragment else None}...")
    
    if result.status == AgentStatus.FOUND:
        print("[OK] Agent found the dish!")
    elif result.status == AgentStatus.NOT_FOUND:
        print("[INFO] Agent found menu but dish not present")
    elif result.status == AgentStatus.MENU_NOT_FOUND:
        print("[FAIL] Agent could not find menu")
    elif result.status == AgentStatus.TIMEOUT:
        print("[FAIL] Agent timed out")
    else:
        print(f"[FAIL] Agent error: {result.status}")
    
    return result


async def test_groq_api():
    """Test Groq API directly."""
    print("\n" + "="*60)
    print("TEST 3: Groq API Connection")
    print("="*60)
    
    from config import settings
    import aiohttp
    
    if not settings.groq_api_key:
        print("[FAIL] No Groq API key configured")
        return False
    
    print(f"API Key: {settings.groq_api_key[:20]}...")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.groq_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "user", "content": "Say 'hello' in one word"}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 10
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                print(f"Response status: {resp.status}")
                
                if resp.status == 200:
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    print(f"[OK] Groq API works! Response: {content}")
                    return True
                else:
                    text = await resp.text()
                    print(f"[FAIL] Groq API error: {text}")
                    return False
                    
    except Exception as e:
        print(f"[FAIL] Groq API connection error: {e}")
        return False


async def test_full_pipeline():
    """Test full pipeline: restaurant -> website -> menu -> dish."""
    print("\n" + "="*60)
    print("TEST 4: Full Pipeline")
    print("="*60)
    
    from services.menu_parser import menu_parser
    from utils.text_utils import find_dish_in_text, extract_price
    
    test_sites = [
        "https://otello.ru/",
        "https://coffeemania.ru/",
    ]
    
    dish = "суп"
    
    for site in test_sites:
        print(f"\n--- Testing: {site} ---")
        
        # Find menu
        menu_url = await menu_parser.find_menu_url(site, dish)
        
        if not menu_url:
            print(f"  [FAIL] No menu found")
            continue
        
        print(f"  Menu URL: {menu_url}")
        
        # Get menu text
        menu_text = await menu_parser.get_menu_text(menu_url)
        
        if not menu_text:
            print(f"  [FAIL] Could not load menu text")
            continue
        
        print(f"  Menu text: {len(menu_text)} chars")
        
        # Search for dish
        pos = find_dish_in_text(dish, menu_text)
        
        if pos is not None:
            price, price_raw = extract_price(menu_text, pos)
            print(f"  [OK] Found '{dish}' at position {pos}")
            print(f"  Price: {price} ({price_raw})")
        else:
            print(f"  [INFO] Dish '{dish}' not found in menu")


async def main():
    """Run all tests."""
    print("="*60)
    print("AGENT AND MENU PARSER TESTS")
    print("="*60)
    
    # Test 1: Groq API
    await test_groq_api()
    
    # Test 2: Static parser
    await test_static_parser()
    
    # Test 3: Agent directly
    await test_agent_directly()
    
    # Test 4: Full pipeline
    await test_full_pipeline()
    
    print("\n" + "="*60)
    print("ALL TESTS COMPLETED")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
