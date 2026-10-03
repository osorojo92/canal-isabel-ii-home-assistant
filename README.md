# Canal Isabel II Home Assistant

Add-on para Home Assistant que descarga automáticamente las telelecturas del Canal de Isabel II usando Chromium y Playwright.

## Características

- Chromium real mediante Playwright.
- Autenticación manual integrada mediante noVNC + Home Assistant Ingress.
- El CAPTCHA, cuando aparece, se resuelve manualmente por el usuario.
- Perfil de navegador persistente dentro del `addon_config`.
- Ejecución automática en modo headless.
- Selección automática de consumo horario.
- CSV en `/share/canal_consumo_horario.csv`.
- Estado en `/share/canal_estado.json`.
- Evento genérico de Home Assistant cuando es necesario volver a autenticarse.
- El aviso de autenticación se emite una sola vez por incidencia, aunque el proceso se ejecute periódicamente.

## Instalación

Añade este repositorio a la tienda de aplicaciones de Home Assistant:

`https://github.com/osorojo92/canal-isabel-ii-home-assistant`

Instala **Canal Isabel II Playwright**.

## Primera autenticación

1. Configura `mode: login`.
2. Inicia o reinicia el add-on.
3. Pulsa **Abrir interfaz web**.
4. En noVNC, pulsa **Connect** si fuese necesario.
5. Inicia sesión normalmente en la Oficina Virtual.
6. Si aparece CAPTCHA, resuélvelo manualmente.
7. Cuando estés dentro de la zona privada, cambia `mode` a `auto`.
8. Reinicia el add-on.

No es necesario copiar `JSESSIONID` ni `canal_state.json`.

## Funcionamiento automático

En modo `auto` el add-on abre Telelecturas con Chromium headless, selecciona frecuencia horaria, descarga el CSV y espera el intervalo configurado.

Si la sesión caduca, no intenta resolver ni eludir el CAPTCHA automáticamente. El add-on publica el evento `canal_isabel_ii_event` con `type: auth_required` una sola vez por incidencia, para que cada usuario pueda gestionarlo mediante una automatización propia. Cambia a `mode: login`, autentícate manualmente y vuelve después a `mode: auto`.

## Seguridad

El perfil del navegador contiene una sesión autenticada. Se guarda en el directorio privado `addon_config` del add-on y no debe publicarse ni subirse a GitHub.

## Aviso

Proyecto no oficial y no afiliado al Canal de Isabel II.
