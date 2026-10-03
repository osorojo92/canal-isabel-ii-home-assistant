from __future__ import annotations

import json
import logging
from pathlib import Path


# ============================================================
# RUTAS
# ============================================================

OPTIONS_FILE = Path("/data/options.json")
CONFIG_DIR = Path("/config")
AUTO_RELOGIN_ATTEMPT_MARKER = (
    CONFIG_DIR / "canal_auto_relogin_attempted.json"
)


# ============================================================
# LOGGING
# ============================================================

_LOGGER = logging.getLogger("canal-auto-login")


# ============================================================
# CONFIGURACIÓN
# ============================================================

def load_auto_relogin_options() -> dict:
    """
    Lee exclusivamente las opciones necesarias para el relogin.

    La contraseña nunca se escribe en logs ni en ficheros auxiliares.
    """

    defaults = {
        "auto_relogin": False,
        "username": "",
        "password": "",
        "user_type": "particular",
    }

    try:

        data = json.loads(
            OPTIONS_FILE.read_text(
                encoding="utf-8"
            )
        )

    except Exception as err:

        _LOGGER.warning(
            "No se pudieron leer las opciones del add-on: %s",
            err,
        )

        return defaults

    return {
        "auto_relogin": bool(
            data.get(
                "auto_relogin",
                defaults["auto_relogin"],
            )
        ),
        "username": str(
            data.get(
                "username",
                defaults["username"],
            )
            or ""
        ),
        "password": str(
            data.get(
                "password",
                defaults["password"],
            )
            or ""
        ),
        "user_type": str(
            data.get(
                "user_type",
                defaults["user_type"],
            )
            or defaults["user_type"]
        ),
    }


# ============================================================
# MARCA: UN INTENTO POR INCIDENCIA
# ============================================================

def auto_relogin_already_attempted() -> bool:

    return AUTO_RELOGIN_ATTEMPT_MARKER.exists()


def mark_auto_relogin_attempt(
    trigger_reason: str,
) -> None:

    CONFIG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    data = {
        "trigger_reason": trigger_reason,
        "attempted": True,
    }

    temp_file = AUTO_RELOGIN_ATTEMPT_MARKER.with_suffix(
        ".json.tmp"
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
        AUTO_RELOGIN_ATTEMPT_MARKER
    )


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
# UTILIDADES DE PÁGINA
# ============================================================

def _first_visible(
    page,
    selectors: list[str],
):

    for selector in selectors:

        try:

            locator = page.locator(
                selector
            )

            for index in range(
                locator.count()
            ):

                candidate = locator.nth(
                    index
                )

                if candidate.is_visible():
                    return candidate

        except Exception:
            continue

    return None


def captcha_is_visible(
    page,
) -> bool:
    """
    Detecta CAPTCHA visible. No intenta resolverlo ni interactuar con él.
    """

    selectors = [
        'iframe[src*="recaptcha"]',
        'iframe[title*="reCAPTCHA"]',
        '[id*="captcha"]',
        '[class*="captcha"]',
    ]

    for selector in selectors:

        try:

            locator = page.locator(
                selector
            )

            for index in range(
                locator.count()
            ):

                if locator.nth(
                    index
                ).is_visible():

                    return True

        except Exception:
            continue

    try:

        body_text = (
            page
            .locator("body")
            .inner_text(
                timeout=3000
            )
            .lower()
        )

        captcha_texts = (
            "captcha",
            "no soy un robot",
            "i'm not a robot",
        )

        return any(
            text in body_text
            for text in captcha_texts
        )

    except Exception:

        return False


def _session_is_valid(
    page,
) -> bool:

    try:

        url = (
            page.url
            .lower()
        )

        if (
            "/group/ovir/" in url
            and "/login" not in url
        ):
            return True

    except Exception:
        pass

    try:

        real_url = (
            page
            .evaluate(
                "() => window.location.href"
            )
            .lower()
        )

        if (
            "/group/ovir/" in real_url
            and "/login" not in real_url
        ):
            return True

    except Exception:
        pass

    return False


def _select_user_type(
    page,
    user_type: str,
) -> bool:
    """
    Intenta seleccionar el tipo de usuario por el texto visible.

    Se recorre cualquier <select> visible para evitar depender de IDs
    internos de la web. Si no hay select, se prueba con una etiqueta
    o control que contenga el texto configurado.
    """

    wanted = (
        user_type
        .strip()
        .lower()
    )

    if not wanted:
        return True

    try:

        selects = page.locator(
            "select"
        )

        for index in range(
            selects.count()
        ):

            select = selects.nth(
                index
            )

            if not select.is_visible():
                continue

            options = select.locator(
                "option"
            )

            for option_index in range(
                options.count()
            ):

                option = options.nth(
                    option_index
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

                if wanted in text:

                    value = option.get_attribute(
                        "value"
                    )

                    if value is not None:

                        select.select_option(
                            value=value
                        )

                    else:

                        select.select_option(
                            label=option.inner_text()
                        )

                    _LOGGER.info(
                        "Tipo de usuario seleccionado."
                    )

                    return True

    except Exception as err:

        _LOGGER.debug(
            "No se pudo seleccionar tipo mediante <select>: %s",
            err,
        )

    try:

        labels = page.locator(
            "label"
        )

        for index in range(
            labels.count()
        ):

            label = labels.nth(
                index
            )

            if not label.is_visible():
                continue

            text = (
                label
                .inner_text()
                .strip()
                .lower()
            )

            if wanted in text:

                label.click()

                _LOGGER.info(
                    "Tipo de usuario seleccionado."
                )

                return True

    except Exception:
        pass

    return False


def _find_submit(
    page,
):

    submit = _first_visible(
        page,
        [
            'button[type="submit"]',
            'input[type="submit"]',
        ],
    )

    if submit is not None:
        return submit

    for text in (
        "Acceder",
        "Entrar",
        "Iniciar sesión",
        "Iniciar sesion",
    ):

        try:

            candidate = page.get_by_role(
                "button",
                name=text,
                exact=False,
            )

            for index in range(
                candidate.count()
            ):

                button = candidate.nth(
                    index
                )

                if button.is_visible():
                    return button

        except Exception:
            continue

    return None


# ============================================================
# LOGIN AUTOMÁTICO
# ============================================================

def attempt_auto_relogin(
    page,
    trigger_reason: str,
) -> dict:
    """
    Realiza como máximo un intento automático por incidencia.

    Retorna un diccionario con:
      success: bool
      reason: código estable para eventos
      message: texto apto para diagnóstico, sin credenciales
    """

    options = load_auto_relogin_options()

    if not options["auto_relogin"]:

        return {
            "success": False,
            "reason": trigger_reason,
            "message": (
                "La recuperación automática de sesión "
                "está desactivada."
            ),
        }

    if auto_relogin_already_attempted():

        return {
            "success": False,
            "reason": "auto_relogin_already_attempted",
            "message": (
                "Ya se realizó el intento automático "
                "para esta incidencia."
            ),
        }

    username = options["username"]
    password = options["password"]
    user_type = options["user_type"]

    if (
        not username.strip()
        or not password
    ):

        return {
            "success": False,
            "reason": "credentials_missing",
            "message": (
                "Faltan usuario o contraseña para "
                "la recuperación automática."
            ),
        }

    # La marca se crea ANTES de interactuar con la web para que un
    # error o cierre inesperado tampoco provoque intentos repetidos.
    try:

        mark_auto_relogin_attempt(
            trigger_reason
        )

    except Exception as err:

        _LOGGER.warning(
            "No se pudo guardar la marca de intento: %s",
            err,
        )

        return {
            "success": False,
            "reason": "auto_relogin_marker_error",
            "message": (
                "No se pudo garantizar el límite "
                "de un intento automático por incidencia."
            ),
        }

    _LOGGER.info(
        (
            "Sesión no válida. Se realizará un único "
            "intento de autenticación automática."
        )
    )

    if captcha_is_visible(
        page
    ):

        return {
            "success": False,
            "reason": "captcha_required",
            "message": (
                "Canal solicita CAPTCHA. "
                "Es necesaria autenticación manual."
            ),
        }

    username_field = _first_visible(
        page,
        [
            'input[autocomplete="username"]',
            'input[name*="usuario"]',
            'input[id*="usuario"]',
            'input[name*="user"]',
            'input[id*="user"]',
            'input[name*="nif"]',
            'input[id*="nif"]',
            'input[name*="document"]',
            'input[id*="document"]',
            'input[type="text"]',
        ],
    )

    password_field = _first_visible(
        page,
        [
            'input[type="password"]',
        ],
    )

    if (
        username_field is None
        or password_field is None
    ):

        return {
            "success": False,
            "reason": "login_form_not_found",
            "message": (
                "No se ha podido identificar el formulario "
                "de acceso de Canal."
            ),
        }

    user_type_selected = _select_user_type(
        page,
        user_type,
    )

    if (
        user_type.strip()
        and not user_type_selected
    ):

        _LOGGER.warning(
            (
                "No se encontró un selector visible para "
                "el tipo de usuario configurado. "
                "Se continuará con el valor actual de la web."
            )
        )

    try:

        username_field.fill(
            username
        )

        password_field.fill(
            password
        )

    except Exception as err:

        _LOGGER.warning(
            "No se pudieron rellenar los campos de acceso: %s",
            err,
        )

        return {
            "success": False,
            "reason": "login_form_fill_failed",
            "message": (
                "No se pudieron rellenar los campos "
                "del formulario de acceso."
            ),
        }

    if captcha_is_visible(
        page
    ):

        return {
            "success": False,
            "reason": "captcha_required",
            "message": (
                "Canal solicita CAPTCHA. "
                "Es necesaria autenticación manual."
            ),
        }

    submit = _find_submit(
        page
    )

    if submit is None:

        return {
            "success": False,
            "reason": "login_submit_not_found",
            "message": (
                "No se ha podido identificar el botón "
                "de acceso de Canal."
            ),
        }

    try:

        submit.click()

    except Exception as err:

        _LOGGER.warning(
            "No se pudo enviar el formulario de acceso: %s",
            err,
        )

        return {
            "success": False,
            "reason": "login_submit_failed",
            "message": (
                "No se pudo enviar el formulario "
                "de autenticación."
            ),
        }

    # Canal puede tardar varios segundos en completar la navegación.
    for _ in range(
        20
    ):

        page.wait_for_timeout(
            1000
        )

        if _session_is_valid(
            page
        ):

            return {
                "success": True,
                "reason": "automatic_login",
                "message": (
                    "La sesión se ha recuperado "
                    "automáticamente."
                ),
            }

        if captcha_is_visible(
            page
        ):

            return {
                "success": False,
                "reason": "captcha_required",
                "message": (
                    "Canal solicita CAPTCHA. "
                    "Es necesaria autenticación manual."
                ),
            }

    return {
        "success": False,
        "reason": "login_failed",
        "message": (
            "El intento automático de autenticación "
            "no consiguió recuperar la sesión."
        ),
    }
