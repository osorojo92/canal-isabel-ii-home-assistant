# Changelog

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