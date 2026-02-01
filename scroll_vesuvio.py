import asyncio
from playwright.async_api import async_playwright

async def scroll_and_capture():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})
        
        menu_url = 'https://vesuviopizza.ru/poklonnaya-menu'
        await page.goto(menu_url, timeout=30000, wait_until='networkidle')
        await page.wait_for_timeout(3000)
        
        # Get page height
        height = await page.evaluate('document.body.scrollHeight')
        print(f"Page height: {height}px")
        
        # Scroll down gradually and capture text
        all_text = ""
        for scroll_y in range(0, min(height, 5000), 500):
            await page.evaluate(f'window.scrollTo(0, {scroll_y})')
            await page.wait_for_timeout(500)
            
            text = await page.inner_text('body')
            if len(text) > len(all_text):
                all_text = text
                print(f"At scroll {scroll_y}: text length = {len(text)}")
        
        # Save final text
        with open('vesuvio_scrolled.txt', 'w', encoding='utf-8') as f:
            f.write(all_text)
        print(f"\nFinal text length: {len(all_text)}")
        
        # Search for dishes
        dishes = ['маргарита', 'пепперони', 'карбонара', '4 сыра', 'капрезе']
        print("\nSearching for dishes:")
        for dish in dishes:
            if dish.lower() in all_text.lower():
                print(f"  {dish}: FOUND")
            else:
                print(f"  {dish}: NOT FOUND")
        
        # Now try clicking on "Пицца" button to see if it loads content
        print("\n=== Trying to click on Pizza button ===")
        try:
            pizza_btn = page.get_by_text("Пицца", exact=False)
            if await pizza_btn.count() > 0:
                await pizza_btn.first.click()
                await page.wait_for_timeout(2000)
                
                text_after_click = await page.inner_text('body')
                print(f"Text after clicking Pizza: {len(text_after_click)} chars")
                
                if 'маргарита' in text_after_click.lower():
                    print(">>> маргарита FOUND after click!")
                    with open('vesuvio_after_pizza_click.txt', 'w', encoding='utf-8') as f:
                        f.write(text_after_click)
        except Exception as e:
            print(f"Error clicking: {e}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(scroll_and_capture())
