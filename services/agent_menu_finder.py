"""
Browser-based agent for finding restaurant menus.
Uses Playwright + Groq LLM for intelligent navigation.

This is a FALLBACK mechanism - only used when static parser fails.
"""
import asyncio
import logging
import json
import re
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    """Status codes for agent results."""
    FOUND = "found"                    # Dish found in menu
    NOT_FOUND = "not_found"            # Menu found, dish not present
    MENU_NOT_FOUND = "menu_not_found"  # Could not find menu
    TIMEOUT = "timeout"                # Exceeded time limit
    ERROR = "error"                    # Browser/LLM error


@dataclass
class AgentResult:
    """Result from the menu finder agent."""
    found: bool
    menu_url: Optional[str]
    dish_fragment: Optional[str]
    status: AgentStatus


@dataclass
class AgentAction:
    """Action decided by LLM."""
    action_type: str  # CLICK, FOUND, NOT_FOUND, GIVE_UP
    target: Optional[str] = None
    context: Optional[str] = None
    reason: Optional[str] = None


# System prompt for LLM reasoning
AGENT_SYSTEM_PROMPT = """You are a web navigation agent. Your task is to find the restaurant menu and check if a specific dish exists.

HOW TO RECOGNIZE A MENU PAGE:
- Contains food item names (салат, суп, роллы, пицца, стейк, etc.)
- Contains prices (₽, руб, numbers like 350, 890, 1200)
- URL often contains: /menu, /food, /dishes, /kitchen
- Categories like: закуски, горячее, напитки, десерты

RULES:
1. CLICK links related to menu: "меню", "menu", "кухня", "блюда", "food", "dishes", "our menu", "наше меню", "еда"
2. IGNORE: booking, delivery, contacts, about us, news, events, careers, cart, корзина, доставка, контакты
3. If you see food items with prices - this IS the menu page
4. When on menu page: search for the target dish. If dish not found in text - respond NOT_FOUND
5. If no menu link exists and page has no food items - respond GIVE_UP

RESPOND WITH ONLY JSON (no markdown, no explanation):
{"action": "CLICK", "target": "exact link text to click", "reason": "why"}
{"action": "FOUND", "context": "text fragment containing the dish", "reason": "found dish"}
{"action": "NOT_FOUND", "reason": "this is menu page but dish is not present"}
{"action": "GIVE_UP", "reason": "cannot find menu on this site"}
"""


class MenuFinderAgent:
    """
    Browser-based agent for finding restaurant menus.
    
    Uses Playwright for browser automation and Groq LLM for reasoning.
    Should only be used as a fallback when static parsing fails.
    """
    
    def __init__(self):
        self._browser = None
        self._playwright = None
        
    async def find_menu_and_dish(
        self,
        site_url: str,
        dish: str = "",
        timeout: int = 30,
        max_steps: int = 5
    ) -> AgentResult:
        """
        Main entry point for the agent.
        
        Args:
            site_url: Restaurant website URL
            dish: Dish name to search for (optional)
            timeout: Maximum time in seconds
            max_steps: Maximum navigation steps
            
        Returns:
            AgentResult with status and findings
        """
        from config import settings
        
        if not settings.agent_enabled:
            logger.info("Agent is disabled in config")
            return AgentResult(
                found=False,
                menu_url=None,
                dish_fragment=None,
                status=AgentStatus.ERROR
            )
        
        logger.info(f"[AGENT] Starting for: {site_url}, dish: '{dish}'")
        
        try:
            result = await asyncio.wait_for(
                self._run_agent(site_url, dish, max_steps),
                timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            logger.warning(f"[AGENT] Timeout after {timeout}s for: {site_url}")
            return AgentResult(
                found=False,
                menu_url=None,
                dish_fragment=None,
                status=AgentStatus.TIMEOUT
            )
        except Exception as e:
            logger.error(f"[AGENT] Error: {e}")
            return AgentResult(
                found=False,
                menu_url=None,
                dish_fragment=None,
                status=AgentStatus.ERROR
            )
        finally:
            await self._cleanup()
    
    async def _run_agent(self, site_url: str, dish: str, max_steps: int) -> AgentResult:
        """Run the agent loop."""
        
        # Initialize browser
        page = await self._init_browser(site_url)
        if not page:
            return AgentResult(
                found=False,
                menu_url=None,
                dish_fragment=None,
                status=AgentStatus.ERROR
            )
        
        current_url = site_url
        
        for step in range(max_steps):
            logger.info(f"[AGENT] Step {step + 1}/{max_steps}, URL: {page.url}")
            
            # Get page context
            page_text = await self._get_page_text(page)
            links = await self._get_links(page)
            
            # Check if dish is already on page (quick win)
            if dish and self._dish_in_text(dish, page_text):
                fragment = self._extract_dish_fragment(dish, page_text)
                logger.info(f"[AGENT] Found dish on page: {fragment[:100]}...")
                return AgentResult(
                    found=True,
                    menu_url=page.url,
                    dish_fragment=fragment,
                    status=AgentStatus.FOUND
                )
            
            # Check if this looks like a menu page
            if self._looks_like_menu(page_text, page.url) and not dish:
                logger.info(f"[AGENT] Found menu page: {page.url}")
                return AgentResult(
                    found=True,
                    menu_url=page.url,
                    dish_fragment=None,
                    status=AgentStatus.FOUND
                )
            
            # Ask LLM for next action
            action = await self._ask_llm(page_text, links, dish, step)
            
            if action.action_type == "FOUND":
                # Verify LLM claim - check if dish really exists on page
                if dish and not self._dish_in_text(dish, page_text):
                    logger.warning(f"[AGENT] LLM claimed FOUND but dish not in text, continuing...")
                    # Don't trust LLM, continue searching or mark as not found
                    if self._looks_like_menu(page_text, page.url):
                        return AgentResult(
                            found=False,
                            menu_url=page.url,
                            dish_fragment=None,
                            status=AgentStatus.NOT_FOUND
                        )
                    continue
                
                return AgentResult(
                    found=True,
                    menu_url=page.url,
                    dish_fragment=action.context,
                    status=AgentStatus.FOUND
                )
            
            elif action.action_type == "NOT_FOUND":
                return AgentResult(
                    found=False,
                    menu_url=page.url,
                    dish_fragment=None,
                    status=AgentStatus.NOT_FOUND
                )
            
            elif action.action_type == "CLICK" and action.target:
                success = await self._click_link(page, action.target)
                if not success:
                    logger.warning(f"[AGENT] Failed to click: {action.target}")
                    # Try to continue anyway
                
                await asyncio.sleep(1)  # Wait for page load
            
            elif action.action_type == "GIVE_UP":
                logger.info(f"[AGENT] Giving up: {action.reason}")
                break
        
        # Max steps reached - check if we're on a menu page
        final_text = await self._get_page_text(page)
        if self._looks_like_menu(final_text, page.url):
            logger.info(f"[AGENT] Max steps reached on menu page, dish not found: {page.url}")
            return AgentResult(
                found=False,
                menu_url=page.url,
                dish_fragment=None,
                status=AgentStatus.NOT_FOUND
            )
        
        return AgentResult(
            found=False,
            menu_url=None,
            dish_fragment=None,
            status=AgentStatus.MENU_NOT_FOUND
        )
    
    async def _init_browser(self, url: str):
        """Initialize Playwright browser and navigate to URL."""
        try:
            from playwright.async_api import async_playwright
            
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True
            )
            
            context = await self._browser.new_context(
                viewport={'width': 1280, 'height': 720},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            
            page = await context.new_page()
            
            # Block images and fonts for faster loading
            await page.route("**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf}", 
                           lambda route: route.abort())
            
            # Try loading with longer timeout, fall back to commit if slow
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=20000)
            except Exception:
                # Retry with commit (faster, doesn't wait for subresources)
                await page.goto(url, wait_until='commit', timeout=15000)
            
            return page
            
        except Exception as e:
            logger.error(f"[AGENT] Browser init error: {e}")
            return None
    
    async def _cleanup(self):
        """Clean up browser resources."""
        try:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.error(f"[AGENT] Cleanup error: {e}")
        finally:
            self._browser = None
            self._playwright = None
    
    async def _get_page_text(self, page) -> str:
        """Extract visible text from page."""
        try:
            text = await page.evaluate('''() => {
                return document.body.innerText || document.body.textContent || '';
            }''')
            # Limit to 3000 chars for LLM context
            return text[:3000] if text else ""
        except Exception:
            return ""
    
    async def _get_links(self, page) -> List[Dict[str, str]]:
        """Extract all links from page."""
        try:
            links = await page.evaluate('''() => {
                const links = [];
                document.querySelectorAll('a[href]').forEach(a => {
                    const text = (a.innerText || a.textContent || '').trim();
                    const href = a.href;
                    if (text && text.length < 100 && href && !href.startsWith('javascript:')) {
                        links.push({text: text, href: href});
                    }
                });
                return links.slice(0, 30);  // Limit to 30 links
            }''')
            return links or []
        except Exception:
            return []
    
    async def _click_link(self, page, link_text: str) -> bool:
        """Click a link by its text."""
        try:
            # Try exact match first
            link = page.get_by_text(link_text, exact=True)
            if await link.count() > 0:
                await link.first.click()
                await page.wait_for_load_state('domcontentloaded', timeout=10000)
                return True
            
            # Try partial match
            link = page.get_by_text(link_text)
            if await link.count() > 0:
                await link.first.click()
                await page.wait_for_load_state('domcontentloaded', timeout=10000)
                return True
            
            return False
        except Exception as e:
            logger.warning(f"[AGENT] Click error: {e}")
            return False
    
    def _dish_in_text(self, dish: str, text: str) -> bool:
        """Check if dish name appears in text."""
        dish_lower = dish.lower().strip()
        text_lower = text.lower()
        
        # Direct match
        if dish_lower in text_lower:
            return True
        
        # Check individual words (for multi-word dishes)
        words = dish_lower.split()
        if len(words) > 1:
            return all(word in text_lower for word in words)
        
        return False
    
    def _extract_dish_fragment(self, dish: str, text: str) -> str:
        """Extract text fragment containing the dish."""
        dish_lower = dish.lower()
        text_lower = text.lower()
        
        pos = text_lower.find(dish_lower)
        if pos == -1:
            return ""
        
        # Get 100 chars before and after
        start = max(0, pos - 50)
        end = min(len(text), pos + len(dish) + 100)
        
        return text[start:end].strip()
    
    def _looks_like_menu(self, text: str, url: str = "") -> bool:
        """Check if text looks like a menu page."""
        text_lower = text.lower()
        url_lower = url.lower() if url else ""
        
        # URL indicators
        url_menu_indicators = ["/menu", "/food", "/dishes", "/kitchen", "/cuisine", "/kuhnya"]
        if any(ind in url_lower for ind in url_menu_indicators):
            return True
        
        # Text indicators - food categories and items
        menu_indicators = [
            "меню", "блюд", "цена", "порция", "грамм",
            "салат", "суп", "горячее", "десерт", "напитки",
            "закуск", "роллы", "пицца", "паста", "стейк",
            "₽", "руб", "menu", "dishes", "price"
        ]
        
        count = sum(1 for ind in menu_indicators if ind in text_lower)
        return count >= 3
    
    async def _ask_llm(
        self,
        page_text: str,
        links: List[Dict[str, str]],
        dish: str,
        step: int
    ) -> AgentAction:
        """Ask Groq LLM for the next action."""
        from config import settings
        
        if not settings.groq_api_key:
            logger.warning("[AGENT] No Groq API key, using heuristic")
            return self._heuristic_action(links)
        
        try:
            import aiohttp
            
            # Format links for prompt
            links_text = "\n".join([f"- {l['text']}" for l in links[:20]])
            
            user_prompt = f"""Step: {step + 1}/5
Target dish: {dish if dish else "(just find menu)"}

Page text (truncated):
{page_text[:1500]}

Available links:
{links_text}

What action should I take?"""

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.groq_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "llama-3.1-8b-instant",
                        "messages": [
                            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.1,
                        "max_tokens": 150
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data["choices"][0]["message"]["content"]
                        return self._parse_llm_response(content)
                    else:
                        logger.warning(f"[AGENT] Groq API error: {resp.status}")
                        return self._heuristic_action(links)
                        
        except Exception as e:
            logger.error(f"[AGENT] LLM error: {e}")
            return self._heuristic_action(links)
    
    def _parse_llm_response(self, content: str) -> AgentAction:
        """Parse JSON response from LLM."""
        try:
            # Try to extract JSON from response
            content = content.strip()
            
            # Remove markdown code blocks if present
            if content.startswith("```"):
                content = re.sub(r"```\w*\n?", "", content)
                content = content.strip()
            
            data = json.loads(content)
            
            return AgentAction(
                action_type=data.get("action", "GIVE_UP").upper(),
                target=data.get("target"),
                context=data.get("context"),
                reason=data.get("reason")
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[AGENT] Failed to parse LLM response: {content[:100]}")
            return AgentAction(action_type="GIVE_UP", reason="parse error")
    
    def _heuristic_action(self, links: List[Dict[str, str]]) -> AgentAction:
        """Fallback heuristic when LLM is unavailable."""
        menu_keywords = ["меню", "menu", "блюда", "dishes", "кухня", "food"]
        
        for link in links:
            text_lower = link["text"].lower()
            for keyword in menu_keywords:
                if keyword in text_lower:
                    return AgentAction(
                        action_type="CLICK",
                        target=link["text"],
                        reason=f"heuristic: contains '{keyword}'"
                    )
        
        return AgentAction(action_type="GIVE_UP", reason="no menu link found")


# Global agent instance
menu_finder_agent = MenuFinderAgent()
