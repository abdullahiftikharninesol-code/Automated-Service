from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import anyio
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.followup_processor import FollowUpProcessor

logger = logging.getLogger("missed_lead_rescue.scheduler")


class BackgroundReminderScheduler:
    """Lightweight in-process periodic scheduler for local/single-instance deployment.

    Database-backed: PostgreSQL determines WHAT is due, while this scheduler only determines
    WHEN to check. Uses asyncio task with clean cancellation and delegates DB execution
    to worker threads to prevent event loop blocking.
    """

    def __init__(
        self,
        db_factory: Callable[[], Session] = SessionLocal,
        interval_seconds: int | None = None,
    ):
        self.db_factory = db_factory
        self.settings = get_settings()
        self.interval_seconds = (
            interval_seconds
            if interval_seconds is not None
            else self.settings.reminder_sweep_interval_seconds
        )
        self._task: asyncio.Task[None] | None = None
        self._running: bool = False

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.is_running:
            logger.warning("Background reminder scheduler is already running.")
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "No running asyncio event loop; background reminder scheduler not started."
            )
            return

        self._running = True
        self._task = loop.create_task(self._run_loop(), name="reminder_sweep_loop")
        logger.info(
            "Background reminder scheduler started (interval=%d seconds).",
            self.interval_seconds,
        )

    async def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Background reminder scheduler stopped cleanly.")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.interval_seconds)
                if not self._running:
                    break
                await anyio.to_thread.run_sync(self._execute_sweep)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Error in background reminder scheduler loop: %s", exc)

    def _execute_sweep(self) -> int:
        """Run single sweep iteration in worker thread with its own short-lived DB session."""
        db = self.db_factory()
        try:
            processor = FollowUpProcessor(db)
            count = processor.process_due()
            if count > 0:
                logger.info("Background reminder sweep processed %d jobs.", count)
            return count
        except Exception as exc:
            logger.exception("Error executing background reminder sweep: %s", exc)
            return 0
        finally:
            db.close()


# Module-level default singleton
scheduler = BackgroundReminderScheduler()
