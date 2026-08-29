from __future__ import annotations

import json
import logging
import signal
import threading
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

CONFIG_DIR = Path("/config")
PROFILE_DIR = CONFIG_DIR / "browser_profile"
STATUS_FILE = Path("/share/canal_estado.json")
CONSUMO_URL = "https://oficinavirtual.canaldeisabelsegunda.es/group/ovir/consumo"
SESSION_FILE = CONFIG_DIR / "canal_session.json"

STOP_EVENT = threading.Event()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger("canal-auth")

def save_session(context) -> None:
    try:
        state = context.storage_state()

        SESSION_FILE.write_text(
            json.dumps(
                state,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        _LOGGER.info(
            "Sesión guardada correctamente: %s cookies",
            len(state.get("cookies", [])),
        )

    except Exception as err:
        _LOGGER.error(
            "No se pudo guardar la sesión: %s",
            err,
        )

def write_status(state: str, message: str) -> None:
    data = {
        "estado": state,
        "mensaje": message,
        "ultima_ejecucion": datetime.now().astimezone().isoformat(),
        "modo": "login",
    }
    try:
        STATUS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as err:
        _LOGGER.warning("No se pudo escribir canal_estado.json: %s", err)


def remove_profile_locks() -> None:
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        path = PROFILE_DIR / name
        try:
            if path.exists() or path.is_symlink():
                path.unlink()
        except Exception:
            pass


def handle_signal(signum, frame) -> None:
    STOP_EVENT.set()


def main() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    remove_profile_locks()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    write_status(
        "autenticacion_manual",
        "Modo login activo. Abre la interfaz web del add-on.",
    )

    with sync_playwright() as p:
        _LOGGER.info("Abriendo Chromium visible para autenticación manual...")

        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1360, "height": 850},
            accept_downloads=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(CONSUMO_URL, wait_until="domcontentloaded", timeout=60000)

            _LOGGER.info(
                "Navegador listo. Inicia sesión manualmente. "
                "Si aparece CAPTCHA, resuélvelo en la interfaz web."
            )

            last_state = None

            while not STOP_EVENT.is_set():
                try:
                    url = page.url.lower()
                    if "/group/ovir/" in url and "/login" not in url:
                        current = "autenticado"

                        if current != last_state:

                            _LOGGER.info(
                                "Sesión autenticada detectada."
                            )

                            # IMPORTANTE:
                            # Guardamos las cookies AHORA.
                            # No esperamos al cierre de Chromium.
                            save_session(context)

                            write_status(
                                "autenticado",
                                "Sesión autenticada y guardada. Ya puedes cambiar a mode auto.",
                            )
                    else:
                        current = "pendiente"
                    last_state = current
                except Exception:
                    pass

                STOP_EVENT.wait(2)

        finally:
            _LOGGER.info("Cerrando Chromium y guardando el perfil...")
            try:
                try:
                    save_session(context)
                except Exception:
                    pass
                context.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
