#!/usr/bin/env sh
# Entrypoint for the Colmi R02 Ring Home Assistant add-on.
# Reads /data/options.json (populated by the Supervisor from the add-on's
# `options` schema) and exports them into the environment before starting
# the uvicorn server.
set -eu

OPTIONS_FILE="/data/options.json"
if [ ! -f "${OPTIONS_FILE}" ]; then
    echo "run.sh: ${OPTIONS_FILE} not found; using defaults" >&2
    OPTIONS_FILE=""
fi

# Export options as COLMI_* env vars. Done in Python because /bin/sh has no
# JSON parser and we don't want to pull in jq just for this.
if [ -n "${OPTIONS_FILE}" ]; then
    eval "$(python3 - <<'PY'
import json, os, shlex, sys
try:
    with open("/data/options.json", "r", encoding="utf-8") as fh:
        opts = json.load(fh)
except Exception as exc:
    print(f"echo run.sh: failed to parse options.json: {exc} >&2", flush=True)
    sys.exit(0)
for key, value in opts.items():
    env_key = "COLMI_" + key.upper()
    if isinstance(value, bool):
        env_value = "1" if value else "0"
    elif value is None:
        env_value = ""
    else:
        env_value = str(value)
    print(f"export {env_key}={shlex.quote(env_value)}")
PY
)"
fi

# HA Supervisor injects these when services: mqtt:want is granted access.
: "${MQTTHOST:=${MQTT_HOST:-}}"
: "${MQTTPORT:=${MQTT_PORT:-1883}}"
: "${MQTTUSERNAME:=${MQTT_USERNAME:-}}"
: "${MQTTPASSWORD:=${MQTT_PASSWORD:-}}"
export MQTTHOST MQTTPORT MQTTUSERNAME MQTTPASSWORD

# Persist the SQLite database under /data so it survives add-on restarts.
export COLMI_DB_PATH="/data/ring_data.sqlite"

LOG_LEVEL_UVICORN="${COLMI_LOG_LEVEL:-info}"

echo "run.sh: starting Colmi R02 add-on (log level: ${LOG_LEVEL_UVICORN})"
exec python3 -m uvicorn \
    colmi_addon.app:app \
    --host 0.0.0.0 \
    --port 8099 \
    --log-level "${LOG_LEVEL_UVICORN}" \
    --proxy-headers \
    --forwarded-allow-ips "*"
