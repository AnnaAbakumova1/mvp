"""
Telegram Bot for Restaurant Dish Search

Entry point for the application.
Uses long polling mode (recommended for local development).
"""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config import settings
from bot import router
from utils.http_client import http_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

# Reduce noise from external libraries
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("aiogram").setLevel(logging.INFO)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)  # Suppress DNS errors from aiohttp

logger = logging.getLogger(__name__)


async def on_startup(bot: Bot) -> None:
    """Actions to perform on bot startup."""
    logger.info("Bot starting up...")
    
    # Get bot info
    bot_info = await bot.get_me()
    logger.info(f"Bot: @{bot_info.username} ({bot_info.first_name})")


async def on_shutdown(bot: Bot) -> None:
    """Actions to perform on bot shutdown."""
    logger.info("Bot shutting down...")
    
    # Close HTTP client session
    await http_client.close()
    
    # Close browser service (V2)
    try:
        from services.browser_service import close_browser
        await close_browser()
        logger.info("Browser service closed")
    except Exception as e:
        logger.warning(f"Browser cleanup error: {e}")
    
    # Stop task queue (V2)
    try:
        from services.task_queue import task_queue
        await task_queue.stop()
        logger.info("Task queue stopped")
    except Exception as e:
        logger.warning(f"Task queue cleanup error: {e}")
    
    logger.info("Cleanup complete")


async def main() -> None:
    """
    Main entry point.
    
    Uses long polling mode which is recommended for:
    - Local development
    - Simple deployments
    - No need for public HTTPS endpoint
    
    For production with webhook, see webhook_main() below.
    """
    # Initialize bot with default properties
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    
    # Initialize dispatcher
    dp = Dispatcher()
    
    # Register routers
    dp.include_router(router)
    
    # Register startup/shutdown handlers
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    logger.info("Starting bot in polling mode...")
    
    try:
        # Start polling
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True,
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
