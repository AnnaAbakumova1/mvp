"""
PDF menu parser with OCR fallback.

Extraction strategy:
1. Try direct text extraction via PyMuPDF (fast, works for text PDFs)
2. If text is empty/minimal, use OCR via pdf2image + pytesseract
3. Cache results to avoid re-processing

All operations are async via run_in_executor.
"""
import asyncio
import io
import logging
import re
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

from services.cache import menu_cache
from utils.http_client import http_client

logger = logging.getLogger(__name__)

# Thread pool for CPU-intensive operations (OCR)
_ocr_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ocr_")

# Minimum text length to consider PDF as text-based (not scanned images)
MIN_TEXT_LENGTH = 100


class PDFParser:
    """
    Async PDF parser with OCR fallback and caching.
    """
    
    def __init__(self):
        self._pymupdf_available = None
        self._ocr_available = None
    
    def _check_pymupdf(self) -> bool:
        """Check if PyMuPDF is available."""
        if self._pymupdf_available is None:
            try:
                import fitz  # PyMuPDF
                self._pymupdf_available = True
            except ImportError:
                logger.warning("PyMuPDF not installed, PDF text extraction disabled")
                self._pymupdf_available = False
        return self._pymupdf_available
    
    def _check_ocr(self) -> bool:
        """Check if OCR dependencies are available."""
        if self._ocr_available is None:
            try:
                import pytesseract
                from pdf2image import convert_from_bytes
                # Check tesseract is installed
                pytesseract.get_tesseract_version()
                self._ocr_available = True
            except (ImportError, Exception) as e:
                logger.warning(f"OCR not available: {e}")
                self._ocr_available = False
        return self._ocr_available
    
    async def extract_text_from_url(self, pdf_url: str) -> Optional[str]:
        """
        Extract text from PDF URL with caching.
        
        Pipeline:
        1. Check cache
        2. Download PDF
        3. Try direct text extraction
        4. Fallback to OCR if needed
        5. Cache result
        """
        # Check cache first
        cached_text = await menu_cache.get_pdf_text(pdf_url)
        if cached_text:
            logger.info(f"[PDF] Cache hit for: {pdf_url}")
            return cached_text
        
        logger.info(f"[PDF] Processing: {pdf_url}")
        
        # Download PDF
        pdf_data = await self._download_pdf(pdf_url)
        if not pdf_data:
            logger.warning(f"[PDF] Failed to download: {pdf_url}")
            return None
        
        # Extract text
        text = await self.extract_text_from_bytes(pdf_data)
        
        # Cache result if we got text
        if text and len(text) > MIN_TEXT_LENGTH:
            await menu_cache.set_pdf_text(pdf_url, text)
            logger.info(f"[PDF] Extracted and cached {len(text)} chars from: {pdf_url}")
        
        return text
    
    async def extract_text_from_bytes(self, pdf_data: bytes) -> Optional[str]:
        """
        Extract text from PDF bytes.
        
        Tries direct extraction first, falls back to OCR.
        """
        # Try direct text extraction
        text = await self._extract_text_direct(pdf_data)
        
        if text and len(text) >= MIN_TEXT_LENGTH:
            logger.debug(f"[PDF] Direct extraction successful: {len(text)} chars")
            return text
        
        # Fallback to OCR
        logger.info("[PDF] Direct extraction failed, trying OCR...")
        text = await self._extract_text_ocr(pdf_data)
        
        if text:
            logger.debug(f"[PDF] OCR extraction successful: {len(text)} chars")
        
        return text
    
    async def _download_pdf(self, url: str) -> Optional[bytes]:
        """Download PDF file."""
        try:
            # Use http_client but get raw bytes
            import aiohttp
            from config import settings
            
            timeout = aiohttp.ClientTimeout(total=settings.request_timeout_seconds)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        content_type = response.headers.get("Content-Type", "")
                        
                        # Verify it's a PDF
                        if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
                            logger.warning(f"[PDF] URL is not a PDF: {content_type}")
                            return None
                        
                        return await response.read()
                    else:
                        logger.warning(f"[PDF] Download failed: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"[PDF] Download error: {e}")
            return None
    
    async def _extract_text_direct(self, pdf_data: bytes) -> Optional[str]:
        """
        Extract text directly using PyMuPDF.
        Fast, works for text-based PDFs.
        """
        if not self._check_pymupdf():
            return None
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._extract_text_pymupdf_sync, pdf_data)
    
    def _extract_text_pymupdf_sync(self, pdf_data: bytes) -> Optional[str]:
        """Synchronous PyMuPDF text extraction."""
        try:
            import fitz  # PyMuPDF
            
            doc = fitz.open(stream=pdf_data, filetype="pdf")
            text_parts = []
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                text = page.get_text("text")
                if text:
                    text_parts.append(text)
            
            doc.close()
            
            full_text = "\n".join(text_parts)
            # Clean up whitespace
            full_text = re.sub(r"\s+", " ", full_text).strip()
            
            return full_text if full_text else None
            
        except Exception as e:
            logger.error(f"[PDF] PyMuPDF error: {e}")
            return None
    
    async def _extract_text_ocr(self, pdf_data: bytes) -> Optional[str]:
        """
        Extract text using OCR (pdf2image + pytesseract).
        Slower, but works for scanned/image PDFs.
        """
        if not self._check_ocr():
            return None
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_ocr_executor, self._extract_text_ocr_sync, pdf_data)
    
    def _extract_text_ocr_sync(self, pdf_data: bytes) -> Optional[str]:
        """Synchronous OCR text extraction."""
        try:
            import pytesseract
            from pdf2image import convert_from_bytes
            from PIL import Image
            
            # Convert PDF to images
            # Use lower DPI for speed, 150 is usually enough for menu text
            images = convert_from_bytes(
                pdf_data,
                dpi=150,
                fmt="png",
                thread_count=2
            )
            
            text_parts = []
            
            for i, image in enumerate(images):
                # OCR with Russian + English support
                text = pytesseract.image_to_string(
                    image,
                    lang="rus+eng",
                    config="--psm 6"  # Assume uniform block of text
                )
                if text:
                    text_parts.append(text)
                
                # Limit to first 5 pages for performance
                if i >= 4:
                    logger.info("[PDF] OCR limited to first 5 pages")
                    break
            
            full_text = "\n".join(text_parts)
            # Clean up OCR artifacts
            full_text = re.sub(r"\s+", " ", full_text).strip()
            
            return full_text if full_text else None
            
        except Exception as e:
            logger.error(f"[PDF] OCR error: {e}")
            return None
    
    def is_pdf_url(self, url: str) -> bool:
        """Check if URL points to a PDF file."""
        url_lower = url.lower()
        
        # Check extension
        if url_lower.endswith(".pdf"):
            return True
        
        # Check common PDF URL patterns
        pdf_patterns = [
            "/menu.pdf",
            "/меню.pdf",
            "download=pdf",
            "format=pdf",
            "/files/menu",
            "/upload/menu",
        ]
        
        return any(pattern in url_lower for pattern in pdf_patterns)
    
    async def find_pdf_links(self, html: str, base_url: str) -> list[str]:
        """
        Find PDF menu links in HTML.
        
        Returns list of absolute PDF URLs.
        """
        from urllib.parse import urljoin
        from bs4 import BeautifulSoup
        
        try:
            soup = BeautifulSoup(html, "lxml")
            pdf_links = []
            
            # Find all links ending with .pdf
            for link in soup.find_all("a", href=True):
                href = link.get("href", "").strip()
                text = link.get_text().lower().strip()
                
                # Check if it's a PDF link
                if href.lower().endswith(".pdf"):
                    full_url = urljoin(base_url, href)
                    
                    # Prioritize menu-related PDFs
                    if any(kw in text or kw in href.lower() for kw in ["меню", "menu", "карта", "carta"]):
                        pdf_links.insert(0, full_url)  # Add to front
                    else:
                        pdf_links.append(full_url)
            
            # Deduplicate while preserving order
            seen = set()
            unique_links = []
            for link in pdf_links:
                if link not in seen:
                    seen.add(link)
                    unique_links.append(link)
            
            return unique_links[:5]  # Limit to 5 PDFs
            
        except Exception as e:
            logger.error(f"[PDF] Error finding PDF links: {e}")
            return []


# Global parser instance
pdf_parser = PDFParser()
