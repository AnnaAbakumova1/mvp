import asyncio
from playwright.async_api import async_playwright

async def investigate_menu_structure():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})
        
        menu_url = 'https://vesuviopizza.ru/poklonnaya-menu'
        await page.goto(menu_url, timeout=30000, wait_until='networkidle')
        await page.wait_for_timeout(3000)
        
        # Save full HTML
        html = await page.content()
        with open('vesuvio_menu_page.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"Saved HTML ({len(html)} chars)")
        
        # Check for iframes
        iframes = await page.query_selector_all('iframe')
        print(f"\nIframes: {len(iframes)}")
        for i, iframe in enumerate(iframes):
            src = await iframe.get_attribute('src')
            print(f"  [{i}] src: {src}")
        
        # Check for PDFs
        pdfs = await page.evaluate('''() => {
            const embeds = document.querySelectorAll('embed, object, iframe');
            const pdfs = [];
            for (let el of embeds) {
                const src = el.src || el.data || '';
                if (src.includes('.pdf')) pdfs.push(src);
            }
            return pdfs;
        }''')
        print(f"\nPDF embeds: {pdfs}")
        
        # Check for menu-related elements
        print("\n=== Looking for menu content elements ===")
        selectors = ['table', '.menu', '#menu', '[class*="menu"]', '[class*="dish"]', '[class*="price"]']
        for sel in selectors:
            try:
                elements = await page.query_selector_all(sel)
                if elements:
                    print(f"{sel}: {len(elements)} elements")
                    for i, el in enumerate(elements[:2]):
                        text = await el.inner_text()
                        if len(text) > 50:
                            print(f"  [{i}] text preview: {text[:200]}...")
            except:
                pass
        
        # Try getting ALL text including hidden
        all_text = await page.evaluate('() => document.body.textContent')
        print(f"\nFull textContent: {len(all_text)} chars")
        
        # Search for pizza in textContent
        if 'маргарита' in all_text.lower():
            print(">>> маргарита FOUND in textContent!")
        else:
            print(">>> маргарита NOT in textContent")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(investigate_menu_structure())
