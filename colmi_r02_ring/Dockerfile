# syntax=docker/dockerfile:1
ARG BUILD_FROM
FROM ${BUILD_FROM}

ENV \
    LANG="C.UTF-8" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# BlueZ + D-Bus client libraries so bleak can talk to the host BlueZ over
# D-Bus. build-base + python headers are only needed transiently while pip
# builds any wheels that lack a musl arm build.
RUN apk add --no-cache \
        bluez \
        bluez-libs \
        dbus \
        dbus-libs \
    && apk add --no-cache --virtual .build-deps \
        build-base \
        python3-dev \
        libffi-dev \
        openssl-dev

WORKDIR /app

# Install Python deps first so image layers cache well.
COPY requirements-addon.txt ./
RUN pip install --no-cache-dir -r requirements-addon.txt

# Install the local colmi_r02_client package (library) alongside the web app.
COPY pyproject.toml README.md ./
COPY colmi_r02_client ./colmi_r02_client
COPY colmi_addon ./colmi_addon
RUN pip install --no-cache-dir . \
    && apk del --no-cache .build-deps

# Add-on runtime files
COPY run.sh /run.sh
RUN chmod a+x /run.sh

EXPOSE 8099

CMD ["/run.sh"]
