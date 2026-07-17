#!/command/with-contenv sh
# Entrypoint for the Colmi R02 Ring Home Assistant add-on.
#
# The `with-contenv` shebang is critical: the HA add-on base image uses
# s6-overlay v3 as PID 1, which by default runs CMD with a stripped
# environment. Without with-contenv the container's env vars
# (SUPERVISOR_TOKEN, MQTTHOST, HOSTNAME, ...) are all empty inside this
# script, which broke Supervisor API pairing persistence and MQTT.
#
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

# MQTT credentials are NOT injected as env vars by the Supervisor. They
# have to be fetched at runtime from GET http://supervisor/services/mqtt
# using SUPERVISOR_TOKEN. The addon does that in its FastAPI lifespan.
# The fallbacks below only matter for local development where you want
# to point at an external broker without going through the Supervisor.
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
