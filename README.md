# Canal Isabel II Home Assistant

Add-on para Home Assistant que descarga automáticamente las telelecturas
del Canal de Isabel II usando Playwright y Chromium.

## Funcionamiento

- Reutiliza una sesión autenticada.
- Ejecuta Chromium en modo headless.
- Selecciona consumo horario.
- Descarga el CSV.
- Guarda el resultado en `/share/canal_consumo_horario.csv`.

## Importante

El fichero `canal_state.json` contiene información de sesión y NO debe
subirse al repositorio.
