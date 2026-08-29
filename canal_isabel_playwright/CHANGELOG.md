# Changelog

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