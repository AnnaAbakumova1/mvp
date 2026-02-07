"""
Async task queue for heavy parsing operations.

Provides non-blocking execution of:
- PDF OCR processing
- Browser rendering
- LLM-based analysis

Two modes:
1. In-process async queue (default) - no external dependencies
2. Redis-backed queue with worker process (optional, for production)

Integrates with Telegram FSM via callbacks.
"""
import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Any, Dict, Awaitable
from datetime import datetime
import json

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """Task priority levels."""
    LOW = 0
    NORMAL = 1
    HIGH = 2


@dataclass
class Task:
    """Represents a queued task."""
    id: str
    task_type: str
    params: Dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    callback_chat_id: Optional[int] = None
    callback_message_id: Optional[int] = None
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_type": self.task_type,
            "params": self.params,
            "status": self.status.value,
            "priority": self.priority.value,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "callback_chat_id": self.callback_chat_id,
            "callback_message_id": self.callback_message_id,
        }


@dataclass
class TaskResult:
    """Result returned to caller."""
    task_id: str
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None


class TaskHandler:
    """Base class for task handlers."""
    
    async def execute(self, params: Dict[str, Any]) -> Any:
        raise NotImplementedError


class PDFParseHandler(TaskHandler):
    """Handler for PDF parsing tasks."""
    
    async def execute(self, params: Dict[str, Any]) -> Any:
        from services.pdf_parser import pdf_parser
        
        pdf_url = params.get("pdf_url")
        if not pdf_url:
            raise ValueError("pdf_url is required")
        
        text = await pdf_parser.extract_text_from_url(pdf_url)
        return {"text": text, "pdf_url": pdf_url}


class BrowserRenderHandler(TaskHandler):
    """Handler for browser rendering tasks."""
    
    async def execute(self, params: Dict[str, Any]) -> Any:
        from services.browser_service import render_js_page
        
        url = params.get("url")
        if not url:
            raise ValueError("url is required")
        
        timeout = params.get("timeout", 30000)
        result = await render_js_page(url, timeout=timeout)
        
        return {
            "html": result.html,
            "text": result.text,
            "url": result.url,
            "success": result.success,
            "error": result.error
        }


class MenuSearchHandler(TaskHandler):
    """Handler for full menu search tasks."""
    
    async def execute(self, params: Dict[str, Any]) -> Any:
        from services.menu_parser_v2 import menu_parser_v2
        
        website_url = params.get("website_url")
        dish_name = params.get("dish_name", "")
        
        if not website_url:
            raise ValueError("website_url is required")
        
        result = await menu_parser_v2.find_and_parse_menu(
            website_url=website_url,
            dish_name=dish_name
        )
        
        return result


class AsyncTaskQueue:
    """
    In-process async task queue.
    
    Features:
    - Priority-based execution
    - Configurable concurrency
    - Task callbacks for FSM integration
    - Automatic retry for failed tasks
    """
    
    def __init__(
        self,
        max_workers: int = 3,
        max_queue_size: int = 100
    ):
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size
        
        self._queue: asyncio.PriorityQueue = None
        self._tasks: Dict[str, Task] = {}
        self._handlers: Dict[str, TaskHandler] = {}
        self._workers: list = []
        self._running = False
        self._callbacks: Dict[str, Callable[[TaskResult], Awaitable[None]]] = {}
        
        # Register default handlers
        self._register_default_handlers()
    
    def _register_default_handlers(self):
        """Register built-in task handlers."""
        self._handlers["pdf_parse"] = PDFParseHandler()
        self._handlers["browser_render"] = BrowserRenderHandler()
        self._handlers["menu_search"] = MenuSearchHandler()
    
    def register_handler(self, task_type: str, handler: TaskHandler):
        """Register a custom task handler."""
        self._handlers[task_type] = handler
    
    async def start(self):
        """Start the task queue workers."""
        if self._running:
            return
        
        self._queue = asyncio.PriorityQueue(maxsize=self.max_queue_size)
        self._running = True
        
        # Start worker coroutines
        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker(f"worker-{i}"))
            self._workers.append(worker)
        
        logger.info(f"Task queue started with {self.max_workers} workers")
    
    async def stop(self):
        """Stop the task queue."""
        self._running = False
        
        # Cancel all workers
        for worker in self._workers:
            worker.cancel()
        
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        
        self._workers.clear()
        logger.info("Task queue stopped")
    
    async def _worker(self, name: str):
        """Worker coroutine that processes tasks."""
        logger.debug(f"[{name}] Started")
        
        while self._running:
            try:
                # Get task from queue (priority, task_id)
                _, task_id = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0
                )
                
                task = self._tasks.get(task_id)
                if not task:
                    continue
                
                if task.status == TaskStatus.CANCELLED:
                    continue
                
                await self._execute_task(task, name)
                
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{name}] Unexpected error: {e}")
    
    async def _execute_task(self, task: Task, worker_name: str):
        """Execute a single task."""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        
        handler = self._handlers.get(task.task_type)
        if not handler:
            task.status = TaskStatus.FAILED
            task.error = f"Unknown task type: {task.task_type}"
            logger.error(f"[{worker_name}] {task.error}")
            return
        
        logger.info(f"[{worker_name}] Executing {task.task_type}: {task.id}")
        
        try:
            result = await handler.execute(task.params)
            task.result = result
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            
            logger.info(f"[{worker_name}] Completed {task.id}")
            
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now()
            
            logger.error(f"[{worker_name}] Failed {task.id}: {e}")
        
        # Execute callback if registered
        callback = self._callbacks.get(task.id)
        if callback:
            try:
                await callback(TaskResult(
                    task_id=task.id,
                    success=task.status == TaskStatus.COMPLETED,
                    result=task.result,
                    error=task.error
                ))
            except Exception as e:
                logger.error(f"[{worker_name}] Callback error: {e}")
            finally:
                del self._callbacks[task.id]
    
    async def submit(
        self,
        task_type: str,
        params: Dict[str, Any],
        priority: TaskPriority = TaskPriority.NORMAL,
        callback: Optional[Callable[[TaskResult], Awaitable[None]]] = None,
        chat_id: Optional[int] = None,
        message_id: Optional[int] = None,
    ) -> str:
        """
        Submit a task to the queue.
        
        Args:
            task_type: Type of task (pdf_parse, browser_render, menu_search)
            params: Task parameters
            priority: Task priority
            callback: Async callback function for completion notification
            chat_id: Telegram chat ID for FSM integration
            message_id: Telegram message ID for updates
            
        Returns:
            Task ID
        """
        if not self._running:
            await self.start()
        
        task_id = str(uuid.uuid4())[:8]
        
        task = Task(
            id=task_id,
            task_type=task_type,
            params=params,
            priority=priority,
            callback_chat_id=chat_id,
            callback_message_id=message_id,
        )
        
        self._tasks[task_id] = task
        
        if callback:
            self._callbacks[task_id] = callback
        
        # Add to priority queue (lower number = higher priority)
        await self._queue.put((3 - priority.value, task_id))
        
        logger.debug(f"Task submitted: {task_id} ({task_type})")
        return task_id
    
    async def submit_and_wait(
        self,
        task_type: str,
        params: Dict[str, Any],
        timeout: float = 60.0,
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> TaskResult:
        """
        Submit task and wait for completion.
        
        Useful for synchronous-style code.
        """
        event = asyncio.Event()
        result_holder = [None]
        
        async def on_complete(result: TaskResult):
            result_holder[0] = result
            event.set()
        
        task_id = await self.submit(
            task_type=task_type,
            params=params,
            priority=priority,
            callback=on_complete
        )
        
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return result_holder[0]
        except asyncio.TimeoutError:
            self.cancel_task(task_id)
            return TaskResult(task_id=task_id, success=False, error="Timeout")
    
    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """Get task status."""
        task = self._tasks.get(task_id)
        return task.status if task else None
    
    def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get task result."""
        task = self._tasks.get(task_id)
        if not task:
            return None
        
        return TaskResult(
            task_id=task_id,
            success=task.status == TaskStatus.COMPLETED,
            result=task.result,
            error=task.error
        )
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending task."""
        task = self._tasks.get(task_id)
        if task and task.status == TaskStatus.PENDING:
            task.status = TaskStatus.CANCELLED
            return True
        return False
    
    def get_queue_stats(self) -> Dict[str, int]:
        """Get queue statistics."""
        stats = {
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "total": len(self._tasks)
        }
        
        for task in self._tasks.values():
            if task.status == TaskStatus.PENDING:
                stats["pending"] += 1
            elif task.status == TaskStatus.RUNNING:
                stats["running"] += 1
            elif task.status == TaskStatus.COMPLETED:
                stats["completed"] += 1
            elif task.status == TaskStatus.FAILED:
                stats["failed"] += 1
        
        return stats
    
    def cleanup_old_tasks(self, max_age_seconds: int = 3600):
        """Remove old completed/failed tasks."""
        now = datetime.now()
        to_remove = []
        
        for task_id, task in self._tasks.items():
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                if task.completed_at:
                    age = (now - task.completed_at).total_seconds()
                    if age > max_age_seconds:
                        to_remove.append(task_id)
        
        for task_id in to_remove:
            del self._tasks[task_id]
        
        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} old tasks")


# Global task queue instance
task_queue = AsyncTaskQueue(max_workers=3)


# --- FSM Integration Helpers ---

class TaskAwareState:
    """
    Mixin for aiogram FSM states that can wait for task completion.
    
    Usage in handlers.py:
        # Submit task and update message when done
        async def on_task_complete(result: TaskResult):
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=f"Done! Result: {result.result}"
            )
        
        task_id = await task_queue.submit(
            task_type="pdf_parse",
            params={"pdf_url": url},
            callback=on_task_complete,
            chat_id=message.chat.id,
            message_id=processing_msg.message_id
        )
    """
    pass


async def create_task_callback(
    bot,  # aiogram Bot instance
    chat_id: int,
    message_id: int,
    success_template: str = "Done: {result}",
    error_template: str = "Error: {error}",
) -> Callable[[TaskResult], Awaitable[None]]:
    """
    Create a callback that updates a Telegram message when task completes.
    
    Usage:
        callback = await create_task_callback(
            bot=bot,
            chat_id=message.chat.id,
            message_id=processing_msg.message_id,
            success_template="Found menu: {result[menu_url]}"
        )
        await task_queue.submit("menu_search", params, callback=callback)
    """
    async def callback(result: TaskResult):
        try:
            if result.success:
                text = success_template.format(result=result.result)
            else:
                text = error_template.format(error=result.error)
            
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text
            )
        except Exception as e:
            logger.error(f"Callback message update failed: {e}")
    
    return callback
