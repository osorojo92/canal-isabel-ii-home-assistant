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
        nginx \
        openbox \
        websockify \
        x11vnc \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir playwright==1.61.0

# noVNC oficial 1.6.0
RUN python3 - <<'PY'
import tarfile
import urllib.request
from pathlib import Path

url = "https://github.com/novnc/noVNC/archive/refs/tags/v1.6.0.tar.gz"
archive = Path("/tmp/novnc.tar.gz")

urllib.request.urlretrieve(url, archive)

with tarfile.open(archive, "r:gz") as tar:
    tar.extractall("/tmp")

Path("/opt/novnc").mkdir(parents=True, exist_ok=True)

source = Path("/tmp/noVNC-1.6.0")

for item in source.iterdir():
    item.rename(Path("/opt/novnc") / item.name)

archive.unlink()
PY

COPY canal_playwright.py /app/canal_playwright.py
COPY auth_browser.py /app/auth_browser.py

COPY nginx.conf /etc/nginx/nginx.conf
COPY vnc-ha.html /opt/novnc/vnc-ha.html

COPY run.sh /run.sh

RUN chmod a+x /run.sh

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

CMD ["/run.sh"]