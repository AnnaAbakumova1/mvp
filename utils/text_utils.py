"""
Text processing utilities for dish name matching and price extraction.
"""
import re
import unicodedata
from typing import Optional, Tuple


def normalize_text(text: str) -> str:
    """
    Normalize text for comparison.
    
    - Convert to lowercase
    - Remove extra whitespace
    - Normalize unicode characters
    - Remove punctuation
    """
    if not text:
        return ""
    
    # Normalize unicode
    text = unicodedata.normalize("NFKC", text)
    
    # Lowercase
    text = text.lower()
    
    # Replace multiple whitespace with single space
    text = re.sub(r"\s+", " ", text)
    
    # Remove leading/trailing whitespace
    text = text.strip()
    
    return text


def normalize_for_search(text: str) -> str:
    """
    Normalize text specifically for search matching.
    More aggressive normalization - removes punctuation.
    """
    text = normalize_text(text)
    
    # Remove punctuation but keep spaces
    text = re.sub(r"[^\w\s]", "", text)
    
    return text


def extract_price(text: str, dish_position: int = 0, context_chars: int = 100) -> Tuple[Optional[float], Optional[str]]:
    """
    Extract price from text near the dish mention.
    
    This is a best-effort extraction - not guaranteed to find the correct price.
    Returns (price_float, price_raw_string) or (None, None) if not found.
    
    Price patterns supported:
    - 650 ₽
    - 650 руб
    - 650 р
    - 650р.
    - от 650 до 800
    - 650.00
    """
    if not text:
        return None, None
    
    # Get context around dish position
    start = max(0, dish_position - context_chars)
    end = min(len(text), dish_position + context_chars)
    context = text[start:end]
    
    # Price patterns (ordered by specificity)
    patterns = [
        # Price with currency symbol: 650 ₽, 650₽
        r"(\d{2,5})\s*₽",
        # Price with "руб": 650 руб, 650руб.
        r"(\d{2,5})\s*руб\.?",
        # Price with "р": 650 р, 650р.
        r"(\d{2,5})\s*р\.?\b",
        # Price after dash/colon: — 650, : 650
        r"[—–\-:]\s*(\d{2,5})(?:\s|$|[^\d])",
        # Standalone number that looks like a price (3-4 digits)
        r"\b(\d{3,4})\b",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, context, re.IGNORECASE)
        if match:
            try:
                price = float(match.group(1))
                # Sanity check: price should be reasonable (10 - 50000)
                if 10 <= price <= 50000:
                    raw = match.group(0).strip()
                    return price, raw
            except (ValueError, IndexError):
                continue
    
    return None, None


def fuzzy_match(needle: str, haystack: str, threshold: float = 0.8) -> bool:
    """
    Check if needle is found in haystack with fuzzy matching.
    
    Simple implementation without external dependencies.
    Uses word-based matching with partial overlap.
    
    Args:
        needle: Text to search for
        haystack: Text to search in
        threshold: Minimum match ratio (0.0 - 1.0)
        
    Returns:
        True if match found
    """
    needle = normalize_for_search(needle)
    haystack = normalize_for_search(haystack)
    
    if not needle or not haystack:
        return False
    
    # Direct substring match
    if needle in haystack:
        return True
    
    # Word-based matching
    needle_words = set(needle.split())
    haystack_words = set(haystack.split())
    
    if not needle_words:
        return False
    
    # Check how many needle words appear in haystack
    matches = needle_words & haystack_words
    match_ratio = len(matches) / len(needle_words)
    
    return match_ratio >= threshold


def find_dish_in_text(dish_name: str, text: str) -> Optional[int]:
    """
    Find dish name in text and return position.
    
    Tries multiple matching strategies:
    1. Exact match (normalized)
    2. All words present
    3. Main word present (longest word in dish name)
    
    Returns:
        Position of match or None if not found
    """
    dish_normalized = normalize_for_search(dish_name)
    text_normalized = normalize_for_search(text)
    
    if not dish_normalized or not text_normalized:
        return None
    
    # Strategy 1: Direct substring match
    pos = text_normalized.find(dish_normalized)
    if pos >= 0:
        return pos
    
    # Strategy 2: All significant words present in same region
    dish_words = [w for w in dish_normalized.split() if len(w) > 2]
    
    if not dish_words:
        return None
    
    # Find all occurrences of first word
    first_word = dish_words[0]
    for match in re.finditer(re.escape(first_word), text_normalized):
        pos = match.start()
        # Check if other words are nearby (within 50 chars)
        region_start = max(0, pos - 20)
        region_end = min(len(text_normalized), pos + 100)
        region = text_normalized[region_start:region_end]
        
        if all(word in region for word in dish_words):
            return pos
    
    # Strategy 3: Main word (longest) is present
    main_word = max(dish_words, key=len) if dish_words else ""
    if len(main_word) >= 4:
        pos = text_normalized.find(main_word)
        if pos >= 0:
            return pos
    
    return None
