# Changelog
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