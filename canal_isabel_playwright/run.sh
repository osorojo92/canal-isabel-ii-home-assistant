#!/bin/bash
set -u

export DISPLAY=:99

read_option() {
    local key="$1"
    local default="$2"

    python3 - "$key" "$default" <<'PY'
import json
import sys

key = sys.argv[1]
default = sys.argv[2]

try:
    with open("/data/options.json", "r", encoding="utf-8") as f:
        options = json.load(f)
    value = options.get(key, default)
except Exception:
    value = default

print(value)
PY
}

MODE="$(read_option mode auto)"
INTERVAL_HOURS="$(read_option interval_hours 24)"
STARTUP_DELAY="$(read_option startup_delay 30)"
INTERVAL_SECONDS=$((INTERVAL_HOURS * 3600))

cleanup() {
    local pids
    pids="$(jobs -pr || true)"
    if [ -n "$pids" ]; then
        kill $pids 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

echo "================================================"
echo " Canal Isabel II - Playwright 1.0.0"
echo "================================================"
echo "Modo: ${MODE}"
echo "Intervalo: ${INTERVAL_HOURS} horas"
echo "Espera inicial: ${STARTUP_DELAY} segundos"
echo

Xvfb :99 -screen 0 1360x900x24 -ac -nolisten tcp >/tmp/xvfb.log 2>&1 &
sleep 1
openbox >/tmp/openbox.log 2>&1 &
x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -localhost >/tmp/x11vnc.log 2>&1 &
websockify --web=/usr/share/novnc 8099 localhost:5900 >/tmp/novnc.log 2>&1 &
sleep 1

if [ "$MODE" = "login" ]; then
    echo "Modo LOGIN."
    echo "Abre la interfaz web del add-on y autentícate manualmente."
    python3 /app/auth_browser.py
    exit $?
fi

if [ "$MODE" != "auto" ]; then
    echo "ERROR: modo desconocido: ${MODE}"
    exit 2
fi

if [ "$STARTUP_DELAY" -gt 0 ]; then
    sleep "$STARTUP_DELAY"
fi

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
        echo "Autenticación requerida. Cambia mode=login y reinicia."
    else
        echo "Proceso finalizado con error: ${EXIT_CODE}"
    fi

    echo "Próxima ejecución dentro de ${INTERVAL_HOURS} horas."
    sleep "$INTERVAL_SECONDS"
done
