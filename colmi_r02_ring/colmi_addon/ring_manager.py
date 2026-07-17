"""Serialised access to the ring over BLE.

Only one BLE operation can be in flight at a time (a ring can't handle
concurrent GATT sessions), so every request through this manager is guarded
by an asyncio lock. The manager is a long-lived singleton owned by the
FastAPI app.

The ring's paired address can be updated at runtime through the pairing UI
without restarting the add-on. A change invalidates any cached status.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from bleak import BleakScanner
from bleak.exc import BleakError, BleakDeviceNotFoundError

from colmi_r02_client import real_time
from colmi_r02_client.client import Client

logger = logging.getLogger(__name__)

# How many extra times to retry a BLE op after the first attempt fails
# with a transient BleakError. BlueZ on Linux frequently drops the first
# connect attempt if the adapter hasn't seen the device recently, or
# fails service discovery right after connect — a short scan + retry
# almost always succeeds on the second try.
_BLE_OP_RETRIES = 2

# How long to spend priming the BlueZ discovery cache before each BLE
# op. bleak's BlueZ backend can't connect to a bare MAC that hasn't
# been advertised in the last ~30s, so we always scan first.
_PRIME_SCAN_SECONDS = 10.0

# Cool-off between retries — long enough for BlueZ to clean up the
# aborted connection before we scan again.
_RETRY_BACKOFF_SECONDS = 2.0


@dataclass
class ScanResult:
    name: str
    address: str
    rssi: int | None = None


@dataclass
class Status:
    address: str
    paired: bool
    reachable: bool
    battery_level: int | None = None
    charging: bool | None = None
    hw_version: str | None = None
    fw_version: str | None = None
    last_seen: datetime | None = None
    last_error: str | None = None


# Best-effort list of BLE name prefixes that indicate a compatible ring.
# Copied from colmi_r02_client.cli.DEVICE_NAME_PREFIXES so we don't reach
# into a private-ish CLI module — and to allow tweaks (e.g. matching the
# "COLMI R02_..." advertisement seen in the wild).
DEVICE_NAME_PREFIXES: tuple[str, ...] = (
    "R01", "R02", "R03", "R04", "R05", "R06", "R07", "R09", "R10",
    "COLMI", "VK-5098", "MERLIN", "Hello Ring", "RING1", "boAtring",
    "TR-R02", "KSIX RING",
)


def _looks_like_ring(name: str | None) -> bool:
    if not name:
        return False
    return any(name.startswith(p) for p in DEVICE_NAME_PREFIXES)


class RingManager:
    """Owns a single Client instance keyed by BLE address."""

    def __init__(self, address: str = "") -> None:
        self._address = address
        self._lock = asyncio.Lock()
        self._last_status: Status | None = None

    # -- address management ------------------------------------------------

    @property
    def address(self) -> str:
        return self._address

    def set_address(self, address: str) -> None:
        address = address.strip()
        if address != self._address:
            logger.info("Ring address changed: %r -> %r", self._address, address)
            self._address = address
            self._last_status = None

    # -- scanning ----------------------------------------------------------

    async def scan(self, seconds: int = 8, include_all: bool = False) -> list[ScanResult]:
        """Passive BLE scan. Returns compatible rings, or all devices when
        include_all=True. Scan doesn't require a paired address."""
        logger.info("Scanning for BLE devices for %ds (include_all=%s)", seconds, include_all)
        devices = await BleakScanner.discover(timeout=float(seconds))
        results: list[ScanResult] = []
        for dev in devices:
            if not include_all and not _looks_like_ring(dev.name):
                continue
            results.append(ScanResult(name=dev.name or "(unknown)", address=dev.address, rssi=getattr(dev, "rssi", None)))
        # Sort with candidate rings first, then by name.
        results.sort(key=lambda r: (not _looks_like_ring(r.name), r.name.lower()))
        return results

    # -- ring operations ---------------------------------------------------

    def _require_address(self) -> str:
        if not self._address:
            raise RuntimeError("No ring paired. Configure an address via the pairing page.")
        return self._address

    async def with_connected_client(self, op_name: str, fn):
        """Public wrapper for other services (e.g. SyncService) so they
        share the same lock and scan-then-connect retry behaviour as
        internal ops. `fn` is called with a connected `Client`."""
        return await self._with_client(op_name, fn)

    async def _with_client(self, op_name, fn):
        """Run `fn(client)` inside a fresh connected Client, serialised
        with the manager lock. `fn` may be sync or async.

        Wraps the connect in a scan-then-connect-then-retry loop because
        bleak's BlueZ backend (used inside the HA add-on container)
        raises `BleakDeviceNotFoundError` when connecting to a MAC the
        adapter hasn't seen advertise recently, and sometimes hits
        `failed to discover services, device disconnected` on the first
        connect after an idle period. Both clear after a quick scan and
        a second attempt.
        """
        address = self._require_address()
        async with self._lock:
            last_exc: Exception | None = None
            for attempt in range(1, _BLE_OP_RETRIES + 2):
                try:
                    device = await BleakScanner.find_device_by_address(
                        address, timeout=_PRIME_SCAN_SECONDS
                    )
                except Exception as exc:
                    logger.warning(
                        "%s: scanner failed on attempt %d/%d: %s",
                        op_name, attempt, _BLE_OP_RETRIES + 1, exc,
                    )
                    device = None
                if device is None:
                    last_exc = BleakDeviceNotFoundError(
                        address,
                        f"Ring {address} not advertising (attempt {attempt})",
                    )
                    logger.warning(
                        "%s: ring %s not visible on attempt %d/%d",
                        op_name, address, attempt, _BLE_OP_RETRIES + 1,
                    )
                    if attempt <= _BLE_OP_RETRIES:
                        await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
                        continue
                    raise last_exc

                client = Client(address)
                try:
                    async with client:
                        logger.debug(
                            "Ring op start: %s (attempt %d)", op_name, attempt
                        )
                        result = fn(client)
                        if asyncio.iscoroutine(result):
                            result = await result
                        logger.debug("Ring op done: %s", op_name)
                        return result
                except (BleakError, EOFError, asyncio.TimeoutError) as exc:
                    last_exc = exc
                    logger.warning(
                        "%s: BLE op failed on attempt %d/%d: %s: %s",
                        op_name, attempt, _BLE_OP_RETRIES + 1,
                        type(exc).__name__, exc,
                    )
                    if attempt <= _BLE_OP_RETRIES:
                        await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
                        continue
                    raise
                except Exception:
                    logger.exception("Ring op failed with non-BLE error: %s", op_name)
                    raise
            # unreachable — either return or raise above
            assert last_exc is not None
            raise last_exc

    async def refresh_status(self) -> Status:
        """Connect, read device info + battery, cache the result."""
        address = self._address
        if not address:
            self._last_status = Status(address="", paired=False, reachable=False,
                                       last_error="No ring paired")
            return self._last_status

        try:
            async def _read(client: Client) -> tuple[dict[str, str], Any]:
                info = await client.get_device_info()
                batt = await client.get_battery()
                return info, batt

            info, batt = await self._with_client("refresh_status", _read)
            status = Status(
                address=address,
                paired=True,
                reachable=True,
                battery_level=int(getattr(batt, "battery_level", 0) or 0),
                charging=bool(getattr(batt, "charging", False)),
                hw_version=info.get("hw_version"),
                fw_version=info.get("fw_version"),
                last_seen=datetime.now(tz=timezone.utc),
            )
        except Exception as exc:
            status = Status(address=address, paired=True, reachable=False,
                            last_error=f"{type(exc).__name__}: {exc}")
        self._last_status = status
        return status

    def cached_status(self) -> Status | None:
        return self._last_status

    async def stream_real_time(self, reading: real_time.RealTimeReading, stop_event: asyncio.Event):
        """Async generator yielding individual real-time samples.

        Wraps `Client.get_realtime_reading` in a loop so the ingress UI can
        show live values via SSE. Each poll takes several seconds; the
        caller stops the stream by setting `stop_event`."""
        address = self._require_address()
        async with self._lock:
            # Prime the BlueZ discovery cache before connecting — see
            # comment on _with_client() for why this is needed.
            device = await BleakScanner.find_device_by_address(
                address, timeout=_PRIME_SCAN_SECONDS
            )
            if device is None:
                yield {"error": f"Ring {address} not advertising"}
                return
            client = Client(address)
            try:
                async with client:
                    while not stop_event.is_set():
                        try:
                            samples = await client.get_realtime_reading(reading)
                        except Exception as exc:
                            logger.warning("real-time poll failed: %s", exc)
                            yield {"error": f"{type(exc).__name__}: {exc}"}
                            return
                        if samples is None:
                            yield {"error": "No reading (is the ring being worn?)"}
                            continue
                        yield {"samples": list(samples), "ts": datetime.now(tz=timezone.utc).isoformat()}
            except (BleakError, EOFError) as exc:
                logger.warning("real-time stream connect failed: %s", exc)
                yield {"error": f"{type(exc).__name__}: {exc}"}
