# -*- coding: utf-8 -*-
"""Debug what agent sees on Picco website"""
import asyncio
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
load_dotenv()


async def debug_picco():
    """Debug what the agent sees on picco.rest"""
    from playwright.async_api import async_playwright
    
    print("Starting browser...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = await context.new_page()
        
        # Block images for faster load
        await page.route("**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf}", 
                        lambda route: route.abort())
        
        print("Loading picco.rest...")
        try:
            await page.goto("https://picco.rest/", wait_until='commit', timeout=30000)
        except Exception as e:
            print(f"Load error: {e}")
            await browser.close()
            return
        
        # Wait for body to exist
        print("Waiting for page to render...")
        try:
            await page.wait_for_selector('body', timeout=10000)
            await asyncio.sleep(3)
        except Exception as e:
            print(f"Wait error: {e}")
        
        # Get page text
        text = await page.evaluate('() => (document.body && document.body.innerText) || ""')
        print(f"\nPage text length: {len(text)}")
        print(f"First 1000 chars:\n{text[:1000]}")
        
        # Get links
        links = await page.evaluate('''() => {
            const links = [];
            document.querySelectorAll('a[href]').forEach(a => {
                const text = (a.innerText || a.textContent || '').trim();
                const href = a.href;
                if (text && text.length < 100 && href && !href.startsWith('javascript:')) {
                    links.push({text: text, href: href});
                }
            });
            return links;
        }''')
        
        print(f"\nFound {len(links)} links:")
        for i, link in enumerate(links[:30]):
            print(f"  {i+1}. '{link['text']}' -> {link['href']}")
        
        # Check for menu indicators
        text_lower = text.lower()
        indicators = ["меню", "menu", "блюда", "dishes", "кухня", "суп", "салат", "цена", "руб", "₽"]
        print(f"\nMenu indicators found:")
        for ind in indicators:
            present = ind in text_lower
            print(f"  '{ind}': {present}")
        
        # Check for chicken soup
        print(f"\n'куриный суп' in text: {'куриный суп' in text_lower}")
        print(f"'куриный' in text: {'куриный' in text_lower}")
        print(f"'суп' in text: {'суп' in text_lower}")
        
        await browser.close()
        print("\nDone!")


if __name__ == "__main__":
    asyncio.run(debug_picco())
