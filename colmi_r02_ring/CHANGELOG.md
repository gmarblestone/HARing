# Changelog

## 0.1.4

* Fix BleakDeviceNotFoundError on refresh status and
  "failed to discover services, device disconnected" on sync when
  running on BlueZ inside Home Assistant OS. `RingManager` now primes
  the adapter's discovery cache with `find_device_by_address` before
  every connect and retries transient BLE errors twice with a short
  backoff.
* `SyncService` now routes its connection through the same helper
  (`RingManager.with_connected_client`) so scheduled and manual syncs
  get the same scan-and-retry treatment.
* Real-time HR stream also primes the cache before opening the SSE
  session.

## 0.1.3

* Remove the shipped `apparmor.txt` profile. It only granted read
  (`/** rmix`) which blocked s6-overlay in the HA base image from
  writing `/run/s6` and `/run/service` at startup, causing the add-on
  container to exit with `s6-overlay-suexec: fatal: child failed with
  exit code 111`. Falling back to Home Assistant's default AppArmor
  profile lets s6 initialise normally.

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
