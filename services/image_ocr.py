"""
Image OCR service for extracting text from menu images on websites.

Pipeline:
1. Find menu images on page (via Playwright)
2. Download images
3. Run OCR via pytesseract
4. Cache results
"""
import asyncio
import logging
import re
import io
from typing import Optional, List, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

from services.cache import menu_cache

logger = logging.getLogger(__name__)

# Thread pool for OCR (CPU-intensive)
_ocr_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="img_ocr_")


@dataclass
class ImageOCRResult:
    """Result of image OCR."""
    success: bool
    text: str = ""
    images_processed: int = 0
    error: Optional[str] = None


class ImageOCRService:
    """
    OCR service for menu images on websites.
    """
    
    def __init__(self):
        self._ocr_available = None
    
    def _check_ocr(self) -> bool:
        """Check if OCR is available."""
        if self._ocr_available is None:
            try:
                import pytesseract
                from PIL import Image
                pytesseract.get_tesseract_version()
                self._ocr_available = True
            except Exception as e:
                logger.warning(f"OCR not available: {e}")
                self._ocr_available = False
        return self._ocr_available
    
    async def extract_text_from_page_images(
        self,
        url: str,
        min_image_size: int = 200,
        max_images: int = 5
    ) -> ImageOCRResult:
        """
        Extract text from menu images on a webpage.
        
        Args:
            url: Page URL
            min_image_size: Minimum image dimension (px) to consider
            max_images: Maximum number of images to process
            
        Returns:
            ImageOCRResult with extracted text
        """
        # Check cache
        cache_key = f"img_ocr:{url}"
        cached = await menu_cache.get_menu_text(cache_key)
        if cached:
            logger.info(f"[IMG_OCR] Cache hit for: {url}")
            return ImageOCRResult(success=True, text=cached)
        
        if not self._check_ocr():
            return ImageOCRResult(success=False, error="OCR not available")
        
        logger.info(f"[IMG_OCR] Processing images from: {url}")
        
        # Find and download menu images
        images = await self._find_menu_images(url, min_image_size, max_images)
        
        if not images:
            return ImageOCRResult(success=False, error="No menu images found")
        
        logger.info(f"[IMG_OCR] Found {len(images)} images to OCR")
        
        # OCR each image
        texts = []
        for i, img_data in enumerate(images):
            text = await self._ocr_image(img_data)
            if text:
                texts.append(text)
                logger.debug(f"[IMG_OCR] Image {i+1}: {len(text)} chars extracted")
        
        if not texts:
            return ImageOCRResult(
                success=False,
                images_processed=len(images),
                error="OCR failed to extract text"
            )
        
        # Combine texts
        full_text = "\n\n".join(texts)
        full_text = re.sub(r"\s+", " ", full_text).strip()
        
        # Cache result
        if len(full_text) > 100:
            await menu_cache.set_menu_text(cache_key, full_text)
        
        logger.info(f"[IMG_OCR] Extracted {len(full_text)} chars from {len(texts)} images")
        
        return ImageOCRResult(
            success=True,
            text=full_text,
            images_processed=len(images)
        )
    
    async def _find_menu_images(
        self,
        url: str,
        min_size: int,
        max_images: int
    ) -> List[bytes]:
        """Find and download menu images from page using Playwright."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("[IMG_OCR] Playwright not installed")
            return []
        
        images_data = []
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 720}
                )
                page = await context.new_page()
                
                # Navigate to page
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(2000)
                
                # Find all images
                images = await page.query_selector_all("img")
                
                menu_keywords = ["menu", "меню", "блюд", "dish", "food", "carta"]
                
                for img in images:
                    if len(images_data) >= max_images:
                        break
                    
                    try:
                        # Get image info
                        src = await img.get_attribute("src")
                        alt = (await img.get_attribute("alt") or "").lower()
                        
                        # Check size
                        box = await img.bounding_box()
                        if not box:
                            continue
                        
                        width, height = box["width"], box["height"]
                        
                        # Skip small images
                        if width < min_size or height < min_size:
                            continue
                        
                        # Prioritize images with menu-related attributes
                        is_menu_image = any(kw in alt or kw in (src or "").lower() 
                                           for kw in menu_keywords)
                        
                        # Also accept large images (likely menu)
                        is_large = width > 400 and height > 300
                        
                        if is_menu_image or is_large:
                            # Take screenshot of the image element
                            img_bytes = await img.screenshot()
                            if img_bytes:
                                images_data.append(img_bytes)
                                logger.debug(f"[IMG_OCR] Captured image: {width}x{height}")
                    
                    except Exception as e:
                        logger.debug(f"[IMG_OCR] Error processing image: {e}")
                        continue
                
                await browser.close()
        
        except Exception as e:
            logger.error(f"[IMG_OCR] Playwright error: {e}")
        
        return images_data
    
    async def _ocr_image(self, img_data: bytes) -> Optional[str]:
        """Run OCR on image data."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_ocr_executor, self._ocr_sync, img_data)
    
    def _ocr_sync(self, img_data: bytes) -> Optional[str]:
        """Synchronous OCR processing."""
        try:
            import pytesseract
            from PIL import Image
            
            # Load image
            img = Image.open(io.BytesIO(img_data))
            
            # Convert to RGB if needed
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            # Run OCR
            text = pytesseract.image_to_string(
                img,
                lang="rus+eng",
                config="--psm 6"  # Assume uniform block of text
            )
            
            return text.strip() if text else None
            
        except Exception as e:
            logger.error(f"[IMG_OCR] OCR error: {e}")
            return None
    
    def is_image_based_menu(self, html: str, text: str) -> bool:
        """
        Detect if page has image-based menu (little text, many images).
        
        Args:
            html: Page HTML
            text: Extracted text from page
            
        Returns:
            True if menu appears to be image-based
        """
        # Very little text extracted
        if len(text) < 300:
            # Check if page has images
            img_count = html.lower().count("<img")
            if img_count >= 3:
                return True
        
        # Has menu keywords in text but no prices
        menu_words = ["меню", "menu", "блюда", "dishes"]
        has_menu_word = any(w in text.lower() for w in menu_words)
        
        price_pattern = r"\d{2,4}\s*[₽рруб]"
        has_prices = bool(re.search(price_pattern, text))
        
        if has_menu_word and not has_prices and len(text) < 500:
            return True
        
        return False


# Global instance
image_ocr_service = ImageOCRService()
