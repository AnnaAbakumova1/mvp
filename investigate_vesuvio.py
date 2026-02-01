import asyncio
from playwright.async_api import async_playwright

async def investigate_vesuvio():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})
        
        # Load main page
        await page.goto('https://vesuviopizza.ru/', timeout=30000, wait_until='networkidle')
        await page.wait_for_timeout(2000)
        
        # Save text to file for proper encoding
        main_text = await page.inner_text('body')
        with open('vesuvio_main.txt', 'w', encoding='utf-8') as f:
            f.write(main_text)
        print(f"Main page text saved ({len(main_text)} chars)")
        
        # Check for menu words
        menu_words = ['пицца', 'паста', 'салат', 'суп', 'маргарита', 'карбонара', 'руб', 'цена']
        print("\nMenu words on main page:")
        for word in menu_words:
            found = word.lower() in main_text.lower()
            print(f"  {word}: {'FOUND' if found else 'NOT FOUND'}")
        
        # Now navigate to #menu
        print("\nNavigating to #menu...")
        await page.goto('https://vesuviopizza.ru/#menu', timeout=30000, wait_until='networkidle')
        await page.wait_for_timeout(2000)
        
        # Get text after navigating to #menu
        menu_text = await page.inner_text('body')
        with open('vesuvio_menu.txt', 'w', encoding='utf-8') as f:
            f.write(menu_text)
        print(f"Menu page text saved ({len(menu_text)} chars)")
        
        # Check menu words again
        print("\nMenu words after #menu navigation:")
        for word in menu_words:
            found = word.lower() in menu_text.lower()
            print(f"  {word}: {'FOUND' if found else 'NOT FOUND'}")
        
        # Take screenshot
        await page.screenshot(path='vesuvio_menu.png', full_page=True)
        print("\nScreenshot saved")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(investigate_vesuvio())
