from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

# ============================================================
# Rutas
# ============================================================

CONFIG_DIR = Path("/config")
PROFILE_DIR = CONFIG_DIR / "browser_profile"

SHARE_DIR = Path("/share")
CSV_FILE = SHARE_DIR / "canal_consumo_horario.csv"
STATUS_FILE = SHARE_DIR / "canal_estado.json"

SESSION_FILE = CONFIG_DIR / "canal_session.json"


# ============================================================
# URLs
# ============================================================

CONSUMO_URL = (
    "https://oficinavirtual.canaldeisabelsegunda.es/group/ovir/consumo"
)


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

_LOGGER = logging.getLogger("canal")


# ============================================================
# Sesión
# ============================================================

def restore_session(context) -> bool:
    """
    Restaura las cookies guardadas durante el login manual.
    """

    if not SESSION_FILE.exists():
        _LOGGER.warning(
            "No existe sesión guardada: %s",
            SESSION_FILE,
        )
        return False

    try:
        state = json.loads(
            SESSION_FILE.read_text(
                encoding="utf-8"
            )
        )

        cookies = state.get("cookies", [])

        if not cookies:
            _LOGGER.warning(
                "El archivo de sesión no contiene cookies."
            )
            return False

        context.add_cookies(cookies)

        _LOGGER.info(
            "Sesión restaurada: %s cookies cargadas.",
            len(cookies),
        )

        return True

    except Exception as err:
        _LOGGER.error(
            "No se pudo restaurar la sesión: %s",
            err,
        )
        return False


# ============================================================
# Estado para Home Assistant
# ============================================================

def write_status(
    state: str,
    message: str,
    code: int = 0,
    csv_bytes: int | None = None,
) -> None:

    data = {
        "estado": state,
        "mensaje": message,
        "codigo": code,
        "ultima_ejecucion": datetime.now().astimezone().isoformat(),
        "modo": "auto",
    }

    if csv_bytes is not None:
        data["csv_bytes"] = csv_bytes

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
# Perfil Chromium
# ============================================================

def remove_profile_locks() -> None:
    """
    Elimina locks residuales de Chromium después de un cierre
    brusco del add-on.
    """

    for name in (
        "SingletonLock",
        "SingletonSocket",
        "SingletonCookie",
    ):
        path = PROFILE_DIR / name

        try:
            if path.exists() or path.is_symlink():
                path.unlink()

        except Exception:
            pass


# ============================================================
# Comprobación de autenticación
# ============================================================

def session_is_valid(page) -> bool:

    url = page.url.lower()

    if "/group/ovir/" in url and "/login" not in url:
        return True

    try:
        if page.locator('input[type="password"]').count() > 0:
            return False

    except Exception:
        pass

    return False


# ============================================================
# Error controlado
# ============================================================

def fail(
    context,
    code: int,
    message: str,
    auth: bool = False,
) -> None:

    _LOGGER.error(message)

    write_status(
        "reautenticacion_requerida" if auth else "error",
        message,
        code,
    )

    try:
        context.close()
    except Exception:
        pass

    raise SystemExit(code)


# ============================================================
# Diagnóstico de red
# ============================================================

def log_request(request) -> None:

    url = request.url.lower()

    if (
        "consumo" in url
        or "periodic" in url
        or "telelectura" in url
        or "export" in url
    ):
        _LOGGER.info(
            "REQUEST %s %s",
            request.method,
            request.url,
        )

        try:
            data = request.post_data

            if data:
                _LOGGER.info(
                    "POST DATA: %s",
                    data,
                )

        except Exception:
            pass


def log_response(response) -> None:

    url = response.url.lower()

    if (
        "consumo" in url
        or "periodic" in url
        or "telelectura" in url
        or "export" in url
    ):
        _LOGGER.info(
            "RESPONSE %s %s",
            response.status,
            response.url,
        )


# ============================================================
# Abrir filtros
# ============================================================

def open_filters(page) -> None:

    try:
        show_filters = page.get_by_text(
            "Mostrar filtros",
            exact=False,
        )

        if (
            show_filters.count() > 0
            and show_filters.first.is_visible()
        ):
            _LOGGER.info(
                "Abriendo filtros..."
            )

            show_filters.first.click()

            page.wait_for_timeout(1000)

    except Exception as err:
        _LOGGER.warning(
            "No se pudieron abrir los filtros: %s",
            err,
        )


# ============================================================
# Selector de periodicidad
# ============================================================

def find_periodicity_selector(page):

    periodicity = page.locator(
        "select#selectPeriodicidad"
    )

    if periodicity.count() == 0:
        periodicity = page.locator(
            'select[id*="selectPeriodicidad"]'
        )

    return periodicity


# ============================================================
# Aplicar filtro HORARIO
# ============================================================

def select_and_apply_hourly(
    page,
    context,
) -> None:

    _LOGGER.info(
        "Buscando selector de periodicidad..."
    )

    periodicity = find_periodicity_selector(page)

    if periodicity.count() == 0:
        fail(
            context,
            40,
            "No se encuentra el selector de periodicidad.",
        )

    periodicity = periodicity.first

    _LOGGER.info(
        "Selector encontrado. Seleccionando frecuencia HORARIA..."
    )

    selected = False


    # --------------------------------------------------------
    # Intento 1: por label
    # --------------------------------------------------------

    try:
        periodicity.select_option(
            label="Horaria"
        )

        selected = True

    except Exception:
        pass


    # --------------------------------------------------------
    # Intento 2: por value
    # --------------------------------------------------------

    if not selected:

        try:
            periodicity.select_option(
                value="Horaria"
            )

            selected = True

        except Exception:
            pass


    # --------------------------------------------------------
    # Intento 3: buscar opción que contenga "horaria"
    # --------------------------------------------------------

    if not selected:

        options = periodicity.locator("option")

        for index in range(options.count()):

            option = options.nth(index)

            try:
                text = (
                    option
                    .inner_text()
                    .strip()
                    .lower()
                )

            except Exception:
                continue

            if "horaria" in text:

                value = option.get_attribute(
                    "value"
                )

                periodicity.select_option(
                    value=value
                )

                selected = True
                break


    if not selected:
        fail(
            context,
            41,
            "Se encontró el selector, pero no la opción Horaria.",
        )


    # --------------------------------------------------------
    # Verificar selección real
    # --------------------------------------------------------

    try:

        selected_text = periodicity.locator(
            "option:checked"
        ).inner_text().strip()

        _LOGGER.info(
            "Periodicidad actualmente seleccionada: %s",
            selected_text,
        )

        if "horaria" not in selected_text.lower():

            fail(
                context,
                42,
                (
                    "El selector no quedó realmente "
                    "en frecuencia Horaria."
                ),
            )

    except Exception as err:

        _LOGGER.warning(
            "No se pudo verificar el texto de la opción: %s",
            err,
        )


    # --------------------------------------------------------
    # Encontrar formulario que contiene el selector
    # --------------------------------------------------------

    form = periodicity.locator(
        "xpath=ancestor::form[1]"
    )

    if form.count() == 0:
        fail(
            context,
            43,
            (
                "No se encontró el formulario asociado "
                "al selector de periodicidad."
            ),
        )

    form = form.first


    # --------------------------------------------------------
    # Diagnóstico del formulario
    # --------------------------------------------------------

    try:

        form_action = form.get_attribute("action")
        form_method = form.get_attribute("method")

        _LOGGER.info(
            "Formulario Telelecturas: method=%s action=%s",
            form_method,
            form_action,
        )

    except Exception:
        pass


    _LOGGER.info(
        "Enviando formulario de Telelecturas con periodicidad HORARIA..."
    )


    # --------------------------------------------------------
    # Enviar realmente el formulario.
    #
    # Esto reproduce el POST observado manualmente:
    #
    # p_p_lifecycle = 1
    # javax.portlet.action = /Telelectura/buscarForm
    # periodicidad = Horaria
    # --------------------------------------------------------

    try:

        form.evaluate(
            """
            form => {
                if (typeof form.requestSubmit === 'function') {
                    form.requestSubmit();
                } else {
                    form.submit();
                }
            }
            """
        )

    except Exception as err:

        fail(
            context,
            44,
            f"Error enviando formulario de Telelecturas: {err}",
        )


    # --------------------------------------------------------
    # Esperar respuesta / actualización
    # --------------------------------------------------------

    try:

        page.wait_for_load_state(
            "domcontentloaded",
            timeout=60000,
        )

    except PlaywrightTimeoutError:

        # Algunas acciones de Liferay no generan una navegación
        # tradicional; seguimos esperando a que aparezcan datos.
        _LOGGER.warning(
            "No hubo evento DOMContentLoaded tras enviar el formulario."
        )


    # Liferay puede realizar trabajo adicional después del POST.
    page.wait_for_timeout(5000)


    # --------------------------------------------------------
    # Comprobar que seguimos autenticados
    # --------------------------------------------------------

    if not session_is_valid(page):

        fail(
            context,
            31,
            (
                "La sesión se perdió al aplicar "
                "la periodicidad Horaria."
            ),
            auth=True,
        )


    # --------------------------------------------------------
    # Comprobar que la página realmente está en HORARIA
    # --------------------------------------------------------

    body_text = ""

    try:

        body_text = page.locator(
            "body"
        ).inner_text(
            timeout=10000
        )

    except Exception as err:

        _LOGGER.warning(
            "No se pudo leer el texto de la página: %s",
            err,
        )


    normalized = re.sub(
        r"\s+",
        " ",
        body_text,
    ).upper()


    if "CONSUMO FRECUENCIA HORARIA" in normalized:

        _LOGGER.info(
            "Consulta HORARIA aplicada correctamente."
        )

    elif "FRECUENCIA HORARIA" in normalized:

        _LOGGER.info(
            "La página confirma frecuencia HORARIA."
        )

    else:

        _LOGGER.warning(
            (
                "No se encontró el texto 'FRECUENCIA HORARIA' "
                "en la página. Se continuará, pero el CSV "
                "será validado obligatoriamente."
            )
        )


# ============================================================
# Localizar exportación CSV
# ============================================================

def find_csv_link(
    page,
    context,
):

    _LOGGER.info(
        "Buscando enlace de exportación CSV..."
    )

    # La petición real observada utiliza:
    #
    # p_p_resource_id=/Telelecturas/export-csv
    # p_p_lifecycle=2
    # fileFormat=CSV

    selectors = [
        'a[href*="export-csv"]',
        'a[href*="Telelecturas%2Fexport-csv"]',
        'a[href*="Telelecturas/export-csv"]',
        'a[href*="fileFormat=CSV"]',
        'a[href*="fileFormat%3DCSV"]',
    ]


    for selector in selectors:

        links = page.locator(selector)

        if links.count() > 0:

            _LOGGER.info(
                "Enlace CSV encontrado con selector: %s",
                selector,
            )

            try:

                href = links.first.get_attribute(
                    "href"
                )

                _LOGGER.info(
                    "URL exportación CSV: %s",
                    href,
                )

            except Exception:
                pass

            return links.first


    fail(
        context,
        50,
        "No se encuentra el enlace de exportación CSV.",
    )


# ============================================================
# Descargar CSV
# ============================================================

def download_csv(
    page,
    context,
) -> int:

    csv_link = find_csv_link(
        page,
        context,
    )


    if CSV_FILE.exists():

        try:
            CSV_FILE.unlink()

        except Exception as err:

            fail(
                context,
                51,
                (
                    "No se puede borrar el CSV anterior: "
                    f"{err}"
                ),
            )


    _LOGGER.info(
        "Descargando CSV horario..."
    )


    try:

        with page.expect_download(
            timeout=60000
        ) as download_info:

            csv_link.click()


        download = download_info.value

        _LOGGER.info(
            "Nombre sugerido por Canal: %s",
            download.suggested_filename,
        )

        download.save_as(
            str(CSV_FILE)
        )


    except Exception as err:

        fail(
            context,
            60,
            f"Error descargando CSV: {err}",
        )


    if not CSV_FILE.exists():

        fail(
            context,
            61,
            (
                "La descarga terminó pero "
                "el CSV no existe."
            ),
        )


    size = CSV_FILE.stat().st_size


    if size == 0:

        fail(
            context,
            62,
            "El CSV descargado está vacío.",
        )


    return size


# ============================================================
# Leer CSV tolerando distintas codificaciones
# ============================================================

def read_csv_text(
    context,
) -> str:

    try:

        raw = CSV_FILE.read_bytes()

    except Exception as err:

        fail(
            context,
            63,
            f"No se puede leer el CSV descargado: {err}",
        )


    encodings = (
        "utf-8-sig",
        "utf-8",
        "cp1252",
        "latin-1",
    )


    for encoding in encodings:

        try:

            text = raw.decode(
                encoding
            )

            _LOGGER.info(
                "CSV leído usando codificación %s.",
                encoding,
            )

            return text

        except UnicodeDecodeError:
            continue


    fail(
        context,
        63,
        "No se pudo determinar la codificación del CSV.",
    )


# ============================================================
# Validación del CSV
# ============================================================

def validate_hourly_csv(
    context,
) -> None:

    content = read_csv_text(
        context
    )

    upper_content = content.upper()


    # --------------------------------------------------------
    # Debe existir HORARIA
    # --------------------------------------------------------

    if "HORARIA" not in upper_content:

        fail(
            context,
            64,
            (
                "El CSV descargado no contiene frecuencia HORARIA. "
                "Canal ha devuelto datos de otra periodicidad."
            ),
        )


    # --------------------------------------------------------
    # Información adicional
    # --------------------------------------------------------

    lines = [
        line
        for line in content.splitlines()
        if line.strip()
    ]


    _LOGGER.info(
        "CSV horario validado: %s líneas no vacías.",
        len(lines),
    )


    # Si vemos DIARIA además de HORARIA lo registramos.
    # No lo tratamos automáticamente como error porque
    # podría aparecer en alguna cabecera/texto auxiliar.

    if "DIARIA" in upper_content:

        _LOGGER.warning(
            (
                "El CSV contiene también el texto DIARIA. "
                "Se mantiene la descarga porque contiene HORARIA."
            )
        )


    _LOGGER.info(
        "Validación CSV correcta: frecuencia HORARIA confirmada."
    )


# ============================================================
# Main
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

    SHARE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


    remove_profile_locks()


    with sync_playwright() as p:

        _LOGGER.info(
            "Abriendo Telelecturas con Chromium headless..."
        )


        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            viewport={
                "width": 1360,
                "height": 850,
            },
            accept_downloads=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )


        restore_session(
            context
        )


        try:

            page = (
                context.pages[0]
                if context.pages
                else context.new_page()
            )


            # ------------------------------------------------
            # Diagnóstico de red
            # ------------------------------------------------

            page.on(
                "request",
                log_request,
            )

            page.on(
                "response",
                log_response,
            )


            # ------------------------------------------------
            # Abrir Telelecturas
            # ------------------------------------------------

            try:

                page.goto(
                    CONSUMO_URL,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

                page.wait_for_timeout(
                    4000
                )

            except PlaywrightTimeoutError:

                fail(
                    context,
                    20,
                    "Timeout abriendo la página de consumo.",
                )


            _LOGGER.info(
                "URL actual: %s",
                page.url,
            )


            # ------------------------------------------------
            # Verificar sesión
            # ------------------------------------------------

            if not session_is_valid(page):

                fail(
                    context,
                    30,
                    (
                        "La sesión ha caducado o requiere "
                        "autenticación manual. "
                        "Cambia mode a login."
                    ),
                    auth=True,
                )


            _LOGGER.info(
                "Sesión autenticada."
            )


            # ------------------------------------------------
            # Abrir filtros
            # ------------------------------------------------

            open_filters(
                page
            )


            # ------------------------------------------------
            # Seleccionar HORARIA y ENVIAR formulario
            # ------------------------------------------------

            select_and_apply_hourly(
                page,
                context,
            )


            # ------------------------------------------------
            # Descargar CSV generado tras la búsqueda horaria
            # ------------------------------------------------

            size = download_csv(
                page,
                context,
            )


            # ------------------------------------------------
            # Verificar que Canal realmente devuelve HORARIA
            # ------------------------------------------------

            validate_hourly_csv(
                context
            )


            # ------------------------------------------------
            # Éxito
            # ------------------------------------------------

            _LOGGER.info(
                "CSV descargado correctamente: %s (%s bytes)",
                CSV_FILE,
                size,
            )


            write_status(
                "ok",
                "Descarga horaria realizada correctamente.",
                0,
                size,
            )


            _LOGGER.info(
                "Proceso completado correctamente."
            )


        finally:

            try:
                context.close()

            except Exception:
                pass


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":

    try:
        main()

    except SystemExit:
        raise

    except Exception as err:

        _LOGGER.exception(
            "Error inesperado: %s",
            err,
        )

        write_status(
            "error",
            f"Error inesperado: {err}",
            99,
        )

        sys.exit(99)