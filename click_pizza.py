import asyncio
import sys
import io
from playwright.async_api import async_playwright

# Fix encoding for Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

async def click_pizza_section():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})
        
        menu_url = 'https://vesuviopizza.ru/poklonnaya-menu'
        await page.goto(menu_url, timeout=30000, wait_until='networkidle')
        await page.wait_for_timeout(3000)
        
        # Find all clickable elements with "Пицца"
        print("=== Looking for Pizza links ===")
        
        links = await page.query_selector_all('a')
        for link in links:
            text = await link.inner_text()
            href = await link.get_attribute('href')
            if 'пицц' in text.lower():
                print(f"Found pizza link -> {href}")
                
                # Click this link
                await link.click()
                await page.wait_for_timeout(3000)
                
                new_url = page.url
                print(f"New URL: {new_url}")
                
                new_text = await page.inner_text('body')
                print(f"New page text length: {len(new_text)}")
                
                with open('vesuvio_pizza_page.txt', 'w', encoding='utf-8') as f:
                    f.write(new_text)
                
                await page.screenshot(path='vesuvio_pizza_page.png', full_page=True)
                print("Screenshot saved")
                
                dishes = ['маргарита', 'пепперони', 'карбонара', '4 сыра']
                print("\nSearching for dishes:")
                for dish in dishes:
                    if dish.lower() in new_text.lower():
                        print(f"  {dish}: FOUND!")
                    else:
                        print(f"  {dish}: not found")
                
                break
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(click_pizza_section())
