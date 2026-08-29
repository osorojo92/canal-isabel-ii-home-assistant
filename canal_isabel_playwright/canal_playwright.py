from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

CONFIG_DIR = Path("/config")
PROFILE_DIR = CONFIG_DIR / "browser_profile"
SHARE_DIR = Path("/share")
CSV_FILE = SHARE_DIR / "canal_consumo_horario.csv"
STATUS_FILE = SHARE_DIR / "canal_estado.json"
SESSION_FILE = CONFIG_DIR / "canal_session.json"

CONSUMO_URL = (
    "https://oficinavirtual.canaldeisabelsegunda.es/group/ovir/consumo"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

_LOGGER = logging.getLogger("canal")


def restore_session(context) -> bool:
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


def remove_profile_locks() -> None:
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


def select_hourly(page, context) -> None:
    _LOGGER.info("Buscando selector de periodicidad...")

    periodicity = page.locator(
        "select#selectPeriodicidad"
    )

    if periodicity.count() == 0:
        periodicity = page.locator(
            'select[id*="selectPeriodicidad"]'
        )

    if periodicity.count() == 0:
        fail(
            context,
            40,
            "No se encuentra el selector de periodicidad.",
        )

    _LOGGER.info(
        "Selector encontrado. Seleccionando frecuencia HORARIA..."
    )

    selected = False

    try:
        periodicity.first.select_option(
            label="Horaria"
        )
        selected = True

    except Exception:
        pass

    if not selected:
        try:
            periodicity.first.select_option(
                value="Horaria"
            )
            selected = True

        except Exception:
            pass

    if not selected:
        options = periodicity.first.locator("option")

        for index in range(options.count()):
            option = options.nth(index)

            text = (
                option
                .inner_text()
                .strip()
                .lower()
            )

            if "horaria" in text:
                value = option.get_attribute("value")

                periodicity.first.select_option(
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

    _LOGGER.info(
        "Frecuencia HORARIA seleccionada."
    )

    page.wait_for_timeout(5000)


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


def validate_hourly_csv(
    context,
) -> None:
    try:
        content = CSV_FILE.read_text(
            encoding="utf-8",
            errors="ignore",
        ).upper()

    except Exception as err:
        fail(
            context,
            63,
            f"No se puede leer el CSV descargado: {err}",
        )

    if "HORARIA" not in content:
        fail(
            context,
            64,
            "El CSV descargado no contiene frecuencia HORARIA.",
        )

    _LOGGER.info(
        "Validación CSV correcta: contiene frecuencia HORARIA."
    )


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

        restore_session(context)

        try:
            page = (
                context.pages[0]
                if context.pages
                else context.new_page()
            )

            # Logging de red para diagnóstico
            page.on(
                "request",
                log_request,
            )

            page.on(
                "response",
                log_response,
            )

            try:
                page.goto(
                    CONSUMO_URL,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

                page.wait_for_timeout(4000)

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

            if not session_is_valid(page):
                fail(
                    context,
                    30,
                    (
                        "La sesión ha caducado o requiere "
                        "autenticación manual. Cambia mode a login."
                    ),
                    auth=True,
                )

            _LOGGER.info(
                "Sesión autenticada."
            )

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

                    page.wait_for_timeout(
                        1000
                    )

            except Exception as err:
                _LOGGER.warning(
                    "No se pudieron abrir los filtros: %s",
                    err,
                )

            select_hourly(
                page,
                context,
            )

            if not session_is_valid(page):
                fail(
                    context,
                    31,
                    (
                        "La sesión se perdió al cambiar "
                        "la periodicidad."
                    ),
                    auth=True,
                )

            _LOGGER.info(
                "Buscando enlace de exportación CSV..."
            )

            csv_links = page.locator(
                'a[href*="export-csv"]'
            )

            if csv_links.count() == 0:
                fail(
                    context,
                    50,
                    (
                        "No se encuentra el enlace "
                        "de exportación CSV."
                    ),
                )

            _LOGGER.info(
                "Enlaces CSV encontrados: %s",
                csv_links.count(),
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
                    csv_links.first.click()

                download = download_info.value

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
                        "La descarga terminó "
                        "pero el CSV no existe."
                    ),
                )

            size = CSV_FILE.stat().st_size

            if size == 0:
                fail(
                    context,
                    62,
                    "El CSV descargado está vacío.",
                )

            validate_hourly_csv(
                context
            )

            _LOGGER.info(
                "CSV descargado correctamente: %s (%s bytes)",
                CSV_FILE,
                size,
            )

            write_status(
                "ok",
                "Descarga realizada correctamente.",
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