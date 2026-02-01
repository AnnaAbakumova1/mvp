import asyncio
from playwright.async_api import async_playwright

async def test():
    url = 'https://muumsk.ru/menu'
    
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()
    
    await page.goto(url, wait_until='networkidle', timeout=30000)
    await page.wait_for_timeout(2000)
    
    # Найти все ссылки
    links = await page.evaluate('''() => {
        return Array.from(document.querySelectorAll('a')).map(a => ({
            href: a.href,
            text: a.innerText.trim().substring(0, 50)
        })).filter(l => l.href && l.href.length > 5);
    }''')
    
    print('Ссылки на странице /menu:')
    for link in links[:20]:
        text = link["text"][:30]
        href = link["href"]
        print(f'  {text:30} -> {href}')
    
    # Скриншот
    await page.screenshot(path='muu_menu_page.png', full_page=True)
    print('\nСкриншот: muu_menu_page.png')

    await browser.close()
    await pw.stop()

if __name__ == '__main__':
    asyncio.run(test())
