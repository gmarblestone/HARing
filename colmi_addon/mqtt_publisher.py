"""Publish ring readings to Home Assistant via MQTT discovery.

When the Supervisor has granted MQTT access, the add-on publishes:

  * `<discovery>/sensor/colmi_<slug>_battery/config`
  * `<discovery>/binary_sensor/colmi_<slug>_charging/config`
  * `<discovery>/sensor/colmi_<slug>_hw_version/config`
  * `<discovery>/sensor/colmi_<slug>_fw_version/config`
  * `<discovery>/sensor/colmi_<slug>_last_sync/config`

State is published to `colmi_r02/<slug>/state` as a JSON blob, and each
sensor's `state_topic` uses a value_template to pull its field out. This
matches the standard HA MQTT discovery pattern for grouped sensors.

If MQTT isn't available or isn't enabled, `MqttPublisher.enabled` stays
False and all publish calls are no-ops.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import asdict
from typing import Any

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover — the addon requirements include it
    mqtt = None  # type: ignore[assignment]

from .config import AddonConfig
from .ring_manager import Status

logger = logging.getLogger(__name__)


def _slugify(address: str) -> str:
    """Turn a BLE address into an MQTT-safe object id."""
    return re.sub(r"[^a-z0-9]+", "", address.lower()) or "ring"


class MqttPublisher:
    def __init__(self, config: AddonConfig) -> None:
        self._config = config
        self._client: Any = None
        self._connected = threading.Event()
        self._discovery_sent_for: str | None = None

    @property
    def enabled(self) -> bool:
        return self._config.mqtt_available and mqtt is not None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if not self.enabled:
            logger.info("MQTT publisher disabled (mqtt_enabled=%s, host=%r)",
                        self._config.mqtt_enabled, self._config.mqtt_host)
            return
        assert mqtt is not None
        client = mqtt.Client(client_id=f"colmi_r02_addon", protocol=mqtt.MQTTv5)
        if self._config.mqtt_username:
            client.username_pw_set(self._config.mqtt_username, self._config.mqtt_password)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.will_set(self._availability_topic("ring"), payload="offline", qos=1, retain=True)
        try:
            client.connect_async(self._config.mqtt_host, self._config.mqtt_port, keepalive=60)
            client.loop_start()
        except Exception as exc:
            logger.error("MQTT connect failed: %s", exc)
            return
        self._client = client
        logger.info("MQTT publisher started (%s:%d)", self._config.mqtt_host, self._config.mqtt_port)

    def stop(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            logger.debug("MQTT stop errored", exc_info=True)

    def _on_connect(self, _client, _userdata, _flags, reason_code, _props=None) -> None:
        if reason_code == 0:
            self._connected.set()
            logger.info("MQTT connected")
        else:
            logger.warning("MQTT connect returned reason_code=%s", reason_code)

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _props=None) -> None:
        self._connected.clear()
        logger.info("MQTT disconnected (reason_code=%s)", reason_code)

    # -- topic helpers -----------------------------------------------------

    def _state_topic(self, slug: str) -> str:
        return f"colmi_r02/{slug}/state"

    def _availability_topic(self, slug: str) -> str:
        return f"colmi_r02/{slug}/availability"

    def _discovery_topic(self, component: str, slug: str, sensor: str) -> str:
        prefix = self._config.mqtt_discovery_prefix.strip("/")
        return f"{prefix}/{component}/colmi_{slug}/{sensor}/config"

    # -- publishing --------------------------------------------------------

    def publish_status(self, status: Status) -> None:
        if not self.enabled or self._client is None:
            return
        if not status.address:
            return
        slug = _slugify(status.address)
        if self._discovery_sent_for != slug:
            self._send_discovery(slug, status.address)
            self._discovery_sent_for = slug

        payload = {
            "battery_level": status.battery_level,
            "charging": "ON" if status.charging else "OFF",
            "reachable": "ON" if status.reachable else "OFF",
            "hw_version": status.hw_version,
            "fw_version": status.fw_version,
            "last_seen": status.last_seen.isoformat() if status.last_seen else None,
            "last_error": status.last_error,
        }
        try:
            self._client.publish(
                self._state_topic(slug),
                json.dumps(payload, default=str),
                qos=1,
                retain=True,
            )
            self._client.publish(
                self._availability_topic(slug),
                "online" if status.reachable else "offline",
                qos=1,
                retain=True,
            )
        except Exception:
            logger.exception("MQTT publish_status failed")

    def _send_discovery(self, slug: str, address: str) -> None:
        assert self._client is not None
        device = {
            "identifiers": [f"colmi_r02_{slug}"],
            "name": f"Colmi R02 ({address})",
            "manufacturer": "Colmi",
            "model": "R02 / R06 / R10",
        }
        state_topic = self._state_topic(slug)
        availability_topic = self._availability_topic(slug)

        sensors: list[tuple[str, str, dict[str, Any]]] = [
            (
                "sensor", "battery",
                {
                    "name": "Battery",
                    "device_class": "battery",
                    "state_class": "measurement",
                    "unit_of_measurement": "%",
                    "value_template": "{{ value_json.battery_level }}",
                },
            ),
            (
                "binary_sensor", "charging",
                {
                    "name": "Charging",
                    "device_class": "battery_charging",
                    "value_template": "{{ value_json.charging }}",
                    "payload_on": "ON",
                    "payload_off": "OFF",
                },
            ),
            (
                "binary_sensor", "reachable",
                {
                    "name": "Reachable",
                    "device_class": "connectivity",
                    "value_template": "{{ value_json.reachable }}",
                    "payload_on": "ON",
                    "payload_off": "OFF",
                },
            ),
            (
                "sensor", "firmware",
                {
                    "name": "Firmware",
                    "value_template": "{{ value_json.fw_version }}",
                    "entity_category": "diagnostic",
                },
            ),
            (
                "sensor", "last_seen",
                {
                    "name": "Last seen",
                    "device_class": "timestamp",
                    "value_template": "{{ value_json.last_seen }}",
                    "entity_category": "diagnostic",
                },
            ),
        ]

        for component, sensor_id, extra in sensors:
            payload = {
                "unique_id": f"colmi_r02_{slug}_{sensor_id}",
                "object_id": f"colmi_r02_{slug}_{sensor_id}",
                "state_topic": state_topic,
                "availability_topic": availability_topic,
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": device,
                **extra,
            }
            self._client.publish(
                self._discovery_topic(component, slug, sensor_id),
                json.dumps(payload),
                qos=1,
                retain=True,
            )
        logger.info("MQTT discovery published for %s", slug)
