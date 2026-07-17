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

# Install the colmi_r02_client library + colmi_addon web app. We install
# editable so there is only one copy of the code and package data (the
# HTML templates and CSS in colmi_addon/static and colmi_addon/templates)
# stays alongside the source at /app/colmi_addon — otherwise pip's build
# isolation can produce a wheel that omits those directories on some
# poetry-core versions, causing /static/style.css to 404 at runtime.
COPY pyproject.toml README.md ./
COPY colmi_r02_client ./colmi_r02_client
COPY colmi_addon ./colmi_addon
RUN pip install --no-cache-dir -e . \
    && apk del --no-cache .build-deps

# Fail the build loudly if the static assets somehow weren't packaged.
RUN test -f /app/colmi_addon/static/style.css \
    && test -f /app/colmi_addon/templates/base.html

# Add-on runtime files
COPY run.sh /run.sh
RUN chmod a+x /run.sh

EXPOSE 8099

CMD ["/run.sh"]
