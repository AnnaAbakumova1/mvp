import asyncio
from playwright.async_api import async_playwright

async def check_all_elements():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})
        
        menu_url = 'https://vesuviopizza.ru/poklonnaya-menu'
        await page.goto(menu_url, timeout=30000, wait_until='networkidle')
        await page.wait_for_timeout(3000)
        
        # Get ALL elements and their text content
        all_elements = await page.evaluate('''() => {
            const elements = document.querySelectorAll('*');
            const results = [];
            for (let el of elements) {
                const text = el.textContent || '';
                const tag = el.tagName;
                const className = el.className || '';
                
                // Only include elements with substantial unique text
                if (text.length > 100 && text.length < 10000) {
                    results.push({
                        tag: tag,
                        className: String(className).substring(0, 50),
                        textLen: text.length,
                        textPreview: text.substring(0, 200)
                    });
                }
            }
            return results;
        }''')
        
        print(f"Elements with substantial text: {len(all_elements)}")
        
        # Check unique text lengths
        seen_lens = set()
        for el in all_elements:
            if el['textLen'] not in seen_lens:
                seen_lens.add(el['textLen'])
                print(f"\n{el['tag']}.{el['className'][:30]} ({el['textLen']} chars):")
                print(f"  {el['textPreview'][:150]}...")
        
        # Check specifically for the menu area by taking element screenshots
        print("\n=== Taking screenshots of main content areas ===")
        
        # Find the main content container
        main = await page.query_selector('main, .t-body, #allrecords, body')
        if main:
            # Get all direct children
            children = await main.query_selector_all(':scope > div')
            print(f"Found {len(children)} top-level divs")
            
            for i, child in enumerate(children[:10]):
                box = await child.bounding_box()
                if box and box['height'] > 100:
                    print(f"Div {i}: {box['width']}x{box['height']} at y={box['y']}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(check_all_elements())
