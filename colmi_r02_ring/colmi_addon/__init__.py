"""Home Assistant add-on for the Colmi R02 smart ring.

The `colmi_addon` package layers a FastAPI web UI and background services
(scheduled sync, MQTT publisher) on top of the existing `colmi_r02_client`
library. It's designed to run inside a Home Assistant Supervisor add-on
container with ingress enabled.
"""

__version__ = "0.1.5"
