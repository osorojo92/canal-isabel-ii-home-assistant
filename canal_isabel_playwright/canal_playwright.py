from pathlib import Path
from datetime import datetime
import json
import sys

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


# ============================================================
# CONFIGURACIÓN
# ============================================================

# /config corresponde al addon_config persistente
CONFIG_DIR = Path("/config")

# /share es accesible desde Home Assistant
SHARE_DIR = Path("/share")

STATE_FILE = CONFIG_DIR / "canal_state.json"

CSV_FILE = SHARE_DIR / "canal_consumo_horario.csv"
STATUS_FILE = SHARE_DIR / "canal_estado.json"

BASE_URL = "https://oficinavirtual.canaldeisabelsegunda.es"
CONSUMO_URL = BASE_URL + "/group/ovir/consumo"


# ============================================================
# ESTADO
# ============================================================

def guardar_estado(
    estado: str,
    mensaje: str,
    codigo: int = 0,
    csv_bytes: int | None = None,
):
    """Guardar estado para que Home Assistant pueda consultarlo."""

    datos = {
        "estado": estado,
        "mensaje": mensaje,
        "codigo": codigo,
        "ultima_ejecucion": datetime.now().astimezone().isoformat(),
    }

    if csv_bytes is not None:
        datos["csv_bytes"] = csv_bytes

    try:
        STATUS_FILE.write_text(
            json.dumps(
                datos,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    except Exception as err:
        print(f"AVISO guardando estado: {err}")


def terminar(
    browser,
    codigo: int,
    mensaje: str,
):
    """Cerrar Chromium y terminar."""

    print()
    print(mensaje)

    guardar_estado(
        estado="error",
        mensaje=mensaje,
        codigo=codigo,
    )

    try:
        browser.close()
    except Exception:
        pass

    sys.exit(codigo)


# ============================================================
# COMPROBACIÓN DE SESIÓN
# ============================================================

def sesion_valida(page) -> bool:
    """Comprobar si seguimos en la zona autenticada."""

    url = page.url.lower()

    if "/group/ovir/" in url:
        return True

    try:
        if page.locator(
            'input[type="password"]'
        ).count() > 0:
            return False
    except Exception:
        pass

    return False


# ============================================================
# PROGRAMA
# ============================================================

def main():

    print()
    print("==============================================")
    print(" CANAL DE ISABEL II - PLAYWRIGHT")
    print("==============================================")
    print()

    SHARE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    CONFIG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Necesitamos una sesión exportada previamente
    # --------------------------------------------------------

    if not STATE_FILE.exists():

        mensaje = (
            "No existe /config/canal_state.json. "
            "Es necesario copiar una sesión válida."
        )

        print(mensaje)

        guardar_estado(
            estado="reautenticacion_requerida",
            mensaje=mensaje,
            codigo=10,
        )

        sys.exit(10)

    with sync_playwright() as p:

        # ----------------------------------------------------
        # Chromium headless
        # ----------------------------------------------------

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = browser.new_context(
            storage_state=str(STATE_FILE),
            accept_downloads=True,
        )

        page = context.new_page()

        # ----------------------------------------------------
        # Abrir Telelecturas
        # ----------------------------------------------------

        print("Abriendo Telelecturas...")

        try:

            page.goto(
                CONSUMO_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            page.wait_for_timeout(4000)

        except PlaywrightTimeoutError:

            terminar(
                browser,
                20,
                "Timeout abriendo la página de consumo.",
            )

        print(f"URL: {page.url}")

        # ----------------------------------------------------
        # Sesión
        # ----------------------------------------------------

        if not sesion_valida(page):

            mensaje = (
                "La sesión del Canal ha caducado "
                "o requiere autenticación manual."
            )

            print(mensaje)

            guardar_estado(
                estado="reautenticacion_requerida",
                mensaje=mensaje,
                codigo=30,
            )

            browser.close()

            sys.exit(30)

        print("✅ Sesión autenticada")

        # ----------------------------------------------------
        # Mostrar filtros
        # ----------------------------------------------------

        print()
        print("Buscando filtros...")

        try:

            mostrar_filtros = page.get_by_text(
                "Mostrar filtros",
                exact=False,
            )

            if (
                mostrar_filtros.count() > 0
                and mostrar_filtros.first.is_visible()
            ):

                print("Abriendo filtros...")

                mostrar_filtros.first.click()

                page.wait_for_timeout(1000)

        except Exception as err:
            print(f"Aviso abriendo filtros: {err}")

        # ----------------------------------------------------
        # Selector periodicidad
        # ----------------------------------------------------

        print()
        print("Buscando selector de periodicidad...")

        periodicidad = page.locator(
            "select#selectPeriodicidad"
        )

        if periodicidad.count() == 0:

            periodicidad = page.locator(
                'select[id*="selectPeriodicidad"]'
            )

        if periodicidad.count() == 0:

            terminar(
                browser,
                40,
                "No se encuentra el selector de periodicidad.",
            )

        print("✅ Selector encontrado")

        # ----------------------------------------------------
        # Horaria
        # ----------------------------------------------------

        print("Seleccionando frecuencia HORARIA...")

        seleccionado = False

        try:

            periodicidad.first.select_option(
                label="Horaria"
            )

            seleccionado = True

        except Exception:
            pass

        if not seleccionado:

            try:

                periodicidad.first.select_option(
                    value="Horaria"
                )

                seleccionado = True

            except Exception:
                pass

        if not seleccionado:

            options = periodicidad.first.locator(
                "option"
            )

            for i in range(options.count()):

                option = options.nth(i)

                texto = (
                    option.inner_text()
                    .strip()
                    .lower()
                )

                if "horaria" in texto:

                    value = option.get_attribute(
                        "value"
                    )

                    periodicidad.first.select_option(
                        value=value
                    )

                    seleccionado = True

                    break

        if not seleccionado:

            terminar(
                browser,
                41,
                "No se encuentra la opción Horaria.",
            )

        print("✅ Frecuencia HORARIA seleccionada")

        page.wait_for_timeout(5000)

        # ----------------------------------------------------
        # Volvemos a comprobar sesión
        # ----------------------------------------------------

        if not sesion_valida(page):

            mensaje = (
                "La sesión se perdió al cambiar "
                "la periodicidad."
            )

            guardar_estado(
                estado="reautenticacion_requerida",
                mensaje=mensaje,
                codigo=31,
            )

            browser.close()

            sys.exit(31)

        # ----------------------------------------------------
        # CSV
        # ----------------------------------------------------

        print()
        print("Buscando exportación CSV...")

        csv_links = page.locator(
            'a[href*="export-csv"]'
        )

        if csv_links.count() == 0:

            terminar(
                browser,
                50,
                "No se encuentra el enlace CSV.",
            )

        print(
            f"✅ Enlaces CSV encontrados: "
            f"{csv_links.count()}"
        )

        csv_link = csv_links.first

        # ----------------------------------------------------
        # Borrar CSV anterior
        # ----------------------------------------------------

        if CSV_FILE.exists():

            try:
                CSV_FILE.unlink()

            except Exception as err:

                terminar(
                    browser,
                    51,
                    f"No se puede borrar CSV anterior: {err}",
                )

        # ----------------------------------------------------
        # Descargar
        # ----------------------------------------------------

        print()
        print("Descargando CSV horario...")

        try:

            with page.expect_download(
                timeout=60000
            ) as download_info:

                csv_link.click()

            download = download_info.value

            download.save_as(
                str(CSV_FILE)
            )

        except Exception as err:

            terminar(
                browser,
                60,
                f"Error descargando CSV: {err}",
            )

        # ----------------------------------------------------
        # Validación
        # ----------------------------------------------------

        if not CSV_FILE.exists():

            terminar(
                browser,
                61,
                "La descarga terminó pero el CSV no existe.",
            )

        tamano = CSV_FILE.stat().st_size

        if tamano == 0:

            terminar(
                browser,
                62,
                "El CSV descargado está vacío.",
            )

        print("✅ CSV descargado correctamente")
        print(CSV_FILE)
        print(f"Tamaño: {tamano} bytes")

        # ----------------------------------------------------
        # Renovar storage_state
        # ----------------------------------------------------

        try:

            context.storage_state(
                path=str(STATE_FILE)
            )

            print(
                "✅ Estado de sesión actualizado"
            )

        except Exception as err:

            print(
                "AVISO: no se pudo actualizar "
                f"canal_state.json: {err}"
            )

        # ----------------------------------------------------
        # Estado OK
        # ----------------------------------------------------

        guardar_estado(
            estado="ok",
            mensaje="Descarga realizada correctamente",
            codigo=0,
            csv_bytes=tamano,
        )

        print()
        print("==============================================")
        print(" PROCESO COMPLETADO")
        print("==============================================")
        print(
            datetime.now().strftime(
                "%d/%m/%Y %H:%M:%S"
            )
        )
        print("Resultado: OK")

        context.close()
        browser.close()

        sys.exit(0)


if __name__ == "__main__":
    main()