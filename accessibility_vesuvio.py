import asyncio
from playwright.async_api import async_playwright

async def use_accessibility_tree():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})
        
        menu_url = 'https://vesuviopizza.ru/poklonnaya-menu'
        await page.goto(menu_url, timeout=30000, wait_until='networkidle')
        await page.wait_for_timeout(3000)
        
        # Try accessibility snapshot
        print("=== Accessibility Tree ===")
        try:
            snapshot = await page.accessibility.snapshot()
            if snapshot:
                def extract_text(node, depth=0):
                    texts = []
                    name = node.get('name', '')
                    if name and len(name) > 2:
                        texts.append(name)
                    children = node.get('children', [])
                    for child in children:
                        texts.extend(extract_text(child, depth+1))
                    return texts
                
                all_texts = extract_text(snapshot)
                full_text = ' '.join(all_texts)
                print(f"Accessibility text: {len(full_text)} chars")
                
                # Save it
                with open('vesuvio_accessibility.txt', 'w', encoding='utf-8') as f:
                    f.write(full_text)
                
                # Search for dishes
                dishes = ['маргарита', 'пепперони', 'карбонара', 'капрезе']
                for dish in dishes:
                    if dish.lower() in full_text.lower():
                        print(f"{dish}: FOUND in accessibility tree!")
                    else:
                        print(f"{dish}: NOT in accessibility tree")
        except Exception as e:
            print(f"Accessibility error: {e}")
        
        # Also try aria-label and title attributes
        print("\n=== Aria labels and titles ===")
        aria_texts = await page.evaluate('''() => {
            const elements = document.querySelectorAll('[aria-label], [title]');
            const texts = [];
            for (let el of elements) {
                const aria = el.getAttribute('aria-label') || '';
                const title = el.getAttribute('title') || '';
                if (aria) texts.push(aria);
                if (title) texts.push(title);
            }
            return texts;
        }''')
        print(f"Found {len(aria_texts)} aria/title texts")
        for text in aria_texts[:10]:
            print(f"  {text[:100]}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(use_accessibility_tree())
