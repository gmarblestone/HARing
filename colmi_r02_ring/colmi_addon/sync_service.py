"""Manual and scheduled sync of ring data into the local SQLite DB.

Sync reuses the existing `colmi_r02_client.db` helpers and the
`Client.get_full_data(start, end)` method. A run is guarded by an asyncio
lock so that manual (button-triggered) and scheduled runs can't fight over
the BLE session.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from colmi_r02_client import date_utils, db
from colmi_r02_client.client import Client

from .ring_manager import RingManager

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    ok: bool
    started_at: datetime
    finished_at: datetime
    start_range: datetime
    end_range: datetime
    hr_days: int
    step_days: int
    error: str | None = None

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


class SyncService:
    def __init__(self, ring: RingManager, db_path: Path) -> None:
        self._ring = ring
        self._db_path = db_path
        self._run_lock = asyncio.Lock()
        self._last: SyncResult | None = None
        self._scheduler_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def last(self) -> SyncResult | None:
        return self._last

    @property
    def running(self) -> bool:
        return self._run_lock.locked()

    # -- sync execution ----------------------------------------------------

    async def run_once(self, days_back: int | None = None) -> SyncResult:
        """Perform a single sync. If `days_back` is None we start from the
        last sync recorded in the DB (or 7 days ago on first run)."""
        started = datetime.now(tz=timezone.utc)
        # Prevent concurrent syncs; also prevent overlap with other BLE ops.
        async with self._run_lock:
            address = self._ring.address
            if not address:
                self._last = SyncResult(
                    ok=False, started_at=started, finished_at=started,
                    start_range=started, end_range=started,
                    hr_days=0, step_days=0, error="No ring paired",
                )
                return self._last

            end = date_utils.now()
            if days_back is not None:
                start = end - timedelta(days=days_back)
            else:
                with db.get_db_session(self._db_path) as session:
                    last = db.get_last_sync(session, address)
                start = last if last is not None else end - timedelta(days=7)

            try:
                # Go through RingManager.with_connected_client so we get
                # the same scan-then-connect + retry treatment as
                # everything else. This fixes the "device not found" /
                # "failed to discover services, device disconnected"
                # errors seen on BlueZ when the adapter's cache is cold.
                async def _do_sync(client: Client):
                    full_data = await client.get_full_data(start, end)
                    # Set ring time while we're connected (mirrors CLI).
                    try:
                        await client.set_time(datetime.now(tz=timezone.utc))
                    except Exception:  # noqa: BLE001
                        logger.debug("set_time after sync failed (non-fatal)")
                    return full_data

                full_data = await self._ring.with_connected_client("sync", _do_sync)

                with db.get_db_session(self._db_path) as session:
                    db.full_sync(session, full_data)

                finished = datetime.now(tz=timezone.utc)
                result = SyncResult(
                    ok=True, started_at=started, finished_at=finished,
                    start_range=start, end_range=end,
                    hr_days=len(full_data.heart_rates),
                    step_days=len(full_data.sport_details),
                )
            except Exception as exc:
                finished = datetime.now(tz=timezone.utc)
                logger.exception("Sync failed")
                result = SyncResult(
                    ok=False, started_at=started, finished_at=finished,
                    start_range=start, end_range=end,
                    hr_days=0, step_days=0,
                    error=f"{type(exc).__name__}: {exc}",
                )
        self._last = result
        return result

    # -- scheduler ---------------------------------------------------------

    def start_scheduler(self, interval_minutes: int) -> None:
        if interval_minutes <= 0:
            logger.info("Auto-sync disabled (interval=%s)", interval_minutes)
            return
        if self._scheduler_task and not self._scheduler_task.done():
            logger.info("Scheduler already running")
            return
        self._stop_event = asyncio.Event()
        self._scheduler_task = asyncio.create_task(
            self._scheduler_loop(interval_minutes),
            name="colmi-auto-sync",
        )
        logger.info("Auto-sync scheduled every %d minutes", interval_minutes)

    async def stop_scheduler(self) -> None:
        self._stop_event.set()
        task = self._scheduler_task
        self._scheduler_task = None
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()

    async def _scheduler_loop(self, interval_minutes: int) -> None:
        interval_seconds = interval_minutes * 60
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval_seconds)
                return  # stop requested
            except asyncio.TimeoutError:
                pass
            if not self._ring.address:
                logger.debug("Skipping auto-sync — no ring paired")
                continue
            try:
                await self.run_once()
            except Exception:
                logger.exception("Scheduled sync raised")
