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
    """Process location input and start search."""
    location_text = message.text.strip()
    
    if len(location_text) < 2:
        await message.answer("Адрес слишком короткий. Попробуйте ещё раз:")
        return
    
    data = await state.get_data()
    dish_name = data.get("dish_name", "")
    
    # Send processing message
    processing_msg = await message.answer(
        f"Ищу рестораны с блюдом \"{dish_name}\" рядом с \"{location_text}\"...\n"
        "Это может занять некоторое время.",
        reply_markup=None,
    )
    
    await state.set_state(SearchState.processing)
    
    try:
        # Step 1: Geocode location
        coords = await geo_service.geocode(location_text)
        
        if not coords:
            await processing_msg.edit_text(
                f"Не удалось найти адрес: {location_text}\n"
                "Попробуйте указать более точный адрес.",
            )
            await state.set_state(SearchState.waiting_for_location)
            return
        
        lat, lon = coords
        
        # Step 2: Search restaurants
        await processing_msg.edit_text(
            f"Адрес найден! Ищу рестораны в радиусе {settings.default_radius_meters} м..."
        )
        
        restaurants = await geo_service.search_restaurants(lat, lon)
        
        if not restaurants:
            await processing_msg.edit_text(
                f"Рядом с \"{location_text}\" не найдено ресторанов.\n"
                "Попробуйте другой адрес или увеличьте радиус поиска.",
            )
            await state.set_state(SearchState.waiting_for_location)
            return
        
        # Step 3: Search for dish in each restaurant
        await processing_msg.edit_text(
            f"Найдено {len(restaurants)} ресторанов. Проверяю меню..."
        )
        
        results = await search_dish_in_restaurants(restaurants, dish_name)
        
        # Step 4: Format and send results
        response = format_search_results(dish_name, location_text, results)
        
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
    """
    semaphore = asyncio.Semaphore(3)  # Max 3 concurrent requests
    
    async def search_one(restaurant):
        async with semaphore:
            return await dish_matcher.search_dish(restaurant, dish_name)
    
    tasks = [search_one(r) for r in restaurants]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filter out exceptions
    valid_results = []
    for result in results:
        if isinstance(result, SearchResult):
            valid_results.append(result)
        elif isinstance(result, Exception):
            logger.error(f"Search task failed: {result}")
    
    return valid_results


def format_search_results(dish_name: str, location: str, results: List[SearchResult]) -> str:
    """Format search results for Telegram message."""
    
    # Separate found results from others
    found = [r for r in results if r.status in (RestaurantStatus.FOUND, RestaurantStatus.FOUND_NO_PRICE)]
    not_found = [r for r in results if r.status not in (RestaurantStatus.FOUND, RestaurantStatus.FOUND_NO_PRICE)]
    
    lines = []
    
    if found:
        lines.append(f"Найдено {len(found)} ресторанов с \"{dish_name}\":\n")
        
        for i, result in enumerate(found, 1):
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
