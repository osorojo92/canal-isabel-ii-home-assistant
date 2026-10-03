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


## Eventos de Home Assistant

El add-on publica eventos genéricos en el bus de Home Assistant para que cada instalación decida cómo reaccionar.

Cuando la sesión falta o deja de ser válida se publica:

- Evento: `canal_isabel_ii_event`
- `type: auth_required`
- `reason: session_missing` o `session_expired`
- `code`: código interno del error
- `message`: descripción
- `source: canal_isabel_ii_playwright`

El evento de autenticación se emite **una sola vez por incidencia**. La marca persiste entre reinicios y ejecuciones periódicas. Se rearma al completar correctamente una ejecución automática o al guardar una nueva sesión en `mode: login`.

Ejemplo de automatización:

```yaml
alias: Canal Isabel II - Requiere autenticación
triggers:
  - trigger: event
    event_type: canal_isabel_ii_event
    event_data:
      type: auth_required

actions:
  - action: notify.notify
    data:
      title: "Canal Isabel II"
      message: "{{ trigger.event.data.message }}"
```

El add-on no llama a ningún servicio de notificación concreto ni depende de scripts personalizados del usuario.
