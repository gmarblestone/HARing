# Changelog

## 0.1.2

* Restructure the repository into a proper Home Assistant add-on
  repository: `repository.yaml` at root, add-on files moved to
  `colmi_r02_ring/`. This fixes "not a valid add-on repository" when
  adding the URL to HA.

## 0.1.1

* Persist UI-paired ring address via the Supervisor API
  (`POST /addons/self/options`) so pairings survive add-on restarts.
* Show a dashboard banner when persistence isn't available (local dev
  outside Supervisor, or API errors).
* Redact `SUPERVISOR_TOKEN` from the startup config log.

## 0.1.0 — initial add-on release

First release of the Home Assistant add-on layer on top of the existing
`colmi_r02_client` Python library.

Features:

* Ingress web UI (dashboard, pair, live HR, charts)
* BLE scan and pair from the browser
* Manual and scheduled sync into a local SQLite database
* Server-Sent Events stream for real-time heart rate
* Chart.js visualisation for steps (bar) and HR (line)
* MQTT discovery + state publishing (battery, charging, reachable, firmware, last seen)
* AppArmor profile, Alpine base, multi-arch build map
