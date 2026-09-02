# Changelog

## [1.0.18] - 2026-09-02

### Fixed

- Sustituida la descarga de noVNC mediante `git clone` por descarga directa del archivo oficial de la versión 1.6.0.
- Evitado el fallo de construcción del add-on cuando Git no puede acceder de forma anónima a GitHub durante el Docker build.

## [1.0.17] - 2026-09-02

### Added

- Añadida recuperación automática de huecos del histórico diario.
- El add-on solicita datos de días anteriores mediante los filtros
  `fechaDesde` y `fechaHasta` de Telelecturas.
- Añadida carga inicial de hasta 30 días para completar las métricas
  históricas.
- Cuando el histórico está completo, se refrescan los últimos 7 días
  para recoger posibles correcciones posteriores de Canal.
- El día actual queda excluido del histórico hasta que haya finalizado.

### Changed

- La descarga CSV puede contener ahora varios días de telelecturas horarias.
- `canal_historico_diario.json` se autorrepara cuando detecta días ausentes.

## [1.0.16] - 2026-08-29

### Added

- Añadido procesamiento automático del CSV horario descargado.
- Añadido `/share/canal_resumen.json` con métricas preparadas para Home Assistant.
- Añadido `/share/canal_historico_diario.json` para conservar el histórico diario de consumo.
- Añadido cálculo de consumo total diario.
- Añadido cálculo de consumo medio horario.
- Añadido máximo horario y hora de máximo consumo.
- Añadido número de horas recibidas y horas con consumo.
- Añadido desglose de consumo por hora.
- Añadido desglose por franjas: nocturno, mañana, tarde y noche.
- Añadidas medias móviles de 7 y 30 días.
- Añadidos máximo y mínimo diarios de los últimos 30 días.
- Añadidas variaciones porcentuales respecto a las medias de 7 y 30 días.
- Añadido contador de días disponibles en el histórico.
- Añadida escritura atómica de los ficheros JSON para reducir el riesgo de corrupción.

### Changed

- El proceso automático no finaliza al descargar el CSV: ahora también valida, procesa y publica los datos preparados para Home Assistant.

## [1.0.15] - 2026-08-29

### Fixed

- Corregida la detección de sesión autenticada en modo `login`.
- La autenticación ya no depende únicamente de `page.url`.
- Añadida comprobación de la URL real mediante `window.location.href`.
- Añadida detección alternativa mediante elementos del DOM de la zona privada.
- El add-on revisa ahora todas las páginas abiertas del contexto de Chromium.
- Mejorado el diagnóstico del estado de cada página para detectar discrepancias entre Playwright y la navegación visible en noVNC.
- La sesión solo se guarda cuando se confirma de forma fiable que el usuario está dentro de la zona autenticada.

## [1.0.13] - 2026-08-29

### Fixed
- Corregido el cambio de periodicidad para que no se limite a modificar visualmente el selector de frecuencia.
- El add-on envía ahora realmente el formulario de Telelecturas tras seleccionar `Horaria`.
- Reproducido el flujo observado en la Oficina Virtual mediante la acción `/Telelectura/buscarForm`.
- Se espera a que Canal regenere la consulta antes de localizar el enlace de exportación CSV.
- Mejorada la detección del enlace de descarga `export-csv`.
- Añadida validación obligatoria del CSV descargado para confirmar que contiene datos de frecuencia `HORARIA`.
- Añadida lectura tolerante a distintas codificaciones del CSV.
- Mejorados los mensajes de diagnóstico del flujo de consulta y descarga.

## [1.0.12] - 2026-08-29

### Added
- Añadido registro de peticiones y respuestas de red relacionadas con consumo, periodicidad, telelectura y exportación.
- Añadido registro del cuerpo de peticiones POST para facilitar el diagnóstico del cambio de frecuencia.
- Añadida validación del CSV descargado para comprobar que contiene frecuencia `HORARIA`.

### Changed
- El proceso ya no considera correcta una descarga si el CSV no corresponde realmente a frecuencia horaria.

### Fixed
- Evitado que el add-on marque como correcta una descarga diaria cuando se esperaba consumo horario.

## [1.0.11] - 2026-08-29

### Fixed
- Corregida la detección de autenticación manual cuando el flujo de login utiliza una página o pestaña diferente de Chromium.
- El modo `login` comprueba ahora todas las páginas abiertas del contexto persistente de Playwright.
- La sesión se guarda inmediatamente cuando cualquiera de las páginas alcanza la zona privada de la Oficina Virtual.
- Añadido registro de diagnóstico de las URLs abiertas en Chromium para facilitar la detección de cambios en el flujo de autenticación.

## [1.0.10] - 2026-08-29

### Fixed
- Corregida la persistencia de la sesión autenticada entre los modos `login` y `auto`.
- La sesión de Playwright se guarda explícitamente mediante `storage_state` en `/config/canal_session.json`.
- Las cookies de autenticación se guardan inmediatamente al detectar un inicio de sesión correcto, sin depender del cierre limpio de Chromium.
- El modo `auto` restaura las cookies almacenadas antes de acceder a Telelecturas.
- Se mantiene el perfil persistente de Chromium como mecanismo adicional de persistencia.
- Añadido registro de diagnóstico para indicar el número de cookies guardadas y restauradas.

## [1.0.9] - 2026-08-29

### Corregido
- Configurado `vnc-ha.html` directamente como punto de entrada de Home Assistant Ingress.
- Evitada la carga accidental de la interfaz estándar `vnc.html` de noVNC.
- El cliente VNC personalizado pasa a ser la interfaz utilizada directamente por el add-on.
- Añadido control explícito de caché para evitar reutilizar versiones anteriores de la interfaz.

### Técnico
- `ingress_entry` cambia de `/vnc.html` a `/vnc-ha.html`.
- La URL WebSocket se construye exclusivamente mediante el cliente personalizado basado en `RFB`.

## [1.0.8] - 2026-08-29

### Corregido
- Corregida la sintaxis de `nginx.conf`.
- Sustituidos comentarios no válidos de estilo `/* ... */` por comentarios compatibles con nginx.
- Restaurado el arranque del proxy nginx para Home Assistant Ingress.

## [1.0.7] - 2026-08-29

### Corregido
- Sustituida la interfaz completa de noVNC por un cliente VNC mínimo basado directamente en la API `RFB`.
- Eliminada la dependencia de `defaults.json` y `mandatory.json`.
- La URL WebSocket se construye explícitamente utilizando `X-Ingress-Path` proporcionado por Home Assistant.
- Eliminada la resolución incorrecta de `/websockify` contra la raíz de Home Assistant.
- Añadido diagnóstico de la URL WebSocket utilizada en la consola del navegador.

### Técnico
- nginx inyecta dinámicamente el valor de `X-Ingress-Path` en `vnc-ha.html`.
- Se mantiene noVNC únicamente como librería VNC mediante `core/rfb.js`.
- Nueva ruta: Home Assistant Ingress → nginx → websockify → x11vnc.

## [1.0.6] - 2026-08-29

### Corregido
- Reimplementada la integración de noVNC con Home Assistant Ingress.
- La ruta WebSocket deja de inferirse desde la URL del navegador.
- Uso del encabezado oficial `X-Ingress-Path` de Home Assistant para construir dinámicamente el endpoint WebSocket correcto.
- Añadido nginx como proxy frontal para noVNC.
- Separado el servidor HTTP de noVNC del proxy WebSocket.
- websockify pasa a ejecutarse internamente en el puerto 6080.
- nginx expone el puerto 8099 utilizado por Home Assistant Ingress.
- `mandatory.json` se genera dinámicamente para cada petición utilizando la ruta real de Ingress.

### Técnico
- Nueva arquitectura: Home Assistant Ingress → nginx → websockify → x11vnc.
- Eliminados los parches anteriores basados en rutas relativas de noVNC.

## [1.0.5] - 2026-08-29

### Corregido
- Corregida definitivamente la construcción de la URL WebSocket de noVNC bajo Home Assistant Ingress.
- Forzado `host` vacío en noVNC para que la conexión WebSocket se resuelva respecto a la URL actual de Ingress.
- Eliminada la dependencia de una URL WebSocket basada en el host raíz de Home Assistant.

### Técnico
- Configurados `host`, `port` y `path` mediante `mandatory.json`.
- noVNC utiliza ahora su soporte nativo de URLs WebSocket relativas.

## [1.0.4] - 2026-08-29

### Corregido
- Forzada la ruta WebSocket relativa de noVNC mediante `mandatory.json`.
- Evitado que configuraciones persistidas previamente en el navegador sobrescriban la ruta WebSocket requerida por Home Assistant Ingress.
- Configurado `./websockify` como endpoint obligatorio para la conexión VNC.

### Cambiado
- La configuración de noVNC pasa de `defaults.json` a `mandatory.json` para garantizar compatibilidad con Home Assistant Ingress.

## [1.0.3] - 2026-08-29

### Corregido
- Corregida la configuración del WebSocket de noVNC detrás de Home Assistant Ingress.
- Añadida configuración explícita de la ruta relativa `./websockify` mediante `defaults.json`.
- Eliminado el parche anterior sobre `vnc.html`, que no afectaba al flujo real de noVNC 1.6.0.

### Cambiado
- Se mantiene `vnc.html` como punto de entrada de Ingress.
- Simplificado el arranque de noVNC/websockify para usar la configuración nativa de noVNC.

## [1.0.2] - 2026-08-29

### Corregido
- Actualizado noVNC a la versión 1.6.0.
- Corregida la conexión WebSocket de noVNC detrás de Home Assistant Ingress.
- noVNC utiliza ahora rutas WebSocket relativas compatibles con el prefijo dinámico de Ingress.

### Cambiado
- noVNC deja de utilizar el paquete incluido en Ubuntu y se instala desde la versión oficial v1.6.0.

## [1.0.1] - 2026-08-29

### Corregido
- Mejorado el arranque de la interfaz de autenticación mediante noVNC.
- Añadidas comprobaciones de inicio para Xvfb, x11vnc y websockify.
- Mejorado el diagnóstico de errores de conexión entre noVNC y el servidor VNC.

### Cambiado
- Los procesos gráficos muestran ahora su salida directamente en el registro del add-on para facilitar la detección de errores.
- Versión dinámica en el run.sh


## 1.0.0 - 2026-08-29

- Primera versión estable.
- Autenticación manual integrada mediante Chromium visible, noVNC e Ingress.
- CAPTCHA resuelto manualmente por el usuario.
- Perfil Chromium persistente propio del add-on.
- Modo `login` para crear o renovar la sesión.
- Modo `auto` para descargas headless periódicas.
- Selección automática de frecuencia horaria.
- CSV en `/share/canal_consumo_horario.csv`.
- Estado en `/share/canal_estado.json`.
- Detección de sesión caducada sin reintentos agresivos.
