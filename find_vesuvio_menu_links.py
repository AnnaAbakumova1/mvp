import asyncio
from playwright.async_api import async_playwright

async def find_menu_links():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})
        
        await page.goto('https://vesuviopizza.ru/', timeout=30000, wait_until='networkidle')
        await page.wait_for_timeout(2000)
        
        # Find all links with "меню" in text or href
        links = await page.evaluate('''() => {
            const allLinks = document.querySelectorAll('a');
            const menuLinks = [];
            for (let link of allLinks) {
                const text = link.innerText.toLowerCase();
                const href = link.href || '';
                if (text.includes('меню') || text.includes('menu') || href.includes('menu')) {
                    menuLinks.push({
                        text: link.innerText.trim().substring(0, 50),
                        href: href
                    });
                }
            }
            return menuLinks;
        }''')
        
        print("=== Menu-related links ===")
        for link in links:
            print(f"Text: {link['text']}")
            print(f"  URL: {link['href']}")
            print()
        
        # Also find buttons that might open menus
        buttons = await page.evaluate('''() => {
            const allButtons = document.querySelectorAll('button, [role="button"], .btn, [class*="button"]');
            const menuButtons = [];
            for (let btn of allButtons) {
                const text = btn.innerText.toLowerCase();
                if (text.includes('меню') || text.includes('открыть')) {
                    menuButtons.push({
                        text: btn.innerText.trim().substring(0, 50),
                        onclick: btn.onclick ? 'has onclick' : 'no onclick',
                        className: btn.className
                    });
                }
            }
            return menuButtons;
        }''')
        
        print("=== Menu buttons ===")
        for btn in buttons:
            print(f"Text: {btn['text']}")
            print(f"  Class: {btn['className']}")
            print()
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(find_menu_links())
