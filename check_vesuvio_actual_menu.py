import asyncio
from playwright.async_api import async_playwright

async def check_actual_menu():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})
        
        # Check one of the actual menu pages
        menu_url = 'https://vesuviopizza.ru/poklonnaya-menu'
        print(f"Checking: {menu_url}")
        
        await page.goto(menu_url, timeout=30000, wait_until='networkidle')
        await page.wait_for_timeout(2000)
        
        # Get text
        text = await page.inner_text('body')
        with open('vesuvio_actual_menu.txt', 'w', encoding='utf-8') as f:
            f.write(text)
        print(f"Saved menu text ({len(text)} chars)")
        
        # Check for specific dishes
        dishes = ['маргарита', 'карбонара', 'пепперони', 'салат', 'суп', 'паста', 'цезарь']
        print("\nSearching for dishes:")
        for dish in dishes:
            if dish.lower() in text.lower():
                print(f"  {dish}: FOUND")
                # Find context
                idx = text.lower().find(dish.lower())
                context = text[max(0,idx-20):idx+100]
                print(f"    Context: {context[:80]}...")
            else:
                print(f"  {dish}: NOT FOUND")
        
        # Screenshot
        await page.screenshot(path='vesuvio_actual_menu.png', full_page=True)
        print("\nScreenshot saved")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(check_actual_menu())
