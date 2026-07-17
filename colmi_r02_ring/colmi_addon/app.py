"""FastAPI application served through Home Assistant ingress.

Route summary:

  GET  /                    dashboard (status + sync button)
  GET  /pair                pairing page (scan + pick)
  POST /pair                set the ring address
  GET  /live                live heart-rate SSE viewer
  GET  /charts              historical charts page
  GET  /api/status          JSON current status (uses cache)
  POST /api/status/refresh  force a status refresh
  POST /api/scan            scan and return device list
  POST /api/sync            trigger a manual sync
  GET  /api/sync/last       result of most recent sync
  GET  /api/data/steps      JSON step totals by day
  GET  /api/data/hr         JSON heart-rate samples
  GET  /api/live/hr         Server-Sent Events stream of real-time HR

The ingress middleware pulls the `X-Ingress-Path` header (set by the HA
proxy) into `request.scope["root_path"]` so redirects and generated links
resolve under the ingress path.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from colmi_r02_client import real_time

from . import __version__, data
from .config import AddonConfig
from .mqtt_publisher import MqttPublisher
from .ring_manager import RingManager
from .supervisor import SupervisorClient
from .sync_service import SyncService

logger = logging.getLogger("colmi_addon")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _configure_logging(level: str) -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    # Turn down bleak's chatter unless the user asked for debug.
    if numeric > logging.DEBUG:
        logging.getLogger("bleak").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = AddonConfig.from_env()
    _configure_logging(cfg.log_level)
    logger.info("Starting Colmi R02 add-on v%s", __version__)

    # Diagnostic: which of the Supervisor / HA-related env vars are set?
    # This helps explain 'supervisor: no' when hassio_api is on. We log
    # presence only, never the value.
    import os as _os
    supervisor_env_hints = {
        name: ("present" if _os.environ.get(name) else "empty/missing")
        for name in ("SUPERVISOR_TOKEN", "HASSIO_TOKEN", "HASSIO_API",
                     "SUPERVISOR_API", "HOSTNAME")
    }
    logger.info("Supervisor env vars: %s", supervisor_env_hints)

    # Diagnostic: confirm the static asset directory shipped in the image
    # and log its contents. Emitted here (not at module import) so it
    # runs after logging is configured.
    if _STATIC_DIR.is_dir():
        logger.info(
            "Static mount: %s (files: %s)",
            _STATIC_DIR, sorted(p.name for p in _STATIC_DIR.iterdir()),
        )
    else:
        logger.error(
            "Static directory not found at %s — /static/* will 404.",
            _STATIC_DIR,
        )

    safe_cfg = {
        k: v for k, v in asdict(cfg).items()
        if "password" not in k and "token" not in k
    }
    safe_cfg["supervisor"] = "yes" if cfg.supervisor_token else "no"
    logger.info("Config: %s", safe_cfg)

    ring = RingManager(address=cfg.address)
    sync = SyncService(ring=ring, db_path=cfg.db_path)
    mqtt_pub = MqttPublisher(cfg)
    mqtt_pub.start()
    supervisor = SupervisorClient(cfg.supervisor_token)

    app.state.config = cfg
    app.state.ring = ring
    app.state.sync = sync
    app.state.mqtt = mqtt_pub
    app.state.supervisor = supervisor

    if cfg.auto_sync_enabled:
        sync.start_scheduler(cfg.auto_sync_minutes)

    try:
        yield
    finally:
        logger.info("Shutting down")
        await sync.stop_scheduler()
        mqtt_pub.stop()


app = FastAPI(title="Colmi R02 Ring", version=__version__, lifespan=lifespan)

# Static assets are served via an explicit FastAPI route rather than
# `app.mount("/static", StaticFiles(...))`. StaticFiles as a mount kept
# returning 404 under HA ingress for reasons we couldn't diagnose
# (mount registered, directory + file present, path matches — see
# 0.1.6/0.1.7 investigation). A plain route with FileResponse is
# simpler and works. Path is constrained to files inside _STATIC_DIR
# to prevent traversal.
_STATIC_DIR = (BASE_DIR / "static").resolve()


@app.get("/static/{path:path}", include_in_schema=False)
async def static_files(path: str):
    candidate = (_STATIC_DIR / path).resolve()
    try:
        candidate.relative_to(_STATIC_DIR)
    except ValueError:
        raise HTTPException(status_code=404)
    if not candidate.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(candidate)


# ---------------------------------------------------------------------------
# Ingress support
# ---------------------------------------------------------------------------

@app.middleware("http")
async def ingress_root_path(request: Request, call_next):
    """Populate `request.scope['root_path']` from HA's ingress header so
    that redirects and `url_for` generate URLs that resolve through the
    ingress proxy. Home Assistant sends the base path in `X-Ingress-Path`."""
    ingress_path = request.headers.get("x-ingress-path", "").rstrip("/")
    if ingress_path:
        request.scope["root_path"] = ingress_path
    response = await call_next(request)
    return response


def _ring(request: Request) -> RingManager:
    return request.app.state.ring


def _sync(request: Request) -> SyncService:
    return request.app.state.sync


def _cfg(request: Request) -> AddonConfig:
    return request.app.state.config


def _mqtt(request: Request) -> MqttPublisher:
    return request.app.state.mqtt


def _supervisor(request: Request) -> SupervisorClient:
    return request.app.state.supervisor


# ---------------------------------------------------------------------------
# HTML pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    ring = _ring(request)
    sync = _sync(request)
    status = ring.cached_status()
    return TEMPLATES.TemplateResponse(
        "index.html",
        {
            "request": request,
            "status": status,
            "address": ring.address,
            "last_sync": sync.last,
            "sync_running": sync.running,
            "auto_sync_enabled": _cfg(request).auto_sync_enabled,
            "auto_sync_minutes": _cfg(request).auto_sync_minutes,
            "supervisor_available": _supervisor(request).available,
            "warn": request.query_params.get("warn", ""),
        },
    )


@app.get("/pair", response_class=HTMLResponse)
async def pair_page(request: Request):
    return TEMPLATES.TemplateResponse(
        "pair.html",
        {"request": request, "address": _ring(request).address},
    )


@app.post("/pair")
async def pair_submit(request: Request, address: str = Form(...)):
    ring = _ring(request)
    address = address.strip()
    ring.set_address(address)

    # Persist the address to the add-on's own options so it survives
    # container restarts. The write is best-effort: if the Supervisor API
    # isn't reachable (local dev, or a transient error) we still keep the
    # in-memory address so the current session works, and surface a hint
    # via the ?warn= query param.
    supervisor = _supervisor(request)
    warn = ""
    if supervisor.available:
        try:
            new_options = _cfg(request).as_options_dict()
            new_options["address"] = address
            await supervisor.update_addon_options(new_options)
        except Exception as exc:
            logger.warning("Failed to persist address via Supervisor: %s", exc)
            warn = "persist_failed"
    else:
        logger.info("Supervisor API unavailable; address stored in memory only")
        warn = "no_supervisor"

    # Immediately connect once to confirm the ring is reachable and
    # populate the dashboard with battery / firmware right away, so the
    # user doesn't have to click "Refresh status" after pairing. Any
    # BLE error here is non-fatal — the pairing itself already
    # succeeded, and the failure is stored in status.last_error which
    # the dashboard renders.
    paired_flag = ""
    try:
        status = await ring.refresh_status()
        if status.reachable:
            paired_flag = "paired_ok"
            logger.info(
                "Pair probe ok: %s battery=%s%% fw=%s",
                address, status.battery_level, status.fw_version,
            )
        else:
            paired_flag = "paired_unreachable"
            logger.warning(
                "Pair probe: address saved but ring unreachable: %s",
                status.last_error,
            )
    except Exception as exc:  # noqa: BLE001
        paired_flag = "paired_unreachable"
        logger.warning("Pair probe raised: %s", exc)

    # Prefer the warn banner (persistence problem) over the paired
    # banner because the persistence issue is more important to see.
    query = warn or paired_flag
    target = "./" if not query else f"./?warn={query}"
    return RedirectResponse(url=target, status_code=303)


@app.get("/live", response_class=HTMLResponse)
async def live_page(request: Request):
    return TEMPLATES.TemplateResponse(
        "live.html",
        {"request": request, "address": _ring(request).address},
    )


@app.get("/charts", response_class=HTMLResponse)
async def charts_page(request: Request):
    return TEMPLATES.TemplateResponse(
        "charts.html",
        {"request": request, "address": _ring(request).address},
    )


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@app.get("/api/status")
async def api_status(request: Request):
    status = _ring(request).cached_status()
    if status is None:
        return {"status": None}
    return {"status": asdict(status)}


@app.post("/api/status/refresh")
async def api_status_refresh(request: Request):
    ring = _ring(request)
    status = await ring.refresh_status()
    _mqtt(request).publish_status(status)
    return {"status": asdict(status)}


@app.post("/api/scan")
async def api_scan(request: Request, seconds: int | None = None, include_all: bool = False):
    ring = _ring(request)
    cfg = _cfg(request)
    duration = seconds if seconds and seconds > 0 else cfg.scan_seconds
    devices = await ring.scan(seconds=duration, include_all=include_all)
    return {"devices": [asdict(d) for d in devices]}


@app.post("/api/sync")
async def api_sync(request: Request, days_back: int | None = None):
    sync = _sync(request)
    if sync.running:
        raise HTTPException(status_code=409, detail="A sync is already in progress")
    result = await sync.run_once(days_back=days_back)
    # Refresh + publish status after a successful sync so MQTT sensors update.
    if result.ok:
        try:
            status = await _ring(request).refresh_status()
            _mqtt(request).publish_status(status)
        except Exception:
            logger.exception("post-sync status refresh failed")
    return {"result": _sync_result_to_dict(result)}


@app.get("/api/sync/last")
async def api_sync_last(request: Request):
    last = _sync(request).last
    return {"result": _sync_result_to_dict(last) if last is not None else None}


def _sync_result_to_dict(result) -> dict:
    return {
        "ok": result.ok,
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
        "duration_seconds": result.duration_seconds,
        "start_range": result.start_range.isoformat(),
        "end_range": result.end_range.isoformat(),
        "hr_days": result.hr_days,
        "step_days": result.step_days,
        "error": result.error,
    }


@app.get("/api/data/steps")
async def api_data_steps(request: Request, days: int = 14):
    cfg = _cfg(request)
    address = _ring(request).address
    if not address:
        return {"days": days, "points": []}
    points = data.get_daily_steps(cfg.db_path, address, days=days)
    return {"days": days, "points": [asdict(p) for p in points]}


@app.get("/api/data/hr")
async def api_data_hr(request: Request, days: int = 3):
    cfg = _cfg(request)
    address = _ring(request).address
    if not address:
        return {"days": days, "points": []}
    points = data.get_heart_rate_series(cfg.db_path, address, days=days)
    return {"days": days, "points": [asdict(p) for p in points]}


# ---------------------------------------------------------------------------
# SSE: live heart rate
# ---------------------------------------------------------------------------

@app.get("/api/live/hr")
async def api_live_hr(request: Request):
    ring = _ring(request)
    if not ring.address:
        raise HTTPException(status_code=400, detail="No ring paired")

    stop = asyncio.Event()

    async def event_stream():
        try:
            async for msg in ring.stream_real_time(real_time.RealTimeReading.HEART_RATE, stop):
                if await request.is_disconnected():
                    stop.set()
                    break
                yield {"event": "hr", "data": json.dumps(msg)}
        except Exception as exc:
            logger.exception("live hr stream errored")
            yield {"event": "error", "data": json.dumps({"error": str(exc)})}
        finally:
            stop.set()

    return EventSourceResponse(event_stream())
