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

    async def get_mqtt_service(self) -> dict | None:
        """Fetch MQTT broker credentials from the Supervisor's services API.

        Returns a dict with keys like ``host``, ``port``, ``username``,
        ``password``, ``ssl``, ``protocol`` when the MQTT service is
        provisioned for this add-on, or ``None`` when the token is missing
        or the Supervisor reports the service as unavailable (e.g. no MQTT
        broker is installed, or the add-on isn't granted access).

        Requires ``services: - mqtt:want`` (or ``mqtt:need``) in config.yaml
        so the Supervisor exposes the endpoint to this add-on.
        """
        if not self.available:
            return None

        url = f"{self._base_url}/services/mqtt"
        request = Request(
            url,
            method="GET",
            headers={"Authorization": f"Bearer {self._token}"},
        )

        def _do_request() -> tuple[int, str]:
            try:
                with urlopen(request, timeout=10) as resp:
                    return resp.status, resp.read().decode("utf-8", errors="replace")
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
                return exc.code, detail
            except URLError as exc:
                raise RuntimeError(f"Supervisor unreachable: {exc.reason}") from exc

        try:
            status, payload = await asyncio.to_thread(_do_request)
        except RuntimeError as exc:
            logger.warning("Supervisor get_mqtt_service failed: %s", exc)
            return None

        if status >= 300:
            logger.info("Supervisor /services/mqtt returned HTTP %s (no MQTT service?)", status)
            return None

        try:
            body = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning("Supervisor /services/mqtt returned non-JSON body")
            return None

        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict) or not data.get("host"):
            logger.info("Supervisor /services/mqtt has no host in response")
            return None
        return data
