# Colmi R02 Ring — Home Assistant Add-on

Read data from a Colmi R02 (or R06 / R10) smart ring directly on Home Assistant OS, with an ingress dashboard, scheduled sync, and optional MQTT sensors.

## Requirements

* Home Assistant OS or Home Assistant Supervised (add-ons don't run on Container / Core installs).
* A working Bluetooth adapter on the Home Assistant host (built-in or USB).
* The ring physically within BLE range of the HA host (a few metres).

## Installation

1. Copy this repository (or its contents) into `/addons/colmi_r02_ring/` on the HA OS host, or add it to a custom add-on repository.
2. In Home Assistant, go to **Settings → Add-ons → Add-on Store**, refresh, and install **Colmi R02 Ring**.
3. Start the add-on. The **Open Web UI** button takes you to the ingress dashboard.

## Configuration

| Option | Default | Description |
| --- | --- | --- |
| `address` | `""` | Bluetooth address of your ring (e.g. `30:38:46:34:40:07`). Can also be set from the Pair page. |
| `scan_seconds` | `8` | How long each BLE scan runs. |
| `auto_sync_enabled` | `true` | Whether the scheduled sync runs. |
| `auto_sync_minutes` | `30` | Interval between auto-syncs. Set to `0` to disable. |
| `mqtt_enabled` | `true` | Publish ring status as MQTT sensors (requires the MQTT integration in HA). |
| `mqtt_discovery_prefix` | `homeassistant` | MQTT discovery prefix. Match your MQTT integration setting. |
| `log_level` | `info` | Uvicorn/app log level. `debug` enables verbose BLE logging. |

## First use

1. Open the add-on's web UI.
2. Go to **Pair**, click **Scan**, and pair your ring. If the ring's name (e.g. `COLMI R02_...`) isn't listed, tick "Show all BLE devices".
3. Click **Refresh status** on the dashboard — you should see battery, firmware, and hardware info.
4. Click **Sync now** to pull step and heart-rate history into the local SQLite database (`/data/ring_data.sqlite` in the add-on).
5. Visit **Charts** to see step totals and HR samples over the last 7 days.

## MQTT sensors

When the MQTT service is available and `mqtt_enabled` is on, the add-on publishes discovery configs at `homeassistant/sensor/colmi_<slug>/…` and state to `colmi_r02/<slug>/state`. Sensors exposed:

* `Colmi R02 Battery` (percentage, `device_class: battery`)
* `Colmi R02 Charging` (binary sensor, `device_class: battery_charging`)
* `Colmi R02 Reachable` (binary sensor, `device_class: connectivity`)
* `Colmi R02 Firmware` (diagnostic)
* `Colmi R02 Last seen` (timestamp)

State is refreshed on every status refresh (manual button) and after every sync.

## Live heart rate

The **Live HR** page opens a Server-Sent Events stream and polls real-time heart rate from the ring. This holds the BLE connection open until you close it, so scheduled sync and status refresh are paused during the stream.

## Troubleshooting

* **Scan finds nothing**: Verify the HA host's Bluetooth adapter with `bluetoothctl` in the host terminal. USB BT dongles sometimes need to be re-plugged.
* **Sync stalls**: BLE is finicky. Kill the sync (restart the add-on) and try again with the ring closer.
* **`No ring paired`**: Enter the address in the Configuration tab, or use the Pair page.
* **MQTT sensors don't appear**: Ensure the MQTT add-on is running and the MQTT integration is set up in HA. Check the add-on log for `MQTT connected`.

## Storage

* Ring data: `/data/ring_data.sqlite` (survives add-on updates and restarts).
* Add-on options: `/data/options.json` (managed by the Supervisor).

## Uninstalling

Stopping and uninstalling the add-on leaves `/data/ring_data.sqlite` intact within Supervisor snapshots. To wipe data, delete `/data/ring_data.sqlite` before uninstall.
