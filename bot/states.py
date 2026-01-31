"""
FSM states for the bot conversation flow.
"""
from aiogram.fsm.state import State, StatesGroup


class SearchState(StatesGroup):
    """States for dish search flow."""
    
    # Waiting for dish name input
    waiting_for_dish = State()
    
    # Waiting for location/address input
    waiting_for_location = State()
    
    # Processing search (optional state for tracking)
    processing = State()
