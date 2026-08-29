# Canal Isabel II Playwright

## Primera autenticación

1. Configura `mode: login`.
2. Reinicia el add-on.
3. Pulsa **Abrir interfaz web**.
4. En noVNC, pulsa **Connect** si fuese necesario.
5. Inicia sesión normalmente.
6. Si aparece CAPTCHA, resuélvelo manualmente.
7. Cuando estés dentro de la zona privada, cambia `mode` a `auto`.
8. Reinicia el add-on.

## Modo automático

El add-on reutiliza el mismo perfil persistente y descarga las telelecturas con Chromium headless.

Archivos de salida:

- `/share/canal_consumo_horario.csv`
- `/share/canal_estado.json`

## Renovar sesión

Si los registros indican que la sesión ha caducado, cambia temporalmente a `mode: login`, vuelve a autenticarte manualmente y regresa después a `mode: auto`.

No es necesario copiar cookies, `JSESSIONID` ni `canal_state.json`.
