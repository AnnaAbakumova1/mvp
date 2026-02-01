import asyncio
import re
from playwright.async_api import async_playwright

async def test():
    url = 'https://vesuviopizza.ru/poklonnaya-menu'
    
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()
    
    await page.goto(url, wait_until='networkidle', timeout=30000)
    await page.wait_for_timeout(2000)
    
    # Сохраним HTML
    html = await page.content()
    with open('vesuvio_menu_full.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'HTML saved: {len(html)} chars')
    
    # Ищем Маргарита в HTML
    if 'аргарита' in html.lower():
        idx = html.lower().index('аргарита')
        print(f'Margherita found in HTML at {idx}')
        print(f'Context: {html[max(0,idx-50):idx+100]}')
    else:
        print('Margherita NOT in HTML')
    
    # Ищем цены (числа 3-4 цифры)
    prices = re.findall(r'\b(\d{3,4})\b', html)
    print(f'\nNumbers (possible prices): {prices[:20]}')

    await browser.close()
    await pw.stop()

if __name__ == '__main__':
    asyncio.run(test())
