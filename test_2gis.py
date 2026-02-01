"""
Тест для проверки работы 2GIS API.
Запуск: python test_2gis.py
"""
import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("TWOGIS_API_KEY")
print(f"API Key: {API_KEY[:10]}..." if API_KEY else "API Key: НЕ НАЙДЕН!")

GEOCODE_URL = "https://catalog.api.2gis.com/3.0/items/geocode"
CATALOG_URL = "https://catalog.api.2gis.com/3.0/items"


async def test_geocode(address: str):
    """Тест геокодирования."""
    print(f"\n{'='*50}")
    print(f"ТЕСТ 1: Геокодирование адреса: {address}")
    print(f"{'='*50}")
    
    params = {
        "q": address,
        "key": API_KEY,
        "fields": "items.point",
        "type": "building,street,adm_div,attraction",
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(GEOCODE_URL, params=params) as response:
            print(f"Статус ответа: {response.status}")
            print(f"URL запроса: {response.url}")
            
            if response.status == 200:
                data = await response.json()
                print(f"Ответ API: {data}")
                
                items = data.get("result", {}).get("items", [])
                if items:
                    point = items[0].get("point")
                    if point:
                        print(f"\n[OK] УСПЕХ! Координаты: lat={point['lat']}, lon={point['lon']}")
                        return point['lat'], point['lon']
                    else:
                        print("[FAIL] Нет координат в ответе")
                else:
                    print("[FAIL] Нет результатов геокодирования")
            else:
                text = await response.text()
                print(f"[FAIL] Ошибка API: {text}")
    
    return None


async def test_search_restaurants(lat: float, lon: float, radius: int = 1000):
    """Тест поиска ресторанов."""
    print(f"\n{'='*50}")
    print(f"ТЕСТ 2: Поиск ресторанов около ({lat}, {lon})")
    print(f"Радиус: {radius}м")
    print(f"{'='*50}")
    
    rubrics = [
        ("164", "Рестораны"),
        ("165", "Кафе"),
        ("5819", "Пиццерии"),
    ]
    
    all_restaurants = []
    
    async with aiohttp.ClientSession() as session:
        for rubric_id, rubric_name in rubrics:
            params = {
                "key": API_KEY,
                "point": f"{lon},{lat}",  # Формат: lon,lat
                "radius": radius,
                "rubric_id": rubric_id,
                "fields": "items.point,items.address",
                "page_size": 10,
            }
            
            print(f"\nЗапрос для рубрики '{rubric_name}' (id={rubric_id})...")
            print(f"Параметры: point={params['point']}, radius={params['radius']}")
            
            async with session.get(CATALOG_URL, params=params) as response:
                print(f"Статус: {response.status}")
                
                if response.status == 200:
                    data = await response.json()
                    items = data.get("result", {}).get("items", [])
                    total = data.get("result", {}).get("total", 0)
                    
                    print(f"Найдено в API: {total}, получено: {len(items)}")
                    
                    for item in items:
                        name = item.get("name", "?")
                        addr = item.get("address_name", "?")
                        all_restaurants.append((name, addr))
                        print(f"  • {name} - {addr}")
                else:
                    text = await response.text()
                    print(f"[FAIL] Ошибка: {text}")
    
    print(f"\n{'='*50}")
    print(f"ИТОГО найдено ресторанов: {len(all_restaurants)}")
    print(f"{'='*50}")
    
    return all_restaurants


async def main():
    """Главная функция тестирования."""
    print("=" * 60)
    print("ТЕСТИРОВАНИЕ 2GIS API")
    print("=" * 60)
    
    if not API_KEY:
        print("[FAIL] ОШИБКА: API ключ не найден в .env файле!")
        print("Убедитесь, что TWOGIS_API_KEY установлен в .env")
        return
    
    # Тест 1: Геокодирование
    test_address = "Москва, мукомольный проезд, 2"
    coords = await test_geocode(test_address)
    
    if coords:
        # Тест 2: Поиск ресторанов
        lat, lon = coords
        await test_search_restaurants(lat, lon, radius=500)
    else:
        print("\n[FAIL] Геокодирование не удалось, поиск ресторанов пропущен")
    
    print("\n" + "=" * 60)
    print("ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
