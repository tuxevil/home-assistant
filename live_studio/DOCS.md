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
3. Dejar `destination_url` vacío para las pruebas locales. Para emitir, configurar
   la URL RTMP/RTMPS completa de ingest y su clave en este campo de contraseña.
4. Iniciar la app. La API queda disponible, pero todavía no emite.
5. Instalar y añadir la integración Live Studio, indicando la dirección interna
   `http://<id-del-repositorio>-live-studio:8099` y el mismo token.
6. En las opciones de la integración, añadir cámaras con su URL RTSP, nombre y
   descripción. Configurar carpeta de música, vídeo y textos en sus menús.
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

El sensor se elige en las opciones de la integración. Se transmite su nombre,
valor y unidad cada 15 segundos. `unknown` o `unavailable` retiran el texto; si
Home Assistant deja de actualizarlo se oculta en un máximo de 120 segundos.
No hay dependencia de MQTT, Frigate, una cámara concreta, IA ni un proveedor cloud.

La marquesina se desplaza en una franja inferior semitransparente. El aviso aparece
cada `cta_period` segundos durante `cta_duration` segundos. El texto se trata
literalmente: ni `%{...}`, comillas, dos puntos o saltos de línea ejecutan filtros.
La tipografía incluida soporta español; algunos emojis pueden no tener glifo.
La distribución visual y la velocidad de desplazamiento siguen siendo fijas.

## Cambios y recuperación

Detener antes de añadir/retirar cámaras, editar sus conexiones, cambiar carpeta de
música, resolución, fps, bitrate o hilos. Seleccionar otra cámara ya configurada,
los textos y los parámetros de selección sí se cambian en vivo. Solo hay una salida
activa; una vista previa no puede arrancar encima de una emisión en vivo.

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
