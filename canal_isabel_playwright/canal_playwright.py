from __future__ import annotations

import csv
import io
import json
import logging
import re
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
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

CSV_FILE = SHARE_DIR / "canal_consumo_horario.csv"
STATUS_FILE = SHARE_DIR / "canal_estado.json"

RESUMEN_FILE = SHARE_DIR / "canal_resumen.json"
HISTORICO_FILE = SHARE_DIR / "canal_historico_diario.json"

SESSION_FILE = CONFIG_DIR / "canal_session.json"
SESSION_STORAGE_FILE = CONFIG_DIR / "canal_session_storage.json"

HISTORY_BOOTSTRAP_DAYS = 30
HISTORY_REFRESH_DAYS = 7

# Un día se considera completo cuando Canal entrega
# al menos 23 registros horarios.
MIN_COMPLETE_HOURS = 23

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

_LOGGER = logging.getLogger("canal")


# ============================================================
# UTILIDADES JSON
# ============================================================

def write_json_atomic(
    path: Path,
    data: dict,
) -> None:
    """
    Escribe un JSON de forma atómica.

    Primero genera un fichero temporal y después lo sustituye,
    reduciendo el riesgo de dejar un JSON corrupto si el add-on
    se detiene durante la escritura.
    """

    temp_file = path.with_suffix(
        path.suffix + ".tmp"
    )

    temp_file.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temp_file.replace(
        path
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
        write_json_atomic(
            STATUS_FILE,
            data,
        )

    except Exception as err:
        _LOGGER.warning(
            "No se pudo escribir canal_estado.json: %s",
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
            "sessionStorage cargado para %s origins.",
            len(data),
        )

        return data

    except Exception as err:

        _LOGGER.warning(
            "No se pudo cargar sessionStorage: %s",
            err,
        )

        return {}


def install_session_storage(
    context,
    session_storage: dict,
) -> None:

    if not session_storage:
        return

    storage_json = json.dumps(
        session_storage,
        ensure_ascii=False,
    )

    context.add_init_script(
        script=f"""
        (() => {{
            const storageByOrigin = {storage_json};

            try {{
                const data =
                    storageByOrigin[
                        window.location.origin
                    ];

                if (!data) {{
                    return;
                }}

                for (
                    const [key, value]
                    of Object.entries(data)
                ) {{
                    sessionStorage.setItem(
                        key,
                        value
                    );
                }}

            }} catch (error) {{
                console.error(
                    "Error restaurando sessionStorage:",
                    error
                );
            }}
        }})();
        """
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

        write_json_atomic(
            SESSION_FILE,
            state,
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

            if origin and storage:

                session_storage[
                    origin
                ] = storage

        except Exception:
            pass

        if session_storage:

            write_json_atomic(
                SESSION_STORAGE_FILE,
                session_storage,
            )

        _LOGGER.info(
            "Estado de sesión actualizado."
        )

    except Exception as err:

        _LOGGER.warning(
            "No se pudo actualizar el estado de sesión: %s",
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

def is_relevant_network_url(
    raw_url: str,
) -> bool:
    """
    Solo registra las peticiones reales al flujo de consumo
    de Canal.

    Excluye:
    - CSS
    - JavaScript
    - imágenes
    - Google Analytics
    - recursos auxiliares de Liferay
    """

    url = raw_url.lower()

    return url.startswith(
        (
            "https://oficinavirtual."
            "canaldeisabelsegunda.es/"
            "group/ovir/consumo"
        )
    )


def log_request(
    request,
) -> None:

    if not is_relevant_network_url(
        request.url
    ):
        return

    _LOGGER.info(
        "REQUEST %s %s",
        request.method,
        request.url,
    )

    # El cuerpo POST nos interesa especialmente porque
    # permite comprobar las fechas y la periodicidad
    # realmente enviadas a Canal.
    if request.method.upper() == "POST":

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

    if not is_relevant_network_url(
        response.url
    ):
        return

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
            "No se pudieron abrir los filtros: %s",
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
    start_date: date,
    end_date: date,
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
            "Periodicidad actualmente seleccionada: %s",
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
            "No se pudo verificar el selector: %s",
            err,
        )

    # --------------------------------------------------------
    # IMPORTANTE:
    # Canal modifica las fechas al cambiar periodicidad.
    # Esperamos a que termine su Javascript y SOLO DESPUÉS
    # aplicamos nuestro rango.
    # --------------------------------------------------------

    _LOGGER.info(
        (
            "Esperando estabilización del formulario "
            "tras seleccionar Horaria..."
        )
    )

    page.wait_for_timeout(
        1000
    )

    set_date_range(
        page,
        context,
        start_date,
        end_date,
    )

    # --------------------------------------------------------
    # Verificación final de fechas
    # justo antes del submit
    # --------------------------------------------------------

    fecha_desde_field = (
        page
        .locator(
            'input[name$="fechaDesde"]'
        )
        .first
    )

    fecha_hasta_field = (
        page
        .locator(
            'input[name$="fechaHasta"]'
        )
        .first
    )

    fecha_desde_final = (
        fecha_desde_field
        .input_value()
    )

    fecha_hasta_final = (
        fecha_hasta_field
        .input_value()
    )

    periodicidad_final = (
        periodicity
        .locator(
            "option:checked"
        )
        .inner_text()
        .strip()
    )

    _LOGGER.info(
        "Valores finales ANTES DEL SUBMIT:"
    )

    _LOGGER.info(
        "  fechaDesde = %s",
        fecha_desde_final,
    )

    _LOGGER.info(
        "  fechaHasta = %s",
        fecha_hasta_final,
    )

    _LOGGER.info(
        "  periodicidad = %s",
        periodicidad_final,
    )

    expected_start = (
        start_date.isoformat()
    )

    expected_end = (
        end_date.isoformat()
    )

    if (
        fecha_desde_final
        != expected_start
        or fecha_hasta_final
        != expected_end
    ):

        _LOGGER.warning(
            (
                "Canal volvió a modificar las fechas. "
                "Se intentará restaurarlas una vez más."
            )
        )

        set_date_range(
            page,
            context,
            start_date,
            end_date,
        )

        fecha_desde_final = (
            fecha_desde_field
            .input_value()
        )

        fecha_hasta_final = (
            fecha_hasta_field
            .input_value()
        )

        _LOGGER.info(
            "Valores tras segundo ajuste:"
        )

        _LOGGER.info(
            "  fechaDesde = %s",
            fecha_desde_final,
        )

        _LOGGER.info(
            "  fechaHasta = %s",
            fecha_hasta_final,
        )

    if (
        fecha_desde_final
        != expected_start
        or fecha_hasta_final
        != expected_end
    ):

        fail(
            context,
            47,
            (
                "Las fechas no permanecen configuradas "
                "antes de enviar el formulario. "
                f"Esperado={expected_start}->{expected_end}, "
                f"actual={fecha_desde_final}->{fecha_hasta_final}"
            ),
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
                "Enlace CSV encontrado con selector: %s",
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
                "CSV leído usando codificación %s.",
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
) -> str:

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
        "CSV horario validado: %s líneas no vacías.",
        len(lines),
    )

    _LOGGER.info(
        (
            "Validación CSV correcta: "
            "frecuencia HORARIA confirmada."
        )
    )

    return content


# ============================================================
# PARSEAR CONSUMO HORARIO
# ============================================================

def parse_decimal(
    value: str,
) -> Decimal:

    value = (
        str(value)
        .strip()
        .replace(",", ".")
    )

    try:
        return Decimal(
            value
        )

    except InvalidOperation:
        raise ValueError(
            f"Valor de consumo no válido: {value}"
        )


def parse_hourly_csv(
    context,
    content: str,
) -> dict:

    reader = csv.DictReader(
        io.StringIO(
            content
        )
    )

    required_columns = {
        "Contrato",
        "Contador",
        "Frecuencia",
        "Fecha/Hora",
        "Consumo (litros)",
    }

    fieldnames = set(
        reader.fieldnames or []
    )

    missing = (
        required_columns
        - fieldnames
    )

    if missing:

        fail(
            context,
            70,
            (
                "Faltan columnas obligatorias "
                f"en el CSV: {sorted(missing)}"
            ),
        )

    # --------------------------------------------------------
    # Estructura:
    #
    # dias["2026-08-28"]["horas"]["09"] = Decimal(...)
    # --------------------------------------------------------

    dias = {}

    contrato = None
    contador = None

    total_rows = 0

    for row in reader:

        frecuencia = (
            row
            .get(
                "Frecuencia",
                ""
            )
            .strip()
            .upper()
        )

        if frecuencia != "HORARIA":
            continue

        fecha_hora = (
            row
            .get(
                "Fecha/Hora",
                ""
            )
            .strip()
        )

        consumo_text = (
            row
            .get(
                "Consumo (litros)",
                ""
            )
            .strip()
        )

        if not fecha_hora:
            continue

        parts = (
            fecha_hora
            .rsplit(
                " ",
                1
            )
        )

        if len(parts) != 2:

            fail(
                context,
                71,
                (
                    "Formato Fecha/Hora inesperado "
                    f"en el CSV: {fecha_hora}"
                ),
            )

        fecha_text = parts[0]
        hora_text = parts[1]

        try:

            fecha_obj = datetime.strptime(
                fecha_text,
                "%d/%m/%Y",
            ).date()

        except ValueError:

            fail(
                context,
                72,
                (
                    "Fecha no válida en el CSV: "
                    f"{fecha_text}"
                ),
            )

        try:

            hora_num = int(
                hora_text
            )

        except ValueError:

            fail(
                context,
                73,
                (
                    "Hora no válida en el CSV: "
                    f"{hora_text}"
                ),
            )

        if (
            hora_num < 0
            or hora_num > 24
        ):

            fail(
                context,
                74,
                (
                    "Hora fuera de rango en el CSV: "
                    f"{hora_num}"
                ),
            )

        consumo = parse_decimal(
            consumo_text
        )

        fecha_iso = (
            fecha_obj
            .isoformat()
        )

        hora_key = (
            f"{hora_num:02d}"
        )

        day_data = dias.setdefault(
            fecha_iso,
            {
                "fecha": fecha_iso,
                "horas": {},
            },
        )

        # Si hubiera dos registros para una misma hora,
        # se suman en lugar de perder datos.
        day_data[
            "horas"
        ][
            hora_key
        ] = (
            day_data[
                "horas"
            ].get(
                hora_key,
                Decimal("0"),
            )
            + consumo
        )

        contrato = (
            contrato
            or row.get(
                "Contrato"
            )
        )

        contador = (
            contador
            or row.get(
                "Contador"
            )
        )

        total_rows += 1

    if not dias:

        fail(
            context,
            75,
            (
                "No se encontraron registros "
                "HORARIOS válidos en el CSV."
            ),
        )

    _LOGGER.info(
        (
            "CSV parseado correctamente: "
            "%s registros horarios, %s días."
        ),
        total_rows,
        len(dias),
    )

    fechas_recibidas = sorted(
        dias.keys()
    )

    _LOGGER.info(
        (
            "Rango realmente recibido en CSV: "
            "%s -> %s."
        ),
        fechas_recibidas[0],
        fechas_recibidas[-1],
    )

    return {
        "contrato": contrato,
        "contador": contador,
        "dias": dias,
    }


# ============================================================
# RESUMEN DE UN DÍA
# ============================================================

def decimal_to_float(
    value: Decimal,
) -> float:

    return float(
        value.quantize(
            Decimal("0.01")
        )
    )


def build_day_summary(
    fecha_iso: str,
    horas: dict,
) -> dict:

    values = list(
        horas.values()
    )

    total = sum(
        values,
        Decimal("0"),
    )

    horas_recibidas = len(
        horas
    )

    if horas_recibidas > 0:

        media = (
            total
            / Decimal(
                horas_recibidas
            )
        )

    else:

        media = Decimal(
            "0"
        )

    horas_con_consumo = sum(
        1
        for value in values
        if value > 0
    )

    # --------------------------------------------------------
    # Máximo horario
    # --------------------------------------------------------

    hora_maximo = None
    maximo = Decimal(
        "0"
    )

    if horas:

        hora_maximo, maximo = max(
            horas.items(),
            key=lambda item: (
                item[1],
                -int(item[0]),
            ),
        )

    # --------------------------------------------------------
    # Franjas
    #
    # 00-06 -> nocturno
    # 07-12 -> mañana
    # 13-18 -> tarde
    # 19-24 -> noche
    #
    # Canal actualmente entrega 01..23 en el CSV observado,
    # pero soportamos también 00 y 24 por si apareciesen.
    # --------------------------------------------------------

    consumo_nocturno = Decimal(
        "0"
    )

    consumo_manana = Decimal(
        "0"
    )

    consumo_tarde = Decimal(
        "0"
    )

    consumo_noche = Decimal(
        "0"
    )

    for hour_key, consumo in horas.items():

        hour = int(
            hour_key
        )

        if 0 <= hour <= 6:

            consumo_nocturno += consumo

        elif 7 <= hour <= 12:

            consumo_manana += consumo

        elif 13 <= hour <= 18:

            consumo_tarde += consumo

        else:

            consumo_noche += consumo

    return {
        "fecha": fecha_iso,

        "consumo_total_l": decimal_to_float(
            total
        ),

        "media_horaria_l": decimal_to_float(
            media
        ),

        "maximo_horario_l": decimal_to_float(
            maximo
        ),

        "hora_maximo": hora_maximo,

        "horas_con_consumo": (
            horas_con_consumo
        ),

        "horas_recibidas": (
            horas_recibidas
        ),

        "consumo_nocturno_l": decimal_to_float(
            consumo_nocturno
        ),

        "consumo_manana_l": decimal_to_float(
            consumo_manana
        ),

        "consumo_tarde_l": decimal_to_float(
            consumo_tarde
        ),

        "consumo_noche_l": decimal_to_float(
            consumo_noche
        ),

        "consumo_por_hora": {
            key: decimal_to_float(
                value
            )
            for key, value
            in sorted(
                horas.items()
            )
        },
    }


# ============================================================
# HISTÓRICO DIARIO
# ============================================================

def load_history() -> dict:

    if not HISTORICO_FILE.exists():

        return {
            "ultima_actualizacion": None,
            "dias": {},
        }

    try:

        data = json.loads(
            HISTORICO_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            data,
            dict,
        ):

            raise ValueError(
                "Formato histórico inválido."
            )

        if not isinstance(
            data.get(
                "dias"
            ),
            dict,
        ):

            data[
                "dias"
            ] = {}

        return data

    except Exception as err:

        _LOGGER.warning(
            (
                "No se pudo leer el histórico "
                "existente: %s. "
                "Se creará uno nuevo."
            ),
            err,
        )

        return {
            "ultima_actualizacion": None,
            "dias": {},
        }


def update_history(
    parsed_data: dict,
) -> dict:

    history = load_history()

    days = history.setdefault(
        "dias",
        {},
    )

    previous_count = len(
        days
    )

    received_count = len(
        parsed_data[
            "dias"
        ]
    )

    new_days = 0
    updated_days = 0

    incomplete_days = 0
    removed_incomplete_days = 0

    for fecha_iso, data in (
        parsed_data[
            "dias"
        ].items()
    ):

        horas = data.get(
            "horas",
            {},
        )

        horas_recibidas = len(
            horas
        )

        # ----------------------------------------------------
        # NO guardar días incompletos
        # ----------------------------------------------------

        if (
            horas_recibidas
            < MIN_COMPLETE_HOURS
        ):

            incomplete_days += 1

            # Si una versión anterior guardó ese día como
            # válido, lo eliminamos automáticamente.
            if fecha_iso in days:

                del days[
                    fecha_iso
                ]

                removed_incomplete_days += 1

                _LOGGER.warning(
                    (
                        "Día %s eliminado del histórico: "
                        "solo contiene %s horas."
                    ),
                    fecha_iso,
                    horas_recibidas,
                )

            else:

                _LOGGER.warning(
                    (
                        "Día %s ignorado: "
                        "solo contiene %s horas."
                    ),
                    fecha_iso,
                    horas_recibidas,
                )

            continue

        # ----------------------------------------------------
        # Día completo
        # ----------------------------------------------------

        summary = build_day_summary(
            fecha_iso,
            horas,
        )

        if fecha_iso in days:

            updated_days += 1

        else:

            new_days += 1

        days[
            fecha_iso
        ] = summary[
            "consumo_total_l"
        ]

    # --------------------------------------------------------
    # Orden cronológico
    # --------------------------------------------------------

    history[
        "dias"
    ] = dict(
        sorted(
            days.items()
        )
    )

    history[
        "ultima_actualizacion"
    ] = (
        datetime
        .now()
        .astimezone()
        .isoformat()
    )

    write_json_atomic(
        HISTORICO_FILE,
        history,
    )

    final_count = len(
        history[
            "dias"
        ]
    )

    _LOGGER.info(
        "Actualización del histórico:"
    )

    _LOGGER.info(
        "  Días almacenados anteriormente: %s",
        previous_count,
    )

    _LOGGER.info(
        "  Días recibidos en esta ejecución: %s",
        received_count,
    )

    _LOGGER.info(
        "  Días nuevos añadidos: %s",
        new_days,
    )

    _LOGGER.info(
        "  Días existentes actualizados: %s",
        updated_days,
    )

    _LOGGER.info(
        "  Días incompletos ignorados: %s",
        incomplete_days,
    )

    _LOGGER.info(
        (
            "  Días incompletos eliminados "
            "del histórico: %s"
        ),
        removed_incomplete_days,
    )

    _LOGGER.info(
        "  Total de días almacenados: %s",
        final_count,
    )

    return history

# ============================================================
# MÉTRICAS HISTÓRICAS
# ============================================================

def get_history_window(
    history: dict,
    reference_date: date,
    days_count: int,
) -> list[float]:

    start_date = (
        reference_date
        - timedelta(
            days=days_count - 1
        )
    )

    values = []

    for fecha_iso, value in (
        history
        .get(
            "dias",
            {}
        )
        .items()
    ):

        try:

            fecha = date.fromisoformat(
                fecha_iso
            )

        except ValueError:
            continue

        if (
            start_date
            <= fecha
            <= reference_date
        ):

            try:

                values.append(
                    float(
                        value
                    )
                )

            except (
                TypeError,
                ValueError,
            ):
                continue

    return values


def average(
    values: list[float],
) -> float | None:

    if not values:
        return None

    return round(
        sum(values)
        / len(values),
        2,
    )


def variation_percent(
    current: float,
    average_value: float | None,
) -> float | None:

    if (
        average_value is None
        or average_value == 0
    ):

        return None

    return round(
        (
            (
                current
                - average_value
            )
            / average_value
        )
        * 100,
        1,
    )


# ============================================================
# GENERAR RESUMEN JSON
# ============================================================
def log_history_integrity(
    history: dict,
    reference_date: date,
) -> None:

    existing_dates = set()

    for fecha_iso in (
        history
        .get(
            "dias",
            {},
        )
        .keys()
    ):

        try:

            existing_dates.add(
                date.fromisoformat(
                    fecha_iso
                )
            )

        except ValueError:
            continue

    for days_count in (
        7,
        30,
    ):

        start_date = (
            reference_date
            - timedelta(
                days=days_count - 1
            )
        )

        expected = [
            start_date
            + timedelta(days=i)
            for i in range(
                days_count
            )
        ]

        available = sum(
            1
            for current_date in expected
            if current_date in existing_dates
        )

        missing = [
            current_date
            for current_date in expected
            if current_date
            not in existing_dates
        ]

        _LOGGER.info(
            (
                "Integridad últimos %s días: "
                "%s/%s disponibles."
            ),
            days_count,
            available,
            days_count,
        )

        if missing:

            _LOGGER.warning(
                (
                    "Quedan %s huecos "
                    "en los últimos %s días."
                ),
                len(missing),
                days_count,
            )

            if len(missing) <= 10:

                _LOGGER.warning(
                    "Huecos: %s",
                    ", ".join(
                        current_date.isoformat()
                        for current_date
                        in missing
                    ),
                )

def generate_summary_files(
    context,
    parsed_data: dict,
) -> dict:

    history = update_history(
        parsed_data
    )

    # ------------------------------------------------------------
    # Solo utilizar días completos para canal_resumen.json
    # ------------------------------------------------------------

    complete_days = {

        fecha_iso: data

        for fecha_iso, data
        in parsed_data[
            "dias"
        ].items()

        if len(
            data.get(
                "horas",
                {},
            )
        ) >= MIN_COMPLETE_HOURS
    }

    if not complete_days:

        fail(
            context,
            76,
            (
                "El CSV no contiene ningún día "
                f"con al menos {MIN_COMPLETE_HOURS} "
                "horas de datos."
            ),
        )

    latest_received_date_iso = max(
        parsed_data[
            "dias"
        ].keys()
    )

    latest_date_iso = max(
        complete_days.keys()
    )

    if (
        latest_received_date_iso
        != latest_date_iso
    ):

        latest_received_hours = len(
            parsed_data[
                "dias"
            ][
                latest_received_date_iso
            ]
            .get(
                "horas",
                {},
            )
        )

        _LOGGER.warning(
            (
                "El último día recibido (%s) "
                "está incompleto: %s horas. "
                "El resumen utilizará el último "
                "día completo: %s."
            ),
            latest_received_date_iso,
            latest_received_hours,
            latest_date_iso,
        )

    latest_data = (
        complete_days[
            latest_date_iso
        ]
    )

    summary = build_day_summary(
        latest_date_iso,
        latest_data[
            "horas"
        ],
    )

    reference_date = (
        date.fromisoformat(
            latest_date_iso
        )
    )
    
    log_history_integrity(
        history,
        reference_date,
    )

    values_7d = get_history_window(
        history,
        reference_date,
        7,
    )

    values_30d = get_history_window(
        history,
        reference_date,
        30,
    )

    media_7d = average(
        values_7d
    )

    media_30d = average(
        values_30d
    )

    consumo_total = (
        summary[
            "consumo_total_l"
        ]
    )

    summary.update(
        {
            "estado": "ok",

            "ultima_actualizacion": (
                datetime
                .now()
                .astimezone()
                .isoformat()
            ),

            "contrato": (
                parsed_data
                .get(
                    "contrato"
                )
            ),

            "contador": (
                parsed_data
                .get(
                    "contador"
                )
            ),

            "media_7d_l": media_7d,

            "media_30d_l": media_30d,

            "maximo_30d_l": (
                round(
                    max(
                        values_30d
                    ),
                    2,
                )
                if values_30d
                else None
            ),

            "minimo_30d_l": (
                round(
                    min(
                        values_30d
                    ),
                    2,
                )
                if values_30d
                else None
            ),

            "variacion_7d_pct": (
                variation_percent(
                    consumo_total,
                    media_7d,
                )
            ),

            "variacion_30d_pct": (
                variation_percent(
                    consumo_total,
                    media_30d,
                )
            ),

            "dias_media_7d": len(
                values_7d
            ),

            "dias_media_30d": len(
                values_30d
            ),

            "dias_historico": len(
                history[
                    "dias"
                ]
            ),
        }
    )

    write_json_atomic(
        RESUMEN_FILE,
        summary,
    )

    _LOGGER.info(
        (
            "Resumen generado: "
            "%s - %.2f L - %s horas recibidas."
        ),
        summary[
            "fecha"
        ],
        summary[
            "consumo_total_l"
        ],
        summary[
            "horas_recibidas"
        ],
    )

    _LOGGER.info(
        "JSON resumen guardado en: %s",
        RESUMEN_FILE,
    )

    _LOGGER.info(
        "JSON histórico guardado en: %s",
        HISTORICO_FILE,
    )

    return summary

# Determinar Intervalo
def get_history_query_range() -> tuple[date, date]:

    end_date = (
        date.today()
        - timedelta(days=1)
    )

    history = load_history()

    history_days = (
        history
        .get(
            "dias",
            {},
        )
    )

    existing_dates = set()

    for fecha_iso in history_days.keys():

        try:

            existing_dates.add(
                date.fromisoformat(
                    fecha_iso
                )
            )

        except ValueError:
            continue

    _LOGGER.info(
        "Histórico existente: %s días.",
        len(existing_dates),
    )

    _LOGGER.info(
        "Último día completo consultable: %s.",
        end_date,
    )

    start_window = (
        end_date
        - timedelta(
            days=HISTORY_BOOTSTRAP_DAYS - 1
        )
    )

    expected_dates = [
        start_window
        + timedelta(days=i)
        for i in range(
            HISTORY_BOOTSTRAP_DAYS
        )
    ]

    missing_dates = [
        current_date
        for current_date
        in expected_dates
        if current_date
        not in existing_dates
    ]

    _LOGGER.info(
        (
            "Analizando histórico de los últimos %s días: "
            "%s esperados, %s existentes, %s ausentes."
        ),
        HISTORY_BOOTSTRAP_DAYS,
        len(expected_dates),
        sum(
            1
            for current_date in expected_dates
            if current_date in existing_dates
        ),
        len(missing_dates),
    )

    if missing_dates:

        first_missing_date = min(
            missing_dates
        )

        refresh_start_date = (
            end_date
            - timedelta(
                days=HISTORY_REFRESH_DAYS - 1
            )
        )

        # Aunque solo falte ayer, solicitamos como mínimo
        # la ventana de refresco. De esta forma siempre
        # disponemos también de días completos anteriores.
        start_date = min(
            first_missing_date,
            refresh_start_date,
        )

        _LOGGER.info(
            "Modo histórico: RECUPERACIÓN."
        )

        _LOGGER.info(
            (
                "Primer hueco: %s. "
                "Último hueco: %s."
            ),
            min(missing_dates),
            max(missing_dates),
        )

        _LOGGER.info(
            (
                "Se solicitará como mínimo una ventana "
                "de %s días para mantener datos completos."
            ),
            HISTORY_REFRESH_DAYS,
        )

        if len(missing_dates) <= 10:

            _LOGGER.info(
                "Días ausentes: %s",
                ", ".join(
                    current_date.isoformat()
                    for current_date
                    in missing_dates
                ),
            )

    else:

        start_date = (
            end_date
            - timedelta(
                days=HISTORY_REFRESH_DAYS - 1
            )
        )

        _LOGGER.info(
            "Modo histórico: REFRESCO."
        )

        _LOGGER.info(
            (
                "No hay huecos en los últimos %s días. "
                "Se refrescarán los últimos %s días."
            ),
            HISTORY_BOOTSTRAP_DAYS,
            HISTORY_REFRESH_DAYS,
        )

    _LOGGER.info(
        (
            "Intervalo que se solicitará a Canal: "
            "%s -> %s."
        ),
        start_date,
        end_date,
    )

    return (
        start_date,
        end_date,
    )

#introduzca esas fechas en el formulario de Canal
def set_date_range(
    page,
    context,
    start_date: date,
    end_date: date,
) -> None:

    fields = {
        "fechaDesde": start_date.isoformat(),
        "fechaHasta": end_date.isoformat(),
    }

    for field_name, value in (
        fields.items()
    ):

        selectors = [
            f'input[name="{field_name}"]',
            f'input[name$="{field_name}"]',
            f'input[id="{field_name}"]',
            f'input[id$="{field_name}"]',
        ]

        field = None

        for selector in selectors:

            candidate = page.locator(
                selector
            )

            if candidate.count() > 0:

                field = candidate.first

                _LOGGER.info(
                    (
                        "Campo %s encontrado "
                        "con selector: %s"
                    ),
                    field_name,
                    selector,
                )

                break

        if field is None:

            fail(
                context,
                45,
                (
                    "No se encuentra el campo "
                    f"{field_name}."
                ),
            )

        try:

            field.fill(
                value
            )

        except Exception:

            field.evaluate(
                """
                (element, value) => {

                    element.removeAttribute(
                        'readonly'
                    );

                    element.value = value;

                    element.dispatchEvent(
                        new Event(
                            'input',
                            {
                                bubbles: true
                            }
                        )
                    );

                    element.dispatchEvent(
                        new Event(
                            'change',
                            {
                                bubbles: true
                            }
                        )
                    );
                }
                """,
                value,
            )

        actual_value = (
            field.input_value()
        )

        if actual_value != value:

            fail(
                context,
                46,
                (
                    f"{field_name} no quedó "
                    f"configurado correctamente. "
                    f"Esperado={value}, "
                    f"actual={actual_value}"
                ),
            )

        _LOGGER.info(
            "%s configurada correctamente: %s",
            field_name,
            actual_value,
        )

    _LOGGER.info(
        (
            "Intervalo de Telelecturas "
            "configurado correctamente: "
            "%s -> %s."
        ),
        start_date,
        end_date,
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
        # Chromium visible dentro de Xvfb.
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

            history_start_date, history_end_date = (
                get_history_query_range()
            )

            select_and_apply_hourly(
                page,
                context,
                history_start_date,
                history_end_date,
            )

            # ------------------------------------------------
            # Descargar CSV
            # ------------------------------------------------

            size = download_csv(
                page,
                context,
            )

            # ------------------------------------------------
            # Validar CSV
            # ------------------------------------------------

            content = validate_hourly_csv(
                context
            )

            # ------------------------------------------------
            # Procesar CSV
            # ------------------------------------------------

            parsed_data = parse_hourly_csv(
                context,
                content,
            )

            # ------------------------------------------------
            # Crear resumen e histórico
            # ------------------------------------------------

            summary = generate_summary_files(
                context,
                parsed_data,
            )

            # ------------------------------------------------
            # Actualizar sesión
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

            _LOGGER.info(
                (
                    "Consumo del día %s: %.2f L"
                ),
                summary[
                    "fecha"
                ],
                summary[
                    "consumo_total_l"
                ],
            )

            write_status(
                "ok",
                (
                    "Descarga y procesamiento "
                    "realizados correctamente."
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