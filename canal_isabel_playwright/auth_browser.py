from __future__ import annotations

import json
import logging
import signal
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


# ============================================================
# RUTAS
# ============================================================

CONFIG_DIR = Path("/config")
PROFILE_DIR = CONFIG_DIR / "browser_profile"

STATUS_FILE = Path("/share/canal_estado.json")

SESSION_FILE = CONFIG_DIR / "canal_session.json"
SESSION_STORAGE_FILE = CONFIG_DIR / "canal_session_storage.json"


# ============================================================
# URL
# ============================================================

CONSUMO_URL = (
    "https://oficinavirtual.canaldeisabelsegunda.es/"
    "group/ovir/consumo"
)


# ============================================================
# CONTROL
# ============================================================

STOP_EVENT = threading.Event()


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

_LOGGER = logging.getLogger("canal-auth")


# ============================================================
# ESTADO HOME ASSISTANT
# ============================================================

def write_status(
    state: str,
    message: str,
) -> None:

    data = {
        "estado": state,
        "mensaje": message,
        "ultima_ejecucion": datetime.now().astimezone().isoformat(),
        "modo": "login",
    }

    try:

        STATUS_FILE.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    except Exception as err:

        _LOGGER.warning(
            "No se pudo escribir canal_estado.json: %s",
            err,
        )


# ============================================================
# ORIGIN
# ============================================================

def get_origin(url: str) -> str | None:

    try:

        parsed = urlsplit(url)

        if parsed.scheme not in (
            "http",
            "https",
        ):
            return None

        return (
            f"{parsed.scheme}://"
            f"{parsed.netloc}"
        )

    except Exception:
        return None


# ============================================================
# SESSION STORAGE
# ============================================================

def capture_session_storage(
    context,
) -> dict:

    result = {}

    for page in context.pages:

        try:

            js_url = page.evaluate(
                "() => window.location.href"
            )

            origin = get_origin(
                js_url
            )

            if not origin:
                continue

            storage = page.evaluate(
                """
                () => {

                    const data = {};

                    for (
                        let i = 0;
                        i < sessionStorage.length;
                        i++
                    ) {

                        const key =
                            sessionStorage.key(i);

                        data[key] =
                            sessionStorage.getItem(key);
                    }

                    return data;
                }
                """
            )

            if storage:

                result[
                    origin
                ] = storage

        except Exception as err:

            _LOGGER.debug(
                "No se pudo leer sessionStorage: %s",
                err,
            )

    return result


# ============================================================
# GUARDAR SESIÓN
# ============================================================

def save_session(
    context,
) -> bool:

    try:

        # ----------------------------------------------------
        # Cookies + localStorage + IndexedDB
        # ----------------------------------------------------

        try:

            state = context.storage_state(
                indexed_db=True
            )

        except TypeError:

            state = context.storage_state()


        SESSION_FILE.write_text(
            json.dumps(
                state,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


        # ----------------------------------------------------
        # sessionStorage
        # ----------------------------------------------------

        session_storage = (
            capture_session_storage(
                context
            )
        )


        SESSION_STORAGE_FILE.write_text(
            json.dumps(
                session_storage,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


        # ----------------------------------------------------
        # Diagnóstico
        # ----------------------------------------------------

        cookies = state.get(
            "cookies",
            [],
        )

        origins = state.get(
            "origins",
            [],
        )


        _LOGGER.info(
            (
                "Sesión guardada correctamente: "
                "%s cookies, "
                "%s origins, "
                "%s origins con sessionStorage"
            ),
            len(cookies),
            len(origins),
            len(session_storage),
        )


        return True


    except Exception as err:

        _LOGGER.exception(
            "No se pudo guardar la sesión: %s",
            err,
        )

        return False


# ============================================================
# LOCKS CHROMIUM
# ============================================================

def remove_profile_locks() -> None:

    for name in (
        "SingletonLock",
        "SingletonSocket",
        "SingletonCookie",
    ):

        path = (
            PROFILE_DIR
            / name
        )

        try:

            if (
                path.exists()
                or path.is_symlink()
            ):
                path.unlink()

        except Exception:
            pass


# ============================================================
# SIGNALS
# ============================================================

def handle_signal(
    signum,
    frame,
) -> None:

    _LOGGER.info(
        "Señal de cierre recibida."
    )

    STOP_EVENT.set()


# ============================================================
# DATOS REALES DE UNA PÁGINA
# ============================================================

def inspect_page(
    page,
) -> dict:

    result = {
        "playwright_url": "",
        "js_url": "",
        "title": "",
        "password": False,
        "private_ui": False,
    }


    # --------------------------------------------------------
    # URL conocida por Playwright
    # --------------------------------------------------------

    try:

        result[
            "playwright_url"
        ] = page.url

    except Exception:
        pass


    # --------------------------------------------------------
    # URL real dentro de Chromium
    # --------------------------------------------------------

    try:

        result[
            "js_url"
        ] = page.evaluate(
            "() => window.location.href"
        )

    except Exception:
        pass


    # --------------------------------------------------------
    # Título
    # --------------------------------------------------------

    try:

        result[
            "title"
        ] = page.title()

    except Exception:
        pass


    # --------------------------------------------------------
    # ¿Existe formulario de contraseña?
    # --------------------------------------------------------

    try:

        result[
            "password"
        ] = (
            page
            .locator(
                'input[type="password"]'
            )
            .count()
            > 0
        )

    except Exception:
        pass


    # --------------------------------------------------------
    # Elementos característicos de sesión privada
    # --------------------------------------------------------

    try:

        body_text = (
            page
            .locator("body")
            .inner_text(
                timeout=3000
            )
            .lower()
        )

        has_hello = (
            "hola," in body_text
        )

        has_contract = (
            "contrato n.º" in body_text
            or "contrato nº" in body_text
            or "contrato n°" in body_text
        )

        has_telelecturas = (
            "telelecturas" in body_text
        )

        result[
            "private_ui"
        ] = (
            has_hello
            and has_contract
            and has_telelecturas
        )

    except Exception:
        pass


    return result


# ============================================================
# DETECTAR AUTENTICACIÓN
# ============================================================

def page_is_authenticated(
    info: dict,
) -> bool:

    playwright_url = (
        info.get(
            "playwright_url",
            ""
        )
        .lower()
    )

    js_url = (
        info.get(
            "js_url",
            ""
        )
        .lower()
    )


    # --------------------------------------------------------
    # Criterio 1:
    # cualquiera de las dos URLs está en zona privada
    # --------------------------------------------------------

    private_url = (
        (
            "/group/ovir/" in playwright_url
            and "/login" not in playwright_url
        )
        or
        (
            "/group/ovir/" in js_url
            and "/login" not in js_url
        )
    )


    if private_url:
        return True


    # --------------------------------------------------------
    # Criterio 2:
    # DOM inequívoco de usuario autenticado
    # --------------------------------------------------------

    if (
        info.get(
            "private_ui",
            False
        )
        and not info.get(
            "password",
            False
        )
    ):
        return True


    return False


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    CONFIG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    PROFILE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    STATUS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    remove_profile_locks()


    signal.signal(
        signal.SIGTERM,
        handle_signal,
    )

    signal.signal(
        signal.SIGINT,
        handle_signal,
    )


    write_status(
        "autenticacion_manual",
        (
            "Modo login activo. "
            "Abre la interfaz web del add-on."
        ),
    )


    authenticated_once = False

    last_diagnostic = None


    with sync_playwright() as p:

        _LOGGER.info(
            (
                "Abriendo Chromium visible "
                "para autenticación manual..."
            )
        )


        context = (
            p.chromium
            .launch_persistent_context(
                user_data_dir=str(
                    PROFILE_DIR
                ),
                headless=False,
                viewport={
                    "width": 1360,
                    "height": 850,
                },
                accept_downloads=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
        )


        try:

            page = (
                context.pages[0]
                if context.pages
                else context.new_page()
            )


            page.goto(
                CONSUMO_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )


            _LOGGER.info(
                (
                    "Navegador listo. "
                    "Inicia sesión manualmente. "
                    "Si aparece CAPTCHA, resuélvelo "
                    "en la interfaz web."
                )
            )


            while not STOP_EVENT.is_set():

                try:

                    diagnostics = []

                    authenticated_page = None


                    # ----------------------------------------
                    # Revisar TODAS las páginas
                    # ----------------------------------------

                    for index, candidate in enumerate(
                        context.pages
                    ):

                        info = inspect_page(
                            candidate
                        )


                        diagnostics.append(
                            {
                                "index": index,
                                **info,
                            }
                        )


                        if (
                            authenticated_page is None
                            and page_is_authenticated(
                                info
                            )
                        ):

                            authenticated_page = (
                                candidate
                            )


                    # ----------------------------------------
                    # Log solo cuando cambia algo
                    # ----------------------------------------

                    diagnostic_string = (
                        json.dumps(
                            diagnostics,
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    )


                    if (
                        diagnostic_string
                        != last_diagnostic
                    ):

                        _LOGGER.info(
                            (
                                "Estado páginas Chromium: "
                                "%s"
                            ),
                            diagnostic_string,
                        )


                        last_diagnostic = (
                            diagnostic_string
                        )


                    # ----------------------------------------
                    # Autenticado
                    # ----------------------------------------

                    if (
                        authenticated_page
                        is not None
                        and not authenticated_once
                    ):

                        try:

                            real_url = (
                                authenticated_page
                                .evaluate(
                                    "() => window.location.href"
                                )
                            )

                        except Exception:

                            real_url = (
                                authenticated_page.url
                            )


                        _LOGGER.info(
                            (
                                "Sesión autenticada "
                                "detectada en: %s"
                            ),
                            real_url,
                        )


                        # Damos margen para que Canal/Liferay
                        # termine de escribir cookies/storage.
                        authenticated_page.wait_for_timeout(
                            3000
                        )


                        if save_session(
                            context
                        ):

                            authenticated_once = True


                            write_status(
                                "autenticado",
                                (
                                    "Sesión autenticada y "
                                    "guardada. Ya puedes "
                                    "cambiar a mode auto."
                                ),
                            )


                except Exception as err:

                    _LOGGER.exception(
                        (
                            "Error comprobando "
                            "autenticación: %s"
                        ),
                        err,
                    )


                STOP_EVENT.wait(
                    2
                )


        finally:

            _LOGGER.info(
                "Cerrando Chromium..."
            )


            if authenticated_once:

                try:

                    save_session(
                        context
                    )

                except Exception:
                    pass


            try:

                context.close()

            except Exception:
                pass


            _LOGGER.info(
                "Chromium cerrado."
            )


if __name__ == "__main__":

    main()