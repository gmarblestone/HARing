"""Runtime configuration loaded from environment variables.

The `run.sh` entrypoint reads `/data/options.json` (the Supervisor-populated
options file) and exports each option as `COLMI_<UPPER_KEY>`. This module
translates those raw strings into a typed dataclass consumed by the rest of
the add-on.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_str(name: str, default: str = "") -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip()


@dataclass(frozen=True)
class AddonConfig:
    address: str
    scan_seconds: int
    auto_sync_minutes: int
    auto_sync_enabled: bool
    mqtt_enabled: bool
    mqtt_discovery_prefix: str
    db_path: Path
    log_level: str
    # MQTT connection details injected by the Supervisor when the add-on has
    # been granted access to the mqtt service.
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str

    @classmethod
    def from_env(cls) -> "AddonConfig":
        return cls(
            address=_get_str("COLMI_ADDRESS"),
            scan_seconds=_get_int("COLMI_SCAN_SECONDS", 8),
            auto_sync_minutes=_get_int("COLMI_AUTO_SYNC_MINUTES", 30),
            auto_sync_enabled=_get_bool("COLMI_AUTO_SYNC_ENABLED", True),
            mqtt_enabled=_get_bool("COLMI_MQTT_ENABLED", True),
            mqtt_discovery_prefix=_get_str("COLMI_MQTT_DISCOVERY_PREFIX", "homeassistant"),
            db_path=Path(_get_str("COLMI_DB_PATH", "/data/ring_data.sqlite")),
            log_level=_get_str("COLMI_LOG_LEVEL", "info"),
            mqtt_host=_get_str("MQTTHOST"),
            mqtt_port=_get_int("MQTTPORT", 1883),
            mqtt_username=_get_str("MQTTUSERNAME"),
            mqtt_password=_get_str("MQTTPASSWORD"),
        )

    @property
    def mqtt_available(self) -> bool:
        """True when the Supervisor gave us MQTT credentials AND the user
        hasn't disabled the integration in add-on options."""
        return self.mqtt_enabled and bool(self.mqtt_host)
