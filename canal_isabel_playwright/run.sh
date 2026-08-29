#!/bin/bash

set -u

export DISPLAY=:99


# ============================================================
# LEER OPCIONES HOME ASSISTANT
# ============================================================

read_option() {

    local key="$1"
    local default="$2"

    python3 - "$key" "$default" <<'PY'

import json
import sys

key = sys.argv[1]
default = sys.argv[2]

try:

    with open(
        "/data/options.json",
        "r",
        encoding="utf-8",
    ) as f:

        options = json.load(f)

    value = options.get(
        key,
        default,
    )

except Exception:

    value = default

print(value)

PY
}


MODE="$(read_option mode auto)"
INTERVAL_HOURS="$(read_option interval_hours 24)"
STARTUP_DELAY="$(read_option startup_delay 30)"

INTERVAL_SECONDS=$((INTERVAL_HOURS * 3600))


# ============================================================
# LIMPIEZA
# ============================================================

cleanup() {

    echo
    echo "Cerrando procesos..."

    local pids

    pids="$(jobs -pr || true)"

    if [ -n "$pids" ]; then

        kill $pids 2>/dev/null || true

    fi
}


trap cleanup EXIT INT TERM


# ============================================================
# CABECERA
# ============================================================

echo "================================================"
echo " Canal Isabel II - Playwright"
echo " Versión: ${ADDON_VERSION:-desconocida}"
echo "================================================"

echo "Modo: ${MODE}"
echo "Intervalo: ${INTERVAL_HOURS} horas"
echo "Espera inicial: ${STARTUP_DELAY} segundos"

echo


# ============================================================
# XVFB
# ============================================================

echo "Arrancando Xvfb..."

Xvfb :99 \
    -screen 0 1360x900x24 \
    -ac \
    -nolisten tcp &

XVFB_PID=$!

sleep 2


if ! kill -0 "$XVFB_PID" 2>/dev/null; then

    echo "ERROR: Xvfb no ha arrancado"

    exit 20

fi


echo "Xvfb OK"


# ============================================================
# OPENBOX
# ============================================================

echo "Arrancando Openbox..."

openbox &

OPENBOX_PID=$!

sleep 1


# ============================================================
# X11VNC
# ============================================================

echo "Arrancando x11vnc..."

x11vnc \
    -display :99 \
    -forever \
    -shared \
    -nopw \
    -rfbport 5900 \
    -localhost &

VNC_PID=$!


sleep 2


if ! kill -0 "$VNC_PID" 2>/dev/null; then

    echo "ERROR: x11vnc no ha arrancado"

    exit 21

fi


echo "x11vnc OK"


# ============================================================
# WEBSOCKIFY
# ============================================================

echo "Arrancando websockify interno..."

websockify \
    6080 \
    localhost:5900 &

WEBSOCKIFY_PID=$!


sleep 2


if ! kill -0 "$WEBSOCKIFY_PID" 2>/dev/null; then

    echo "ERROR: websockify no ha arrancado"

    exit 22

fi


echo "websockify OK"


# ============================================================
# NGINX / HOME ASSISTANT INGRESS
# ============================================================

echo "Comprobando configuración nginx..."

nginx -t


if [ $? -ne 0 ]; then

    echo "ERROR: configuración nginx incorrecta"

    exit 23

fi


echo "Arrancando nginx para Home Assistant Ingress..."

nginx -g "daemon off;" &

NGINX_PID=$!


sleep 2


if ! kill -0 "$NGINX_PID" 2>/dev/null; then

    echo "ERROR: nginx no ha arrancado"

    exit 24

fi


echo "nginx OK"
echo
echo "Interfaz noVNC disponible en puerto Ingress 8099"
echo


# ============================================================
# MODO LOGIN
# ============================================================

if [ "$MODE" = "login" ]; then

    echo "================================================"
    echo " MODO LOGIN"
    echo "================================================"

    echo
    echo "Abre la interfaz web del add-on."
    echo "Inicia sesión manualmente."
    echo "Si aparece CAPTCHA, resuélvelo manualmente."
    echo

    python3 /app/auth_browser.py

    exit $?

fi


# ============================================================
# VALIDACIÓN MODO
# ============================================================

if [ "$MODE" != "auto" ]; then

    echo "ERROR: modo desconocido: ${MODE}"

    exit 2

fi


# ============================================================
# ESPERA INICIAL
# ============================================================

if [ "$STARTUP_DELAY" -gt 0 ]; then

    echo "Esperando ${STARTUP_DELAY} segundos..."

    sleep "$STARTUP_DELAY"

fi


# ============================================================
# BUCLE AUTOMÁTICO
# ============================================================

while true
do

    echo
    echo "------------------------------------------------"
    echo "Ejecutando descarga:"
    date
    echo "------------------------------------------------"

    python3 /app/canal_playwright.py

    EXIT_CODE=$?


    echo


    if [ "$EXIT_CODE" -eq 0 ]; then

        echo "Proceso finalizado correctamente."

    elif [ "$EXIT_CODE" -eq 30 ]; then

        echo "Autenticación requerida."
        echo "Cambia mode a login y reinicia el add-on."

    else

        echo "Proceso finalizado con error: ${EXIT_CODE}"

    fi


    echo
    echo "Próxima ejecución dentro de ${INTERVAL_HOURS} horas."
    echo


    sleep "$INTERVAL_SECONDS"

done