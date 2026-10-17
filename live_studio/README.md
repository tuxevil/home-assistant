# Live Studio Engine

Motor de vídeo local para [Live Studio](https://github.com/tuxevil/ha-live-studio).
Versión de desarrollo **0.1.0**, licencia MIT.

- Entrada RTSP por TCP; salida H.264 y AAC.
- Reloj, título, sensor, marquesina y aviso periódico sobre la imagen.
- Actualizaciones de texto sin reiniciar FFmpeg.
- Música MP3 normalizada una vez, en bucle y con posición guardada.
- Vista previa local de duración limitada, sin conectarse al ingest de YouTube.
- API local autenticada para la integración de Home Assistant.

Consulta [instalación y funcionamiento](DOCS.md). Los parámetros por defecto son
1080p, 15 fps, H.264 `veryfast` y 3000 Kbps. La carga depende del vídeo, equipo y
ajustes; se debe medir antes de usar en producción. AMD64 se ha probado; AArch64
está declarado para construcción pero aún no se ha validado en hardware.

No inicia una emisión al instalar. Una emisión iniciada explícitamente se reintenta
si falla y se restaura tras reiniciar el motor. **Detener** cancela esa restauración.
El reinicio de Home Assistant no detiene el motor.
