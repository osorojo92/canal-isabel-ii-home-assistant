# Contexto del proyecto

Proyecto: add-on de Home Assistant para Canal Isabel II.

Repositorio:
https://github.com/osorojo92/canal-isabel-ii-home-assistant

Objetivo:
- Ejecutar Chromium/Playwright dentro de Home Assistant.
- Permitir login manual mediante noVNC cuando la sesión caduca.
- Resolver CAPTCHA manualmente.
- Guardar y reutilizar la sesión.
- Acceder a Telelecturas.
- Seleccionar frecuencia HORARIA.
- Descargar CSV.
- Guardarlo en /share/canal_consumo_horario.csv.
- Más adelante crear sensores y visualización en Home Assistant.

Arquitectura actual:
Home Assistant Ingress
→ nginx :8099
→ cliente noVNC personalizado vnc-ha.html
→ websockify :6080
→ x11vnc :5900
→ Xvfb :99
→ Chromium/Playwright

Modos:
- mode: login
  - Chromium visible.
  - Login manual.
  - CAPTCHA manual.
- mode: auto
  - Ejecución automática.

Ficheros principales:
- canal_isabel_playwright/config.yaml
- canal_isabel_playwright/Dockerfile
- canal_isabel_playwright/run.sh
- canal_isabel_playwright/nginx.conf
- canal_isabel_playwright/vnc-ha.html
- canal_isabel_playwright/auth_browser.py
- canal_isabel_playwright/canal_playwright.py

Cosas que YA funcionan:
- Add-on instalable desde GitHub.
- Ingress.
- noVNC.
- Chromium visible dentro del add-on.
- Login manual.
- Detección de sesión autenticada.
- Guardado de cookies.
- Descarga CSV en versiones anteriores.
- Detección de selector de periodicidad.
- Identificación del formulario POST de Telelecturas.
- Identificación del endpoint de exportación CSV.

Flujo observado en Canal:
Búsqueda:
POST /group/ovir/consumo
p_p_lifecycle=1
javax.portlet.action=/Telelectura/buscarForm
periodicidad=Horaria
fechaDesde=YYYY-MM-DD
fechaHasta=YYYY-MM-DD
contratosFiltro=...

Exportación:
p_p_lifecycle=2
p_p_resource_id=/Telelecturas/export-csv
fileFormat=CSV

Problema actual:
- La sesión manual se detecta y se guarda.
- Al arrancar posteriormente en modo auto, Canal a veces redirige a /web/ovir/login.
- Se está trabajando en persistir no solo cookies, sino storage_state completo, localStorage, IndexedDB y sessionStorage.
- No tocar nginx/noVNC salvo que sea estrictamente necesario: esa parte ya funciona.

Reglas:
- No intentar resolver ni saltar CAPTCHA automáticamente.
- El CAPTCHA se resuelve manualmente en modo login.
- No cambiar varias partes de arquitectura a la vez.
- Antes de modificar código, revisar logs y confirmar la causa.
- Cuando se modifique un fichero, devolver el fichero completo listo para reemplazar.
- Mantener compatibilidad con Home Assistant add-on.
- Usar versiones semver.