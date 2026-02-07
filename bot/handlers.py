"""
Telegram bot message handlers.
"""
import asyncio
import logging
from typing import List

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext

from bot.states import SearchState
from bot.keyboards import get_start_keyboard, get_cancel_keyboard, get_results_keyboard
from models import SearchResult, RestaurantStatus
from services import geo_service, dish_matcher
from config import settings

logger = logging.getLogger(__name__)

router = Router()


# --- Command handlers ---

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Handle /start command."""
    logger.info(f"[DEBUG] /start от пользователя {message.from_user.id}")
    await state.clear()
    
    await message.answer(
        "Привет! Я помогу найти рестораны с нужным блюдом.\n\n"
        "Напишите название блюда, которое хотите найти.\n"
        "Например: паста карбонара",
        reply_markup=get_start_keyboard(),
    )
    
    await state.set_state(SearchState.waiting_for_dish)


@router.message(Command("help"))
@router.message(F.text == "Помощь")
async def cmd_help(message: Message):
    """Handle /help command."""
    await message.answer(
        "Как пользоваться ботом:\n\n"
        "1. Напишите название блюда (например: борщ, паста карбонара)\n"
        "2. Укажите город или адрес\n"
        "3. Получите список ресторанов с этим блюдом\n\n"
        "Команды:\n"
        "/start - Начать поиск\n"
        "/help - Показать справку\n"
        "/cancel - Отменить текущий поиск\n\n"
        f"Радиус поиска: {settings.default_radius_meters} м",
    )


@router.message(Command("cancel"))
@router.message(F.text == "Отмена")
async def cmd_cancel(message: Message, state: FSMContext):
    """Handle /cancel command."""
    current_state = await state.get_state()
    
    if current_state is None:
        await message.answer("Нечего отменять.")
        return
    
    await state.clear()
    await message.answer(
        "Поиск отменён. Напишите /start чтобы начать заново.",
        reply_markup=get_start_keyboard(),
    )


# --- Search flow handlers ---

@router.message(F.text == "Найти блюдо")
async def start_search(message: Message, state: FSMContext):
    """Start new search flow."""
    await message.answer(
        "Напишите название блюда, которое хотите найти:",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(SearchState.waiting_for_dish)


@router.message(SearchState.waiting_for_dish)
async def process_dish_name(message: Message, state: FSMContext):
    """Process dish name input."""
    dish_name = message.text.strip()
    
    if len(dish_name) < 2:
        await message.answer("Название блюда слишком короткое. Попробуйте ещё раз:")
        return
    
    if len(dish_name) > 100:
        await message.answer("Название блюда слишком длинное. Попробуйте ещё раз:")
        return
    
    await state.update_data(dish_name=dish_name)
    
    await message.answer(
        f"Ищем: *{dish_name}*\n\n"
        "Теперь напишите город или адрес для поиска:",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(),
    )
    
    await state.set_state(SearchState.waiting_for_location)


@router.message(SearchState.waiting_for_location)
async def process_location(message: Message, state: FSMContext):
    """Process location input and start search with progressive radius."""
    location_text = message.text.strip()
    logger.info(f"[DEBUG] Получен адрес: {location_text}")
    
    if len(location_text) < 2:
        await message.answer("Адрес слишком короткий. Попробуйте ещё раз:")
        return
    
    data = await state.get_data()
    dish_name = data.get("dish_name", "")
    logger.info(f"[DEBUG] Ищем блюдо: {dish_name}")
    
    # Send processing message
    processing_msg = await message.answer(
        f"Ищу рестораны с блюдом \"{dish_name}\" рядом с \"{location_text}\"...\n"
        "Начинаю поиск в радиусе 100 м.",
        reply_markup=None,
    )
    
    await state.set_state(SearchState.processing)
    
    try:
        # Step 1: Geocode location
        logger.info(f"[DEBUG] Геокодирование: {location_text}")
        coords = await geo_service.geocode(location_text)
        logger.info(f"[DEBUG] Результат геокодирования: {coords}")
        
        if not coords:
            await processing_msg.edit_text(
                f"Не удалось найти адрес: {location_text}\n"
                "Попробуйте указать более точный адрес.",
            )
            await state.set_state(SearchState.waiting_for_location)
            return
        
        lat, lon = coords
        logger.info(f"[DEBUG] Координаты: lat={lat}, lon={lon}")
        
        # Import services
        from services import site_finder
        from services.menu_parser_v2 import menu_parser_v2
        from services.pdf_parser import pdf_parser
        from utils.text_utils import find_dish_in_text, extract_price
        
        invalid_domains = [
            "t.me", "telegram.org", "vk.com", "whatsapp.com", 
            "wa.me", "facebook.com", "instagram.com", "youtube.com"
        ]
        
        # Progressive radius search: 100, 200, 300, 400, 500, 1000 meters
        restaurants_with_dish = []  # Restaurants where dish was FOUND
        restaurants_checked = []    # All checked restaurants (to show menu links)
        checked_ids = set()         # Already processed restaurant IDs
        target_count = 3            # Stop when we find 3 restaurants with dish
        max_radius = 1000           # Increased radius for better coverage
        radius_step = 200           # Larger steps for faster search
        
        def format_found_restaurants(found_list, dish):
            """Format list of found restaurants for display."""
            lines = [f"Найдено блюдо \"{dish}\" в {len(found_list)} рест.:\n"]
            for i, r in enumerate(found_list, 1):
                lines.append(f"*{i}. {r['name']}*")
                if r.get("menu_url"):
                    lines.append(f"   🔗 {r['menu_url']}")
                if r.get("price"):
                    lines.append(f"   🍽 {r['dish_name']} — {r['price']:.0f} ₽")
                else:
                    lines.append(f"   🍽 {r['dish_name']} — цена не указана")
                lines.append("")
            return "\n".join(lines)
        
        for current_radius in range(radius_step, max_radius + 1, radius_step):
            # Update status message with current results
            if restaurants_with_dish:
                status_text = format_found_restaurants(restaurants_with_dish, dish_name)
                status_text += f"\n---\nИщу ещё... Радиус: {current_radius} м"
            else:
                status_text = f"Ищу блюдо \"{dish_name}\"...\nРадиус поиска: {current_radius} м"
            
            await processing_msg.edit_text(status_text, parse_mode="Markdown", disable_web_page_preview=True)
            
            logger.info(f"[DEBUG] Поиск в радиусе {current_radius}м около ({lat}, {lon})")
            
            # Search restaurants at current radius
            restaurants = await geo_service.search_restaurants(lat, lon, radius_meters=current_radius)
            logger.info(f"[DEBUG] Найдено ресторанов в {current_radius}м: {len(restaurants) if restaurants else 0}")
            
            if not restaurants:
                continue
            
            # Process only new restaurants (not checked before)
            for restaurant in restaurants:
                # Skip if already checked
                if restaurant.id in checked_ids:
                    continue
                checked_ids.add(restaurant.id)
                
                # Stop if we found enough
                if len(restaurants_with_dish) >= target_count:
                    break
                
                # Find website
                website = await site_finder.find_website(restaurant)
                
                if not website:
                    continue
                    
                # Check if it's a valid website (not social media)
                if any(domain in website.lower() for domain in invalid_domains):
                    logger.info(f"[DEBUG] Пропущен (соц.сеть): {restaurant.name} -> {website}")
                    continue
                
                logger.info(f"[DEBUG] Ищу блюдо на: {website}")
                
                # Use V2 parser with PDF and browser support
                parse_result = await menu_parser_v2.find_and_parse_menu(
                    website_url=website,
                    dish_name=dish_name,
                    use_browser_fallback=True,
                    timeout=25
                )
                
                menu_url = parse_result.menu_url or website
                page_text = parse_result.menu_text
                dish_position = parse_result.dish_position if parse_result.dish_found else None
                
                # Check if this is an image-based menu (very little extractable text)
                is_image_based_menu = (not page_text or len(page_text) < 300)
                
                if dish_position is not None and page_text:
                    # Dish found! Add and update message immediately
                    price = parse_result.price  # Use price from V2 parser
                    if price is None and page_text:
                        price, _ = extract_price(page_text, dish_position)
                    
                    restaurants_with_dish.append({
                        "name": restaurant.name,
                        "website": website,
                        "dish_name": dish_name,
                        "price": price,
                        "menu_url": menu_url,
                        "source": parse_result.source.value if parse_result.source else "unknown"
                    })
                    logger.info(f"[DEBUG] Найдено блюдо: {restaurant.name} -> {dish_name}, цена: {price}, источник: {parse_result.source}")
                    
                    # Update message immediately with new result
                    if len(restaurants_with_dish) < target_count:
                        status_text = format_found_restaurants(restaurants_with_dish, dish_name)
                        status_text += f"\n---\nИщу ещё... Радиус: {current_radius} м"
                        await processing_msg.edit_text(status_text, parse_mode="Markdown", disable_web_page_preview=True)
                else:
                    # Dish not found in menu - add to checked list with reason
                    restaurants_checked.append({
                        "name": restaurant.name,
                        "website": website,
                        "menu_url": menu_url,
                        "found": False,
                        "is_image_menu": is_image_based_menu
                    })
                    if is_image_based_menu:
                        logger.info(f"[DEBUG] Меню в виде изображений: {restaurant.name} -> {website}")
                    else:
                        logger.info(f"[DEBUG] Блюдо не найдено в меню: {restaurant.name}")
            
            # Stop if we found enough restaurants with the dish
            if len(restaurants_with_dish) >= target_count:
                logger.info(f"[DEBUG] Найдено {len(restaurants_with_dish)} ресторанов, останавливаем поиск")
                break
        
        # Final results
        lines = []
        
        if restaurants_with_dish:
            lines.append(f"Найдено блюдо \"{dish_name}\" в {len(restaurants_with_dish)} ресторанах:\n")
            for i, r in enumerate(restaurants_with_dish, 1):
                lines.append(f"*{i}. {r['name']}*")
                if r["menu_url"]:
                    lines.append(f"   🔗 {r['menu_url']}")
                if r["price"]:
                    lines.append(f"   🍽 {r['dish_name']} — {r['price']:.0f} ₽")
                else:
                    lines.append(f"   🍽 {r['dish_name']} — цена не указана")
                lines.append("")
        
        # Show restaurants where dish was not found (with menu links)
        if restaurants_checked and not restaurants_with_dish:
            lines.append(f"Блюдо \"{dish_name}\" не найдено автоматически.\n")
            lines.append("Рестораны рядом — проверьте меню самостоятельно:\n")
            
            # Separate image-based menus from regular ones
            image_menus = [r for r in restaurants_checked if r.get("is_image_menu")]
            regular_menus = [r for r in restaurants_checked if not r.get("is_image_menu")]
            
            # Show regular menus first
            for r in regular_menus[:5]:
                lines.append(f"• {r['name']}")
                if r.get("menu_url"):
                    lines.append(f"  🔗 {r['menu_url']}")
                elif r.get("website"):
                    lines.append(f"  🔗 {r['website']}")
                lines.append("")
            
            # Show image-based menus with explanation
            if image_menus:
                remaining_slots = 5 - len(regular_menus[:5])
                if remaining_slots > 0:
                    for r in image_menus[:remaining_slots]:
                        lines.append(f"• {r['name']} (меню в виде изображений)")
                        if r.get("menu_url"):
                            lines.append(f"  🔗 {r['menu_url']}")
                        elif r.get("website"):
                            lines.append(f"  🔗 {r['website']}")
                        lines.append("")
        
        if not restaurants_with_dish and not restaurants_checked:
            lines.append(f"Нет ресторанов с доступными сайтами в радиусе 500 м от \"{location_text}\".")
        
        response = "\n".join(lines)
        
        await processing_msg.edit_text(
            response,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        
    except Exception as e:
        logger.error(f"Search error: {e}", exc_info=True)
        await processing_msg.edit_text(
            "Произошла ошибка при поиске. Попробуйте позже.",
        )
    
    finally:
        await state.clear()
        await message.answer(
            "Для нового поиска напишите /start",
            reply_markup=get_start_keyboard(),
        )


# --- Callback handlers ---

@router.callback_query(F.data == "new_search")
async def callback_new_search(callback: CallbackQuery, state: FSMContext):
    """Handle new search button press."""
    await callback.answer()
    await state.clear()
    
    await callback.message.answer(
        "Напишите название блюда:",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(SearchState.waiting_for_dish)


# --- Helper functions ---

async def search_dish_in_restaurants(restaurants, dish_name: str) -> List[SearchResult]:
    """
    Search for dish in multiple restaurants concurrently.
    
    Limits concurrency to avoid overwhelming servers.
    Only returns restaurants with valid websites (not Telegram/VK/WhatsApp).
    """
    semaphore = asyncio.Semaphore(3)  # Max 3 concurrent requests
    
    async def search_one(restaurant):
        async with semaphore:
            result = await dish_matcher.search_dish(restaurant, dish_name)
            
            # Filter out invalid website sources (Telegram, VK, WhatsApp, etc.)
            if result.menu_url:
                invalid_domains = [
                    "t.me", "telegram.org", "vk.com", "whatsapp.com", 
                    "wa.me", "facebook.com", "instagram.com"
                ]
                if any(domain in result.menu_url.lower() for domain in invalid_domains):
                    # Mark as SITE_NOT_FOUND if it's not a proper website
                    result.status = RestaurantStatus.SITE_NOT_FOUND
                    result.menu_url = None
            
            return result
    
    tasks = [search_one(r) for r in restaurants]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filter out exceptions and SITE_NOT_FOUND results
    valid_results = []
    for result in results:
        if isinstance(result, SearchResult):
            if result.status != RestaurantStatus.SITE_NOT_FOUND:
                valid_results.append(result)
        elif isinstance(result, Exception):
            logger.error(f"Search task failed: {result}")
    
    return valid_results


def format_search_results(dish_name: str, location: str, results: List[SearchResult]) -> str:
    """Format search results for Telegram message - show only first 3 with websites."""
    
    # Separate found results from others
    found = [r for r in results if r.status in (RestaurantStatus.FOUND, RestaurantStatus.FOUND_NO_PRICE)]
    
    lines = []
    
    if found:
        # Show only first 3 restaurants with websites
        top_results = found[:3]
        
        lines.append(f"Найдено {len(top_results)} ресторанов с \"{dish_name}\" (показаны первые 3):\n")
        
        for i, result in enumerate(top_results, 1):
            lines.append(f"*{i}. {result.restaurant.name}*")
            lines.append(f"   📍 {result.restaurant.address}")
            
            if result.menu_item:
                if result.menu_item.price:
                    lines.append(f"   🍽 {result.menu_item.name} — {result.menu_item.price:.0f} ₽")
                else:
                    lines.append(f"   🍽 {result.menu_item.name} — цена не указана")
            
            if result.menu_url:
                lines.append(f"   🔗 {result.menu_url}")
            
            lines.append("")
    
    else:
        lines.append(f"Блюдо \"{dish_name}\" не найдено в меню ресторанов рядом с \"{location}\".\n")
    
    # Add stats
    not_found = [r for r in results if r.status not in (RestaurantStatus.FOUND, RestaurantStatus.FOUND_NO_PRICE)]
    menu_unavailable = sum(1 for r in not_found if r.status == RestaurantStatus.MENU_UNAVAILABLE)
    site_not_found = sum(1 for r in not_found if r.status == RestaurantStatus.SITE_NOT_FOUND)
    
    if menu_unavailable > 0 or site_not_found > 0:
        lines.append("---")
        lines.append(f"Проверено ресторанов: {len(results)}")
        if menu_unavailable > 0:
            lines.append(f"Меню недоступно: {menu_unavailable}")
        if site_not_found > 0:
            lines.append(f"Сайт не найден: {site_not_found}")
    
    return "\n".join(lines)


# --- Debug catch-all handler (должен быть последним!) ---

@router.message()
async def debug_catch_all(message: Message, state: FSMContext):
    """Catch-all handler for debugging unhandled messages."""
    current_state = await state.get_state()
    logger.warning(
        f"[DEBUG] Необработанное сообщение: '{message.text}' "
        f"от пользователя {message.from_user.id}, "
        f"состояние FSM: {current_state}"
    )
    await message.answer(
        f"[DEBUG] Сообщение не обработано.\n"
        f"Текст: {message.text}\n"
        f"Состояние: {current_state}\n\n"
        f"Напишите /start чтобы начать."
    )
