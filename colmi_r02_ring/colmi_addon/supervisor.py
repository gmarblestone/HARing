"""Thin client for the Home Assistant Supervisor REST API.

Inside a Supervisor-managed add-on the Supervisor injects a
`SUPERVISOR_TOKEN` env var and exposes its API at http://supervisor. We use
it only to persist the paired ring address into the add-on's own options,
so a UI-driven pairing survives a container restart.

If `SUPERVISOR_TOKEN` isn't present (local development, or someone running
the FastAPI app outside a Supervisor add-on) the client reports itself as
unavailable and all calls become explicit no-ops handled by the caller.
"""

from __future__ import annotations

import asyncio
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class SupervisorClient:
    def __init__(self, token: str, base_url: str = "http://supervisor") -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")

    @property
    def available(self) -> bool:
        return bool(self._token)

    async def update_addon_options(self, options: dict) -> None:
        """Overwrite the add-on's own `options` block (persists to
        `/data/options.json` for us). Raises RuntimeError on failure so the
        caller can surface a warning."""
        if not self.available:
            raise RuntimeError("Supervisor API not available")

        url = f"{self._base_url}/addons/self/options"
        body = json.dumps({"options": options}).encode("utf-8")
        request = Request(
            url,
            method="POST",
            data=body,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )

        # urllib is blocking; punt to a worker thread so we don't block the
        # event loop.
        def _do_request() -> tuple[int, str]:
            try:
                with urlopen(request, timeout=10) as resp:
                    return resp.status, resp.read().decode("utf-8", errors="replace")
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
                raise RuntimeError(f"Supervisor returned HTTP {exc.code}: {detail}") from exc
            except URLError as exc:
                raise RuntimeError(f"Supervisor unreachable: {exc.reason}") from exc

        status, payload = await asyncio.to_thread(_do_request)
        logger.info("Supervisor update_addon_options -> %s", status)
        if status >= 300:
            raise RuntimeError(f"Supervisor returned HTTP {status}: {payload}")
