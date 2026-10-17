# Instalación y uso

## Requisitos

Home Assistant OS para instalar como app/add-on, o Docker para ejecutar el motor
por separado. Una cámara o restream RTSP accesible, capacidad de CPU para H.264 y
espacio para la caché de música. La integración se prueba con Home Assistant
2026.10.1 y declara mínimo 2026.10.0.

## Configurar el motor

1. Instalar Live Studio Engine desde este repositorio y arrancarlo.
2. Configurar `api_token` con al menos 32 caracteres ASCII sin espacios. Generar un
   valor aleatorio propio; no usar claves copiadas de ejemplos.
3. Dejar `destination_url` vacío para las pruebas. Este campo es una compatibilidad
   para la salida original; los nuevos destinos se configuran por live en las
   opciones de la integración.
4. Iniciar la app. La API queda disponible, pero todavía no emite.
5. Instalar y añadir la integración Live Studio, indicando la dirección interna
   `http://<id-del-repositorio>-live-studio:8099` y el mismo token.
6. Conectar el live existente o elegir **Crear un live**, indicando nombre, una o
   varias fuentes y sensores opcionales. En Opciones se administran cámaras,
   música, textos, reglas y destino de ese live.
7. Pulsar **Grabar vista previa de 20 segundos**. Ver el archivo
   `/media/live_studio/preview.mp4` desde los medios de Home Assistant.
8. Una vez revisado el resultado, activar **Emisión en vivo** para publicar en el
   ingest configurado. El servicio no crea ni finaliza eventos de YouTube.

El nombre interno depende del identificador asignado por Supervisor al repositorio.
No se necesita publicar el puerto en Internet. Si el motor vive en otra máquina,
usar una dirección de la LAN accesible desde Home Assistant. Se admite HTTPS con
certificado válido; no se desactiva su verificación.

## Música

Colocar MP3 en `/share/stream_music/` o seleccionar otra carpeta dentro de `/share`
o `/media`. Se ordenan alfabéticamente. La primera preparación crea archivos FLAC
estéreo a 44100 Hz en almacenamiento privado `/data/audio`; necesita tiempo y disco.
Si no hay MP3, se genera silencio. Los archivos con errores impiden preparar la
salida: revisar la carpeta, retirar el archivo defectuoso y volver a probar.

Se guarda pista y posición cada cinco segundos y al desconectar. Se retoma al
reconectar; una terminación forzada puede repetir unos segundos. Si se retiró la
pista guardada, empieza la lista actual. La carpeta se examina cada 30 segundos. Añadir, retirar o modificar MP3 reinicia
la salida para reconstruir la lista, conservando la posición cuando es posible.
La caché no se limpia automáticamente.

Usar música con permiso para emisión pública. No se incluyen archivos de música.

## Textos y sensor

El título, marquesina y aviso periódico tienen entidades `text` para editarlos
desde dashboards y automatizaciones, por ejemplo con `text.set_value`. Un texto
vacío oculta ese elemento. El reloj usa una zona horaria IANA, como `Europe/Madrid`.
Los cambios de texto se aplican en aproximadamente un segundo.

Cada live puede seleccionar entre cero y ocho sensores en **Live y sensores**.
Se transmite su nombre, valor y unidad cada15 segundos. `unknown` o `unavailable`
retiran solo esa lectura; una lista vacía no muestra información. Las líneas
largas se desplazan para permitir leerlas. Si Home Assistant deja de actualizar
los datos, se ocultan en un máximo de120 segundos.
No hay dependencia de MQTT, Frigate, una cámara concreta, IA ni un proveedor cloud.

La marquesina se desplaza en una franja inferior semitransparente. El aviso aparece
cada `cta_period` segundos durante `cta_duration` segundos. El texto se trata
literalmente: ni `%{...}`, comillas, dos puntos o saltos de línea ejecutan filtros.
La tipografía incluida soporta español; algunos emojis pueden no tener glifo.
La distribución visual y la velocidad de desplazamiento siguen siendo fijas.

## Cambios y recuperación

Detener antes de añadir/retirar cámaras, editar sus conexiones, cambiar carpeta de
música, resolución, fps, bitrate o hilos. Seleccionar otra cámara ya configurada,
los textos y los parámetros de selección sí se cambian en vivo. Cada live tiene una sola salida activa; su vista previa no puede arrancar encima
de su propia emisión. Otros lives pueden continuar emitiendo simultáneamente.

La salida en vivo reintenta tras fallos; el watchdog reconecta si el vídeo deja de
avanzar 45 segundos. Se conserva la intención de emitir tras reiniciar la app.
Detener desactiva esa intención. Una vista previa no se restaura ni reintenta sola.
Cada cámara tiene su propio receptor con reconexión. Al cambiar de fuente se
conservan el codificador, la conexión de salida y la música. Si falta imagen se
muestra una pantalla negra con aviso mientras se recupera; la salida sigue.
Una caída del ingest o de Internet sí obliga a reconectar la salida.

## Credenciales y registros

El token API y el destino se configuran en la app; la URL RTSP puede contener
credenciales y se guarda en el almacenamiento privado del motor. Las opciones de versiones
anteriores pueden conservar una copia hasta volver a guardarlas. Las copias de seguridad deben tratarse como privadas.

Estado y diagnósticos no contienen URL RTSP, destino ni tokens. No se publican las
líneas de FFmpeg porque pueden incluir contraseñas. La configuración de vídeo
completa solo está disponible para clientes autenticados. Proteger el acceso a
Home Assistant y a la red local. No hay telemetría ni cuenta propia del proyecto.

## Docker independiente

Construir desde `live_studio/` con `docker build -t live-studio-engine .`. Montar:

- Directorio de datos propio en `/data`, con `options.json` privado que contenga
  `api_token` y `destination_url` (vacío para pruebas).
- Carpeta de MP3 de solo lectura en `/share/stream_music`.
- Carpeta de salidas locales escribible en `/media/live_studio`.

Conectar Home Assistant y el motor a una red privada común, o publicar el puerto
8099 únicamente en una interfaz de confianza. El motor no requiere Docker socket,
red del host ni privilegios. No usar el directorio de datos de otro add-on.

## Retirada

Detener desde la integración antes de desinstalar. Quitar la integración por sí
solo no detiene una emisión: el motor es independiente. Detener/desinstalar la app
para finalizar su envío. La emisión pública de YouTube puede seguir abierta según
su configuración de finalización automática.

## Selección manual y automática (0.2.0)

El selector ofrece Automático y cada cámara. Elegir un nombre fuerza esa vista;
ninguna comparación ni fallo cambia una selección manual. Volver a Automático
permite decidir con las siguientes comparaciones o por pérdida de señal.

La integración expone cámaras de instantáneas para cada fuente y para la vista
actual. Durante una salida solo devuelven fotogramas recientes; no sirven imágenes
antiguas cuando una cámara falla. No son nuevos restreams para reproducción.

La IA es opcional: instalar LLM Vision y configurar allí un proveedor con visión
(local o cloud, incluido un proxy compatible). En Opciones → Selección automática,
elegir ese proveedor y su modelo. Live Studio no guarda su API key ni exige un
proveedor concreto. Las imágenes se envían al proveedor elegido; tenerlo en cuenta
antes de habilitarlo. El botón Comparar vistas permite una consulta manual incluso
con la salida detenida. Las consultas programadas se hacen solo al emitir o grabar
y con selección automática. La frecuencia y costes dependen del proveedor.

Valores iniciales: comparación cada 10 minutos, ventaja mínima 10 puntos,
preferencia diurna +5, dos confirmaciones y permanencia mínima 20 minutos. Hay
entidades numéricas para ajustar estos valores en vivo. El bonus solo se aplica
con `sun.sun` confirmado sobre el horizonte y metadatos recientes; no se estima
el movimiento de nubes a partir de una foto. La cámara preferida se elige en las
opciones. De noche no se aplica ese bonus.

Los resultados caducados, repetidos o posteriores a una selección/configuración
ya modificada se rechazan. Una cámara sin vídeo confirmado impide el cambio por
comparación. En Automático, dos controles de salud fallidos consecutivos (cada
cinco segundos) permiten saltar a otra fuente sana sin esperar la permanencia.
Con una sola cámara se mantiene la reconexión; no hace falta IA.

Cada fuente se decodifica mientras la salida está activa, aunque no esté elegida.
La carga crece con el número de cámaras. La resolución/fps de salida es común a
todas; probar CPU y memoria antes de añadir más fuentes.

Actualizar primero el motor a 0.2.0 y después la integración a 0.2.0. Ver la
[guía de migración](MIGRATION.md) antes de reemplazar otro emisor.

## Varios lives en un motor

Un motor 0.3.0 puede alojar hasta 16 lives, según los recursos disponibles. Cada uno
selecciona1–8 fuentes de cámara y cero a ocho sensores. Los límites no garantizan
que un equipo pueda transcodificar todas esas salidas a la vez: medir su carga.

En Ajustes → Integraciones → Live Studio → Añadir entrada, elegir **Crear un live**.
Se reutiliza la conexión del motor existente. Indicar nombre, fuentes y sensores;
si el catálogo está vacío, el asistente pide la primera URL RTSP. También se puede
conectar a un live ya creado o a otro motor. No es necesario instalar otra app por
cada emisión. El catálogo ofrece fuentes configuradas en los otros lives del motor;
una misma cámara puede participar en varios, con decodificadores independientes.

En Opciones de cada entrada:

- **Live y sensores:** renombrar y seleccionar una lista propia, incluso vacía.
- **Cámaras:** seleccionar fuentes existentes o añadir/editar conexiones RTSP.
- **Destino de emisión:** URL RTMP/RTMPS privada con clave. No se devuelve ni se
  guarda en las opciones de Home Assistant. Detener ese live antes de cambiarla.
  Un campo vacío conserva el destino; retirarlo exige marcar la opción explícita.
- **Vídeo/música, textos y reglas:** independientes para cada live.
- **Eliminar este live:** requiere detenerlo y confirmar. No detiene otros lives
  ni cierra eventos de YouTube. Se archivan configuraciones pequeñas para recuperación.

Un live nuevo queda detenido y sin destino. Su propia intención de emisión se
restaura tras reiniciar el motor únicamente si se había iniciado explícitamente.
Un error de recepción, codificación o configuración de un live no arranca ni
cambia la salida de otro. Reiniciar o detener toda la app sí afecta a todos sus
lives: para manejar uno solo, usar sus entidades nativas.

Los datos viven en `/data/lives/<id>`; el live migrado conserva `/data` y sus IDs.
Las muestras nuevas se guardan en `/media/live_studio/<id>/preview.mp4`; la original
mantiene `/media/live_studio/preview.mp4`. Los marcadores y cachés de audio son
independientes, aunque varios lives lean la misma carpeta MP3. Esto ocupa disco.

La actualización desde 0.2 conserva los datos y las entidades del live original.
Las entradas existentes de motores anteriores pueden seguir conectadas, pero para
crear nuevos lives en un motor se requiere0.3.0. Engine2 sigue disponible como
servidor adicional opcional por compatibilidad; no hace falta para crear otro live.
Su código se genera con`scripts/sync_engine_instances.py` y CI comprueba la igualdad.

La API autenticada añade`GET /api/server`, `GET/POST /api/lives`,
`GET/PATCH/DELETE /api/lives/<id>`, `GET /api/catalog`, y rutas por live como
`/api/lives/<id>/status`, `config`, `metadata`, `start`, `stop`, `destination` y
`cameras/<source>/snapshot.jpg`. Las rutas originales siguen siendo alias del
live original. El token del motor permite administrar todos sus lives; usarlo solo
en una red y clientes de confianza. No se añade telemetría ni una cuenta cloud.

## Optional external engine and GPU

Use the same companion API on Linux (native systemd or a container) instead of the HAOS app when desired. Example service: `deploy/systemd/live-studio.service` in this repository. Install Python, the packages in `requirements.txt` (aiohttp and pyzmq), FFmpeg with the `zmq` and `drawtext` filters, fonts and the drivers appropriate to your hardware. No Proxmox dependency.

`STUDIO_DATA` contains private options.json (API token), profile settings/identities/destinations/bookmarks. `STUDIO_MEDIA` stores previews. `STUDIO_MUSIC_ROOTS` is an administrator-controlled colon-separated directory allowlist (default `/share:/media`); configure it for external music storage. Copy or mount music separately and preserve bookmark/cache paths on relocation. No installation-specific paths, addresses or tokens are required in public source.

Per-live `video_encoder` and `video_decoder`: `cpu` (default), `vaapi`, `auto`. Optional `vaapi_device` selects an accessible render node; empty discovers render nodes. Explicit VAAPI fails visibly if initialization is unavailable. Automatic mode exposes its actual backend/fallback in status; a source may fall back to CPU after failed hardware decoding. VAAPI can work with different vendors depending on driver support. Software overlays use CPU; hardware frames are transferred as needed, not a zero-copy pipeline.

`source_buffer_ms` defaults to250 (0–2000). Source presentation timestamps, rather than packet arrival, pace camera pictures through a bounded buffer. Clock discontinuities reset that buffer; overdue frames are skipped instead of accelerated playback. Increasing buffering adds latency, and cannot repair a long source outage or invent intermediate camera frames.

For relocation, test privately with resume intents disabled before changing HA entries. Preserve identities and move private destinations only when the old sender is stopped; disable old app autostart/watchdog after cutover. Internal HAOS add-on DNS names and media paths require reachable equivalents externally.

### Camera motion diagnostics

Encoder `fps` includes repeated pictures and animated overlays. Status also
reports `feed_fps` (raw frames delivered to the compositor), `selected_frame_fps`
(new selected camera frame objects delivered per second), and
`feed_max_block_seconds` (longest pipe wait). These values update every five
seconds and are initially null. They measure frame delivery, not optical motion
or image-content uniqueness. A15FPS camera normally yields about15 selected
frames and30 compositor frames per second when output is30FPS.

The paced pipe uses frame-count timestamps. A slow ingest handshake may delay
startup, but cannot recursively create duplicate video frames from each input
read delay. A sustained encoder/network bottleneck still requires resolving
that bottleneck; changing timestamp policy does not add processing capacity.

### Live overlay layout

Engine0.5.0 adds `overlay_layout`. Each of `title`, `source`, `date`, `clock`,
`sensor`, `ticker` and `cta` accepts partial updates for `visible`, `anchor`,
`x`, `y`, `font_size`, `color`, `background_color`, `background_opacity`,
`shadow`, `scroll`, `speed` and `direction`. Anchors are `auto` or a combination
of `top`/`middle`/`bottom` and `left`/`center`/`right`. Offsets and font sizes
use a1080p reference and scale with output height. Colors use `#RRGGBB`.
Scrolling can be `off`, `overflow` or `always`; speed0 keeps text stationary.

`band` accepts `visible`, `position` (`top`/`bottom`), `height`, `color` and
`opacity`. Automatic positions keep information/ticker inside the bar and
place other labels around it; custom anchors let you position each separately.
Date formats are `iso`, `day_first`, `month_first`; time formats are
`24h_seconds`, `24h`, `12h`. The existing `timezone` controls both.

Layout commands use a private Unix socket in the overlay directory, not a TCP
port. Edits preserve the encoder, RTMP session and audio bookmark. Status
`overlay_pending` remains true until commands are accepted. Partial updates
merge without resetting other elements or lives. Existing `show_clock` and
`show_camera_name` flags remain compatible; date visibility is independent.

Authenticated `GET /api/lives/{live_id}/overlay/snapshot.jpg` returns a fresh
JPEG with the desired layout for review; it does not replace the live output.
The integration exposes this as an overlay-preview camera and bundles a
Lovelace editor card.

The bundled app uses Debian13 and FFmpeg7, matching the reference external
Linux deployment. FFmpeg8 packages that terminate during live `drawtext`
resizing are not supported for this feature; changing to a newer major version
requires passing the runtime rendering tests, not just detecting filter names.
