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

El add-on puede intentar recuperar automáticamente una sesión caducada.

Opciones disponibles:

- `auto_relogin`: activa o desactiva la recuperación automática.
- `username`: usuario de acceso.
- `password`: contraseña de acceso; Home Assistant la muestra enmascarada.
- `user_type`: texto del tipo de usuario que debe seleccionar el formulario; por defecto `particular`.

Cuando `auto_relogin: true` y la sesión no es válida:

1. El add-on realiza **un único intento automático por incidencia**.
2. Si el login funciona, guarda la nueva sesión, continúa la ejecución y publica `type: auth_recovered`.
3. Si aparece CAPTCHA, no intenta resolverlo. Publica `type: auth_required` y exige autenticación manual.
4. Si el login falla por cualquier otro motivo, tampoco vuelve a intentarlo en las siguientes ejecuciones de esa misma incidencia.
5. Al completar un login manual correcto en `mode: login`, se rearma el mecanismo para futuras incidencias.

Si `auto_relogin: false`, se mantiene el comportamiento manual: cuando la sesión caduque, cambia temporalmente a `mode: login`, vuelve a autenticarte y regresa después a `mode: auto`.

No es necesario copiar cookies, `JSESSIONID` ni `canal_state.json`.


## Eventos de Home Assistant

El add-on publica eventos genéricos en el bus de Home Assistant para que cada instalación decida cómo reaccionar.

Cuando la sesión requiere intervención manual se publica:

- Evento: `canal_isabel_ii_event`
- `type: auth_required`
- `reason`: causa concreta, por ejemplo `session_expired`, `captcha_required`, `credentials_missing` o `login_failed`
- `code`: código interno del error
- `message`: descripción
- `source: canal_isabel_ii_playwright`

Cuando el add-on recupera por sí mismo una sesión caducada se publica:

- Evento: `canal_isabel_ii_event`
- `type: auth_recovered`
- `reason: automatic_login`
- `trigger_reason`: `session_expired` o `session_missing`
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


## Prueba automática en modo login

Si `auto_relogin: true` y el add-on se inicia con `mode: login`, se realiza un único intento automático de autenticación al abrir la página de Canal.

El registro indica expresamente si el intento termina con `ÉXITO` o `SIN ÉXITO`. Si falla, no se repite en bucle: Chromium permanece visible para continuar manualmente desde noVNC. Este intento de `mode: login` es independiente del límite de un intento por incidencia utilizado por el modo automático.


## Prueba limpia de credenciales en modo login

Desde la versión 1.3.4, cuando `mode: login` y `auto_relogin: true`, el intento automático se realiza **sin reutilizar la sesión guardada**.

Antes de probar las credenciales, el add-on elimina las cookies y el almacenamiento web del perfil de Chromium para esa prueba. No restaura `canal_session.json` ni `canal_session_storage.json`. El acceso se intenta exclusivamente con `username`, `password` y `user_type` de la configuración.

Si el intento tiene éxito, la nueva sesión se guarda mediante el flujo normal. Si falla, el navegador permanece abierto para completar el login manualmente.
