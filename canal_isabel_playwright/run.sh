#!/bin/bash

set -u

OPTIONS_FILE="/data/options.json"

echo "================================================"
echo " Canal Isabel II - Playwright"
echo "================================================"

INTERVAL_HOURS=$(python3 - <<'PY'
import json

try:
    with open("/data/options.json", "r", encoding="utf-8") as f:
        options = json.load(f)

    print(int(options.get("interval_hours", 24)))
except Exception:
    print(24)
PY
)

STARTUP_DELAY=$(python3 - <<'PY'
import json

try:
    with open("/data/options.json", "r", encoding="utf-8") as f:
        options = json.load(f)

    print(int(options.get("startup_delay", 30)))
except Exception:
    print(30)
PY
)

INTERVAL_SECONDS=$((INTERVAL_HOURS * 3600))

echo "Intervalo: ${INTERVAL_HOURS} horas"
echo "Espera inicial: ${STARTUP_DELAY} segundos"
echo

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
    else
        echo "Proceso finalizado con error: ${EXIT_CODE}"
    fi

    echo
    echo "Próxima ejecución dentro de ${INTERVAL_HOURS} horas."
    echo

    sleep "$INTERVAL_SECONDS"
done