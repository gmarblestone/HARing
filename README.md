# HARing — Home Assistant Add-ons

Home Assistant Supervisor add-on repository for [Colmi R02](https://github.com/tahnok/colmi_r02_client) smart rings.

## Available add-ons

| Add-on | Version | Description |
| --- | --- | --- |
| [Colmi R02 Ring](./colmi_r02_ring) | 0.1.2 | Sync steps and heart rate from a Colmi R02 / R06 / R10 smart ring over BLE. Ingress web UI, scheduled sync, live heart-rate viewer, MQTT sensors. |

## Adding this repository to Home Assistant

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**.
2. Open the ⋮ menu (top right) → **Repositories**.
3. Add: `https://github.com/gmarblestone/HARing`.
4. Refresh the store; the **Colmi R02 Ring** add-on appears under the "HARing" heading.
5. Install and start it, then open the Web UI.

## Requirements

* Home Assistant OS or Home Assistant Supervised (add-ons don't run on Container / Core installs).
* A Bluetooth adapter on the Home Assistant host, within a few metres of the ring.

## Attribution

The BLE protocol library ([colmi_r02_client](./colmi_r02_ring/colmi_r02_client)) is a fork of [tahnok/colmi_r02_client](https://github.com/tahnok/colmi_r02_client) — full credit to Wesley Ellis and the reverse-engineering community.
