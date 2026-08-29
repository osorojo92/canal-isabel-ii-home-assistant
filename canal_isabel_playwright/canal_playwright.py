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

    for fecha_iso, data in (
        parsed_data[
            "dias"
        ].items()
    ):

        summary = build_day_summary(
            fecha_iso,
            data[
                "horas"
            ],
        )

        days[
            fecha_iso
        ] = summary[
            "consumo_total_l"
        ]

    # Orden cronológico para que el JSON sea legible.
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

    _LOGGER.info(
        (
            "Histórico diario actualizado: "
            "%s días almacenados."
        ),
        len(
            history[
                "dias"
            ]
        ),
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

def generate_summary_files(
    context,
    parsed_data: dict,
) -> dict:

    history = update_history(
        parsed_data
    )

    # El CSV normal contiene un único día.
    # Si Canal devuelve varios en el futuro,
    # usamos el más reciente para canal_resumen.json.
    latest_date_iso = max(
        parsed_data[
            "dias"
        ].keys()
    )

    latest_data = (
        parsed_data[
            "dias"
        ][
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

            select_and_apply_hourly(
                page,
                context,
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