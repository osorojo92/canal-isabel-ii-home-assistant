ARG BUILD_VERSION
ARG BUILD_ARCH

FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

ARG BUILD_VERSION
ARG BUILD_ARCH

ENV ADDON_VERSION="${BUILD_VERSION}"
ENV PYTHONUNBUFFERED=1
ENV TZ=Europe/Madrid
ENV DISPLAY=:99

WORKDIR /app

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        dbus-x11 \
        fonts-liberation \
        git \
        openbox \
        websockify \
        x11vnc \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

# Playwright Python debe coincidir con la imagen base
RUN pip install --no-cache-dir playwright==1.61.0

# noVNC 1.6.0:
# incluye soporte para URLs WebSocket relativas,
# necesario detrás de Home Assistant Ingress.
RUN git clone \
        --depth 1 \
        --branch v1.6.0 \
        https://github.com/novnc/noVNC.git \
        /opt/novnc \
    && rm -rf /opt/novnc/.git

RUN printf '%s\n' \
    '{' \
    '  "host": "",' \
    '  "port": 0,' \
    '  "path": "websockify",' \
    '  "autoconnect": true' \
    '}' \
    > /opt/novnc/mandatory.json

COPY canal_playwright.py /app/canal_playwright.py
COPY auth_browser.py /app/auth_browser.py
COPY run.sh /run.sh

RUN chmod a+x /run.sh

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

CMD ["/run.sh"]