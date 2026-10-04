from __future__ import annotations

import json
import logging
import signal
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from auto_login import (
    attempt_auto_relogin,
    load_auto_relogin_options,
)


# ============================================================
# RUTAS
# ============================================================

CONFIG_DIR = Path("/config")
PROFILE_DIR = CONFIG_DIR / "browser_profile"

STATUS_FILE = Path("/share/canal_estado.json")

SESSION_FILE = CONFIG_DIR / "canal_session.json"
SESSION_STORAGE_FILE = CONFIG_DIR / "canal_session_storage.json"
AUTH_EVENT_MARKER = CONFIG_DIR / "canal_auth_required_event_sent.json"
AUTO_RELOGIN_ATTEMPT_MARKER = (
    CONFIG_DIR / "canal_auto_relogin_attempted.json"
)


# ============================================================
# URL
# ============================================================

BASE_URL = (
    "https://oficinavirtual.canaldeisabelsegunda.es"
)

LOGIN_URL = (
    BASE_URL
    + "/login"
)

CONSUMO_URL = (
    BASE_URL
    + "/group/ovir/consumo"
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
# REARMAR AVISO DE AUTENTICACIÓN
# ============================================================

def clear_auth_required_event_marker() -> None:

    if not AUTH_EVENT_MARKER.exists():
        return

    try:

        AUTH_EVENT_MARKER.unlink()

        _LOGGER.info(
            "Aviso de autenticación rearmado."
        )

    except Exception as err:

        _LOGGER.warning(
            (
                "No se pudo rearmar el aviso "
                "de autenticación: %s"
            ),
            err,
        )


# ============================================================
# REARMAR INTENTO AUTOMÁTICO
# ============================================================

def clear_auto_relogin_attempt_marker() -> None:

    if not AUTO_RELOGIN_ATTEMPT_MARKER.exists():
        return

    try:

        AUTO_RELOGIN_ATTEMPT_MARKER.unlink()

        _LOGGER.info(
            "Reintento automático de autenticación rearmado."
        )

    except Exception as err:

        _LOGGER.warning(
            (
                "No se pudo rearmar el intento automático "
                "de autenticación: %s"
            ),
            err,
        )


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
# PREPARAR LOGIN LIMPIO
# ============================================================

def prepare_clean_login_test(
    context,
    page,
) -> None:
    """
    Prepara una prueba de login sin reutilizar la sesión guardada.

    Se eliminan cookies y almacenamiento web del perfil persistente
    antes de ejecutar el intento automático. No se leen ni restauran
    canal_session.json ni canal_session_storage.json.
    """

    _LOGGER.info(
        (
            "Preparando prueba de login limpia: "
            "se ignorará la sesión guardada."
        )
    )

    try:

        context.clear_cookies()

        _LOGGER.info(
            "Cookies del navegador eliminadas para la prueba."
        )

    except Exception as err:

        _LOGGER.warning(
            "No se pudieron limpiar las cookies: %s",
            err,
        )

    try:

        page.goto(
            LOGIN_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

    except Exception as err:

        _LOGGER.warning(
            (
                "No se pudo abrir directamente la página "
                "de login antes de limpiar storage: %s"
            ),
            err,
        )

    try:

        page.evaluate(
            """
            async () => {
                try {
                    localStorage.clear();
                } catch (e) {}

                try {
                    sessionStorage.clear();
                } catch (e) {}

                try {
                    if (window.indexedDB && indexedDB.databases) {
                        const databases = await indexedDB.databases();

                        for (const db of databases) {
                            if (db && db.name) {
                                indexedDB.deleteDatabase(db.name);
                            }
                        }
                    }
                } catch (e) {}

                try {
                    if (window.caches) {
                        const names = await caches.keys();

                        for (const name of names) {
                            await caches.delete(name);
                        }
                    }
                } catch (e) {}
            }
            """
        )

        _LOGGER.info(
            (
                "localStorage, sessionStorage, IndexedDB y "
                "cachés web limpiados para la prueba."
            )
        )

    except Exception as err:

        _LOGGER.warning(
            (
                "No se pudo limpiar completamente el "
                "almacenamiento web: %s"
            ),
            err,
        )

    try:

        context.clear_cookies()

    except Exception:
        pass

    page.goto(
        CONSUMO_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    _LOGGER.info(
        (
            "Prueba limpia preparada. El intento automático "
            "usará exclusivamente usuario, contraseña y tipo "
            "de usuario configurados en el add-on."
        )
    )


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


            # ------------------------------------------------
            # INTENTO AUTOMÁTICO ÚNICO EN MODE LOGIN
            # ------------------------------------------------

            auto_relogin_options = (
                load_auto_relogin_options()
            )

            if auto_relogin_options.get(
                "auto_relogin",
                False,
            ):

                _LOGGER.info(
                    (
                        "Modo login con recuperación automática "
                        "activada: se realizará un único intento "
                        "con las credenciales configuradas."
                    )
                )

                prepare_clean_login_test(
                    context,
                    page,
                )

                result = attempt_auto_relogin(
                    page,
                    "login_mode_clean_test",
                    ignore_attempt_marker=True,
                )

                if result.get(
                    "success",
                    False,
                ):

                    _LOGGER.info(
                        (
                            "Intento automático en mode login: "
                            "ÉXITO. La sesión se ha recuperado."
                        )
                    )

                else:

                    _LOGGER.warning(
                        (
                            "Intento automático en mode login: "
                            "SIN ÉXITO (%s). %s"
                        ),
                        result.get(
                            "reason",
                            "unknown",
                        ),
                        result.get(
                            "message",
                            "Sin detalle.",
                        ),
                    )

                    _LOGGER.info(
                        (
                            "El navegador permanecerá abierto "
                            "para autenticación manual."
                        )
                    )

            else:

                _LOGGER.info(
                    (
                        "Recuperación automática desactivada "
                        "en mode login."
                    )
                )

                page.goto(
                    CONSUMO_URL,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )


            _LOGGER.info(
                (
                    "Navegador listo. "
                    "Si no se ha autenticado automáticamente, "
                    "inicia sesión manualmente. "
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

                            clear_auth_required_event_marker()
                            clear_auto_relogin_attempt_marker()


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