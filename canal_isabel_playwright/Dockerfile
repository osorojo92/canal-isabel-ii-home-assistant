ARG BUILD_VERSION
ARG BUILD_ARCH

FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

ENV PYTHONUNBUFFERED=1
ENV TZ=Europe/Madrid

WORKDIR /app

RUN pip install --no-cache-dir playwright==1.61.0

COPY canal_playwright.py /app/canal_playwright.py
COPY run.sh /run.sh

RUN chmod a+x /run.sh

CMD ["/run.sh"]