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
# RUTAS
# ============================================================

CONFIG_DIR = Path("/config")

SHARE_DIR = Path("/share")

CSV_FILE = (
    SHARE_DIR
    / "canal_consumo_horario.csv"
)

STATUS_FILE = (
    SHARE_DIR
    / "canal_estado.json"
)

SESSION_FILE = (
    CONFIG_DIR
    / "canal_session.json"
)

SESSION_STORAGE_FILE = (
    CONFIG_DIR
    / "canal_session_storage.json"
)


# ============================================================
# URL
# ============================================================

CONSUMO_URL = (
    "https://oficinavirtual.canaldeisabelsegunda.es/"
    "group/ovir/consumo"
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

_LOGGER = logging.getLogger(
    "canal"
)


# ============================================================
# ESTADO HOME ASSISTANT
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
        "ultima_ejecucion": (
            datetime
            .now()
            .astimezone()
            .isoformat()
        ),
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
            (
                "No se pudo escribir "
                "canal_estado.json: %s"
            ),
            err,
        )


# ============================================================
# ERROR CONTROLADO
# ============================================================

def fail(
    context,
    code: int,
    message: str,
    auth: bool = False,
) -> None:

    _LOGGER.error(
        message
    )


    write_status(
        (
            "reautenticacion_requerida"
            if auth
            else "error"
        ),
        message,
        code,
    )


    try:
        context.close()

    except Exception:
        pass


    raise SystemExit(
        code
    )


# ============================================================
# SESSION STORAGE
# ============================================================

def load_session_storage() -> dict:

    if not SESSION_STORAGE_FILE.exists():

        _LOGGER.info(
            (
                "No existe sessionStorage "
                "guardado. Se continuará."
            )
        )

        return {}


    try:

        data = json.loads(
            SESSION_STORAGE_FILE.read_text(
                encoding="utf-8"
            )
        )


        _LOGGER.info(
            (
                "sessionStorage cargado "
                "para %s origins."
            ),
            len(data),
        )


        return data


    except Exception as err:

        _LOGGER.warning(
            (
                "No se pudo cargar "
                "sessionStorage: %s"
            ),
            err,
        )

        return {}


def install_session_storage(
    context,
    session_storage: dict,
) -> None:

    if not session_storage:
        return


    # Este script se ejecuta ANTES que el JavaScript
    # de la página en cada navegación.

    script = """
    (storageByOrigin) => {

        try {

            const data =
                storageByOrigin[
                    window.location.origin
                ];

            if (!data) {
                return;
            }

            for (
                const [key, value]
                of Object.entries(data)
            ) {
                sessionStorage.setItem(
                    key,
                    value
                );
            }

        } catch (error) {

            console.error(
                "Error restaurando sessionStorage:",
                error
            );

        }
    }
    """


    context.add_init_script(
        script=(
            f"({script})"
            f"({json.dumps(session_storage)});"
        )
    )


# ============================================================
# ACTUALIZAR SESIÓN
# ============================================================

def save_updated_session(
    context,
    page,
) -> None:

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
        # sessionStorage actual
        # ----------------------------------------------------

        session_storage = {}


        try:

            origin = page.evaluate(
                "() => window.location.origin"
            )

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


            if (
                origin
                and storage
            ):

                session_storage[
                    origin
                ] = storage


        except Exception:
            pass


        if session_storage:

            SESSION_STORAGE_FILE.write_text(
                json.dumps(
                    session_storage,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )


        _LOGGER.info(
            "Estado de sesión actualizado."
        )


    except Exception as err:

        _LOGGER.warning(
            (
                "No se pudo actualizar "
                "el estado de sesión: %s"
            ),
            err,
        )


# ============================================================
# COMPROBAR SESIÓN
# ============================================================

def session_is_valid(
    page,
) -> bool:

    url = page.url.lower()


    if (
        "/group/ovir/" in url
        and "/login" not in url
    ):

        return True


    try:

        if (
            page
            .locator(
                'input[type="password"]'
            )
            .count()
            > 0
        ):

            return False


    except Exception:
        pass


    return False


# ============================================================
# DIAGNÓSTICO DE RED
# ============================================================

def log_request(
    request,
) -> None:

    url = (
        request
        .url
        .lower()
    )


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


def log_response(
    response,
) -> None:

    url = (
        response
        .url
        .lower()
    )


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
# ABRIR FILTROS
# ============================================================

def open_filters(
    page,
) -> None:

    try:

        show_filters = (
            page
            .get_by_text(
                "Mostrar filtros",
                exact=False,
            )
        )


        if (
            show_filters.count() > 0
            and show_filters.first.is_visible()
        ):

            _LOGGER.info(
                "Abriendo filtros..."
            )


            show_filters.first.click()


            page.wait_for_timeout(
                1000
            )


    except Exception as err:

        _LOGGER.warning(
            (
                "No se pudieron abrir "
                "los filtros: %s"
            ),
            err,
        )


# ============================================================
# SELECTOR PERIODICIDAD
# ============================================================

def find_periodicity_selector(
    page,
):

    periodicity = page.locator(
        "select#selectPeriodicidad"
    )


    if periodicity.count() == 0:

        periodicity = page.locator(
            'select[id*="selectPeriodicidad"]'
        )


    return periodicity


# ============================================================
# APLICAR HORARIA
# ============================================================

def select_and_apply_hourly(
    page,
    context,
) -> None:

    _LOGGER.info(
        "Buscando selector de periodicidad..."
    )


    periodicity = (
        find_periodicity_selector(
            page
        )
    )


    if periodicity.count() == 0:

        fail(
            context,
            40,
            (
                "No se encuentra el selector "
                "de periodicidad."
            ),
        )


    periodicity = periodicity.first


    _LOGGER.info(
        (
            "Selector encontrado. "
            "Seleccionando frecuencia HORARIA..."
        )
    )


    selected = False


    # --------------------------------------------------------
    # Por label
    # --------------------------------------------------------

    try:

        periodicity.select_option(
            label="Horaria"
        )

        selected = True

    except Exception:
        pass


    # --------------------------------------------------------
    # Por value
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
    # Buscar opción por texto
    # --------------------------------------------------------

    if not selected:

        options = periodicity.locator(
            "option"
        )


        for index in range(
            options.count()
        ):

            option = options.nth(
                index
            )


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

                value = (
                    option
                    .get_attribute(
                        "value"
                    )
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
            (
                "Se encontró el selector, "
                "pero no la opción Horaria."
            ),
        )


    # --------------------------------------------------------
    # Verificar selector
    # --------------------------------------------------------

    try:

        selected_text = (
            periodicity
            .locator(
                "option:checked"
            )
            .inner_text()
            .strip()
        )


        _LOGGER.info(
            (
                "Periodicidad actualmente "
                "seleccionada: %s"
            ),
            selected_text,
        )


        if (
            "horaria"
            not in selected_text.lower()
        ):

            fail(
                context,
                42,
                (
                    "El selector no quedó "
                    "realmente en Horaria."
                ),
            )


    except SystemExit:
        raise


    except Exception as err:

        _LOGGER.warning(
            (
                "No se pudo verificar "
                "el selector: %s"
            ),
            err,
        )


    # --------------------------------------------------------
    # Formulario
    # --------------------------------------------------------

    form = periodicity.locator(
        "xpath=ancestor::form[1]"
    )


    if form.count() == 0:

        fail(
            context,
            43,
            (
                "No se encontró el formulario "
                "asociado al selector."
            ),
        )


    form = form.first


    try:

        _LOGGER.info(
            "Formulario Telelecturas: method=%s action=%s",
            form.get_attribute(
                "method"
            ),
            form.get_attribute(
                "action"
            ),
        )

    except Exception:
        pass


    _LOGGER.info(
        (
            "Enviando formulario de Telelecturas "
            "con periodicidad HORARIA..."
        )
    )


    # --------------------------------------------------------
    # Submit real
    # --------------------------------------------------------

    try:

        form.evaluate(
            """
            form => {

                if (
                    typeof form.requestSubmit
                    === 'function'
                ) {

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
            (
                "Error enviando formulario "
                f"de Telelecturas: {err}"
            ),
        )


    # --------------------------------------------------------
    # Esperar actualización
    # --------------------------------------------------------

    page.wait_for_timeout(
        7000
    )


    if not session_is_valid(
        page
    ):

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
    # Confirmar texto
    # --------------------------------------------------------

    try:

        body_text = (
            page
            .locator("body")
            .inner_text(
                timeout=10000
            )
        )

    except Exception:

        body_text = ""


    normalized = re.sub(
        r"\s+",
        " ",
        body_text,
    ).upper()


    if (
        "FRECUENCIA HORARIA"
        in normalized
    ):

        _LOGGER.info(
            "Consulta HORARIA aplicada correctamente."
        )

    else:

        _LOGGER.warning(
            (
                "No se encontró FRECUENCIA HORARIA "
                "en la página. "
                "El CSV será validado."
            )
        )


# ============================================================
# BUSCAR ENLACE CSV
# ============================================================

def find_csv_link(
    page,
    context,
):

    _LOGGER.info(
        "Buscando enlace de exportación CSV..."
    )


    selectors = [

        'a[href*="export-csv"]',

        (
            'a[href*='
            '"Telelecturas%2Fexport-csv"]'
        ),

        (
            'a[href*='
            '"Telelecturas/export-csv"]'
        ),

        'a[href*="fileFormat=CSV"]',

        (
            'a[href*='
            '"fileFormat%3DCSV"]'
        ),
    ]


    for selector in selectors:

        links = page.locator(
            selector
        )


        if links.count() > 0:

            _LOGGER.info(
                (
                    "Enlace CSV encontrado "
                    "con selector: %s"
                ),
                selector,
            )


            try:

                _LOGGER.info(
                    "URL exportación CSV: %s",
                    links.first.get_attribute(
                        "href"
                    ),
                )

            except Exception:
                pass


            return links.first


    fail(
        context,
        50,
        (
            "No se encuentra el enlace "
            "de exportación CSV."
        ),
    )


# ============================================================
# DESCARGAR CSV
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
                    "No se puede borrar "
                    f"el CSV anterior: {err}"
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


        download = (
            download_info.value
        )


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
            (
                "Error descargando CSV: "
                f"{err}"
            ),
        )


    if not CSV_FILE.exists():

        fail(
            context,
            61,
            (
                "La descarga terminó "
                "pero el CSV no existe."
            ),
        )


    size = (
        CSV_FILE
        .stat()
        .st_size
    )


    if size == 0:

        fail(
            context,
            62,
            "El CSV descargado está vacío.",
        )


    return size


# ============================================================
# LEER CSV
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
            (
                "No se puede leer "
                f"el CSV: {err}"
            ),
        )


    for encoding in (

        "utf-8-sig",
        "utf-8",
        "cp1252",
        "latin-1",

    ):

        try:

            text = raw.decode(
                encoding
            )


            _LOGGER.info(
                (
                    "CSV leído usando "
                    "codificación %s."
                ),
                encoding,
            )


            return text


        except UnicodeDecodeError:
            continue


    fail(
        context,
        63,
        (
            "No se pudo determinar "
            "la codificación del CSV."
        ),
    )


# ============================================================
# VALIDAR CSV HORARIO
# ============================================================

def validate_hourly_csv(
    context,
) -> None:

    content = read_csv_text(
        context
    )


    upper_content = (
        content.upper()
    )


    if (
        "HORARIA"
        not in upper_content
    ):

        fail(
            context,
            64,
            (
                "El CSV descargado no contiene "
                "frecuencia HORARIA."
            ),
        )


    lines = [

        line

        for line
        in content.splitlines()

        if line.strip()

    ]


    _LOGGER.info(
        (
            "CSV horario validado: "
            "%s líneas no vacías."
        ),
        len(lines),
    )


    _LOGGER.info(
        (
            "Validación CSV correcta: "
            "frecuencia HORARIA confirmada."
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

    SHARE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


    # --------------------------------------------------------
    # Sesión obligatoria
    # --------------------------------------------------------

    if not SESSION_FILE.exists():

        write_status(
            "reautenticacion_requerida",
            (
                "No existe sesión guardada. "
                "Cambia mode a login."
            ),
            30,
        )

        raise SystemExit(
            30
        )


    with sync_playwright() as p:

        _LOGGER.info(
            (
                "Abriendo Telelecturas "
                "con Chromium automático..."
            )
        )


        # ----------------------------------------------------
        # IMPORTANTE:
        #
        # headless=False dentro de Xvfb.
        #
        # De esta forma Chromium utiliza el mismo tipo
        # de navegador que durante el login manual.
        # ----------------------------------------------------

        browser = p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )


        try:

            # ------------------------------------------------
            # RESTAURAR STORAGE_STATE COMPLETO
            #
            # Aquí Playwright restaura:
            #
            # - cookies
            # - localStorage
            # - IndexedDB
            # ------------------------------------------------

            context = browser.new_context(
                storage_state=str(
                    SESSION_FILE
                ),
                viewport={
                    "width": 1360,
                    "height": 850,
                },
                accept_downloads=True,
            )


            # ------------------------------------------------
            # RESTAURAR sessionStorage
            # ------------------------------------------------

            session_storage = (
                load_session_storage()
            )


            install_session_storage(
                context,
                session_storage,
            )


            state = json.loads(
                SESSION_FILE.read_text(
                    encoding="utf-8"
                )
            )


            _LOGGER.info(
                (
                    "Storage state restaurado: "
                    "%s cookies, %s origins."
                ),
                len(
                    state.get(
                        "cookies",
                        [],
                    )
                ),
                len(
                    state.get(
                        "origins",
                        [],
                    )
                ),
            )


            # ------------------------------------------------
            # Página
            # ------------------------------------------------

            page = context.new_page()


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
                    5000
                )


            except PlaywrightTimeoutError:

                fail(
                    context,
                    20,
                    (
                        "Timeout abriendo "
                        "la página de consumo."
                    ),
                )


            _LOGGER.info(
                "URL actual: %s",
                page.url,
            )


            # ------------------------------------------------
            # Validar autenticación
            # ------------------------------------------------

            if not session_is_valid(
                page
            ):

                fail(
                    context,
                    30,
                    (
                        "La sesión guardada ya no es válida. "
                        "Cambia mode a login y vuelve "
                        "a autenticarte."
                    ),
                    auth=True,
                )


            _LOGGER.info(
                "Sesión autenticada correctamente."
            )


            # ------------------------------------------------
            # Filtros
            # ------------------------------------------------

            open_filters(
                page
            )


            select_and_apply_hourly(
                page,
                context,
            )


            # ------------------------------------------------
            # CSV
            # ------------------------------------------------

            size = download_csv(
                page,
                context,
            )


            validate_hourly_csv(
                context
            )


            # ------------------------------------------------
            # Actualizar estado de sesión
            # ------------------------------------------------

            save_updated_session(
                context,
                page,
            )


            # ------------------------------------------------
            # OK
            # ------------------------------------------------

            _LOGGER.info(
                (
                    "CSV descargado correctamente: "
                    "%s (%s bytes)"
                ),
                CSV_FILE,
                size,
            )


            write_status(
                "ok",
                (
                    "Descarga horaria "
                    "realizada correctamente."
                ),
                0,
                size,
            )


            _LOGGER.info(
                "Proceso completado correctamente."
            )


        finally:

            try:
                browser.close()

            except Exception:
                pass


# ============================================================
# ENTRY POINT
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
            (
                "Error inesperado: "
                f"{err}"
            ),
            99,
        )


        sys.exit(
            99
        )