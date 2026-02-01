# -*- coding: utf-8 -*-
"""
Test agent on real restaurants with known data:
- Muu (muumsk.ru) - SHOULD find "куриный суп"
- Picco Ristorante (picco.rest) - should NOT find "куриный суп"
"""
import asyncio
import logging
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()


async def test_restaurant(name: str, url: str, dish: str, expected_found: bool):
    """Test a restaurant and check if result matches expectation."""
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"URL: {url}")
    print(f"Dish: {dish}")
    print(f"Expected: {'FOUND' if expected_found else 'NOT FOUND'}")
    print("="*60)
    
    from services.agent_menu_finder import menu_finder_agent, AgentStatus
    
    result = await menu_finder_agent.find_menu_and_dish(
        site_url=url,
        dish=dish,
        timeout=45,
        max_steps=7
    )
    
    print(f"\nResult:")
    print(f"  Status: {result.status}")
    print(f"  Found: {result.found}")
    print(f"  Menu URL: {result.menu_url}")
    if result.dish_fragment:
        print(f"  Fragment: {result.dish_fragment[:200]}...")
    
    # Check expectation
    actual_found = result.found or result.status == AgentStatus.FOUND
    
    if actual_found == expected_found:
        print(f"\n[PASS] Result matches expectation!")
        return True
    else:
        print(f"\n[FAIL] Expected {'FOUND' if expected_found else 'NOT FOUND'}, got {'FOUND' if actual_found else 'NOT FOUND'}")
        return False


async def main():
    """Run tests on real restaurants."""
    print("="*60)
    print("AGENT REAL RESTAURANT TESTS")
    print("="*60)
    
    dish = "куриный суп"
    
    test_cases = [
        # (name, url, dish, expected_found)
        ("Muu Steakhouse", "https://muumsk.ru/", dish, True),
        ("Niyama Sushi", "https://niyama.ru/", dish, False),  # Sushi - no chicken soup
    ]
    
    results = []
    
    for name, url, dish, expected in test_cases:
        try:
            passed = await test_restaurant(name, url, dish, expected)
            results.append((name, passed))
        except Exception as e:
            print(f"\n[ERROR] {name}: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status} {name}")
    
    passed_count = sum(1 for _, p in results if p)
    print(f"\nTotal: {passed_count}/{len(results)} tests passed")


if __name__ == "__main__":
    asyncio.run(main())
