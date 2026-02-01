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


def extract_price(text: str, dish_position: int = 0, context_chars: int = 150) -> Tuple[Optional[float], Optional[str]]:
    """
    Extract price from text near the dish mention.
    
    Searches FORWARD from dish position (prices usually follow dish names).
    Returns (price_float, price_raw_string) or (None, None) if not found.
    
    Price patterns supported:
    - 650 ₽, 650₽
    - 650 руб, 650руб.
    - 650 р, 650р.
    - от 650, 650—800
    - 150г/450₽ (weight/price)
    - 650.00, 650,00
    - RUB 650, 650 RUB
    """
    if not text:
        return None, None
    
    # Get context - prioritize FORWARD search (price usually after dish name)
    start = max(0, dish_position - 30)  # Small lookback
    end = min(len(text), dish_position + context_chars)  # Larger lookforward
    context = text[start:end]
    
    # Price patterns (ordered by specificity - most specific first)
    patterns = [
        # Price with currency symbol: 650 ₽, 650₽, 650 руб
        (r"(\d{2,5})\s*₽", 1),
        (r"(\d{2,5})\s*руб\.?(?:лей)?", 1),
        (r"(\d{2,5})\s*р\.?\b", 1),
        # RUB format: RUB 650, 650 RUB
        (r"RUB\s*(\d{2,5})", 1),
        (r"(\d{2,5})\s*RUB", 1),
        # Weight/price format: 150г/450₽, 150г — 450
        (r"\d+\s*[гgГG]\s*[/—–\-]\s*(\d{2,5})", 1),
        # Price after separator: — 650, / 650, : 650
        (r"[—–\-/:]\s*(\d{2,5})(?:\s*₽|\s*р\.?|\s*руб\.?)?", 1),
        # Decimal prices: 650.00, 650,00
        (r"(\d{2,5})[.,]00\b", 1),
        # Price range: от 650, 650-800 (take first number)
        (r"от\s*(\d{2,5})", 1),
        (r"(\d{3,4})\s*[—–\-]\s*\d{3,4}", 1),
        # Standalone number in typical price range (3-4 digits, not weight)
        (r"(?<!\d)(\d{3,4})(?!\s*[гgГG]|\d)", 1),
    ]
    
    # Try each pattern, collect all matches with positions
    candidates = []
    
    for pattern, group in patterns:
        for match in re.finditer(pattern, context, re.IGNORECASE):
            try:
                price = float(match.group(group))
                # Sanity check: price should be reasonable (50 - 50000 rubles)
                if 50 <= price <= 50000:
                    # Calculate distance from dish position (prefer closer prices)
                    match_pos = match.start()
                    # Prices AFTER dish name are preferred
                    if match_pos >= 30:  # After the lookback area
                        distance = match_pos - 30
                    else:
                        distance = 1000 + (30 - match_pos)  # Penalize prices before dish
                    
                    candidates.append((distance, price, match.group(0).strip()))
            except (ValueError, IndexError):
                continue
    
    # Return closest price to dish position
    if candidates:
        candidates.sort(key=lambda x: x[0])  # Sort by distance
        _, price, raw = candidates[0]
        return price, raw
    
    return None, None


def extract_price_from_line(line: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Extract price from a single menu line.
    
    Useful when parsing structured menus where each line is a dish.
    """
    if not line:
        return None, None
    
    # Common patterns for single-line extraction
    patterns = [
        r"(\d{2,5})\s*₽",
        r"(\d{2,5})\s*руб",
        r"(\d{2,5})\s*р\.?\b",
        r"[—–\-/]\s*(\d{2,5})\s*$",
        r"(\d{3,4})\s*$",  # Number at end of line
    ]
    
    for pattern in patterns:
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            try:
                price = float(match.group(1))
                if 50 <= price <= 50000:
                    return price, match.group(0).strip()
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
    2. All words present in nearby region
    3. Main word present
    4. Transliterated/translated variants
    
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
    
    if dish_words:
        # Find all occurrences of first word
        first_word = dish_words[0]
        for match in re.finditer(re.escape(first_word), text_normalized):
            pos = match.start()
            # Check if other words are nearby (within 100 chars)
            region_start = max(0, pos - 20)
            region_end = min(len(text_normalized), pos + 100)
            region = text_normalized[region_start:region_end]
            
            if all(word in region for word in dish_words):
                return pos
    
    # Strategy 3: Main word (longest) is present
    if dish_words:
        main_word = max(dish_words, key=len)
        if len(main_word) >= 4:
            pos = text_normalized.find(main_word)
            if pos >= 0:
                return pos
    
    # Strategy 4: Try common translations/variants
    variants = _get_dish_variants(dish_name)
    for variant in variants:
        variant_normalized = normalize_for_search(variant)
        pos = text_normalized.find(variant_normalized)
        if pos >= 0:
            return pos
    
    return None


def _get_dish_variants(dish_name: str) -> list:
    """
    Get alternative names/translations for a dish.
    
    Handles Russian <-> English/Italian translations for common dishes.
    """
    dish_lower = dish_name.lower().strip()
    
    # Dictionary of dish name variants
    dish_variants = {
        # Salads
        "зеленый салат": ["green salad", "insalata verde", "салат зеленый", "микс салат", "mix salad", "салат микс", "листовой салат"],
        "салат цезарь": ["caesar salad", "insalata caesar", "цезарь"],
        "греческий салат": ["greek salad", "insalata greca", "греческий"],
        "овощной салат": ["vegetable salad", "insalata di verdure"],
        
        # Soups
        "куриный суп": ["chicken soup", "zuppa di pollo", "суп куриный", "бульон куриный"],
        "томатный суп": ["tomato soup", "zuppa di pomodoro"],
        "грибной суп": ["mushroom soup", "zuppa di funghi"],
        
        # Main dishes
        "паста карбонара": ["carbonara", "pasta carbonara", "карбонара"],
        "пицца маргарита": ["margherita", "pizza margherita", "маргарита"],
        "стейк": ["steak", "bistecca"],
        
        # Common patterns
        "салат": ["salad", "insalata"],
        "суп": ["soup", "zuppa", "brodo"],
        "пицца": ["pizza"],
        "паста": ["pasta"],
    }
    
    variants = []
    
    # Check exact match first
    if dish_lower in dish_variants:
        variants.extend(dish_variants[dish_lower])
    
    # Check if dish contains any known word
    for key, values in dish_variants.items():
        if key in dish_lower or dish_lower in key:
            variants.extend(values)
        # Also check reverse (if searching for English/Italian)
        for v in values:
            if v in dish_lower or dish_lower in v:
                variants.append(key)
                variants.extend([x for x in values if x != v])
    
    # Remove duplicates while preserving order
    seen = set()
    unique_variants = []
    for v in variants:
        if v.lower() not in seen:
            seen.add(v.lower())
            unique_variants.append(v)
    
    return unique_variants
