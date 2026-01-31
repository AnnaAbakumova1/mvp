"""
Telegram inline and reply keyboards.
"""
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Get keyboard with cancel button."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Отмена")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_start_keyboard() -> ReplyKeyboardMarkup:
    """Get main menu keyboard."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Найти блюдо")],
            [KeyboardButton(text="Помощь")],
        ],
        resize_keyboard=True,
    )


def get_location_keyboard() -> ReplyKeyboardMarkup:
    """Get keyboard for location input with optional geolocation."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Отправить геолокацию", request_location=True)],
            [KeyboardButton(text="Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_results_keyboard(results_count: int) -> InlineKeyboardMarkup:
    """Get inline keyboard for search results."""
    buttons = []
    
    if results_count > 0:
        buttons.append([
            InlineKeyboardButton(text="Новый поиск", callback_data="new_search")
        ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)
