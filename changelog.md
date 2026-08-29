## [1.0.15] - 2026-08-29

### Fixed

- Corregida la detección de sesión autenticada en modo `login`.
- La autenticación ya no depende únicamente de `page.url`.
- Añadida comprobación de la URL real mediante `window.location.href`.
- Añadida detección alternativa mediante elementos del DOM de la zona privada.
- El add-on revisa ahora todas las páginas abiertas del contexto de Chromium.
- Mejorado el diagnóstico del estado de cada página para detectar discrepancias entre Playwright y la navegación visible en noVNC.
- La sesión solo se guarda cuando se confirma de forma fiable que el usuario está dentro de la zona autenticada.
