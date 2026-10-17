# Reemplazar un emisor existente

0.2.0 incorpora continuidad entre cámaras y controles de selección. Una instalación
existente puede tener automatizaciones adicionales que requieren adaptación antes
de cambiar su salida pública. Instalar el motor en paralelo con destino vacío y
probar mediante grabación o ingest local; nunca conectar dos emisores a la misma
clave pública simultáneamente.

| Función | Live Studio 0.2.0 | Verificación previa al cambio |
| --- | --- | --- |
| RTSP TCP y reconexión | Receptor independiente por cámara | Probar pérdida y retorno en señales de prueba |
| Música en bucle | MP3 ordenados, AAC, marcador persistente | Comprobar las pistas, volumen y continuidad |
| Cambio manual | Selector nativo | Confirmar misma salida y música durante cambios |
| Selección visual | LLM Vision opcional | Elegir proveedor/modelo y comparar imágenes recientes |
| Preferencia diurna | Cámara configurable + bonus con sol conocido | Revisar puntuaciones brutas y efectivas |
| Margen/confirmaciones/permanencia | Números editables en vivo | Igualar los valores anteriores |
| Fallo de cámara | Doble comprobación y alternativa sana en Auto | Manual conserva la elección del usuario |
| Elementos gráficos | Título, reloj, sensor, marquesina y CTA | Revisar tamaño, privacidad y legibilidad |
| YouTube evento, OAuth y Analytics | Externos al motor | Mantener el mismo evento y sus integraciones |
| Paisaje, avisos y WhatsApp | Automatizaciones externas | Reenlazar fuentes, frescura y acciones antes del cambio |

## Contratos para automatizaciones externas

Usar las entidades de esta integración que correspondan a la instalación:

- El sensor **Cámara actual** publica `camera_entity`, `camera_id`, modo y hora del
  último cambio. Configurar el vínculo físico en las opciones de cada fuente.
- El binario **Vídeo actual** confirma que el fotograma elegido está reciente.
- La cámara **Vista actual** sirve una instantánea reciente o falla explícitamente.
- El selector permite forzar una cámara o volver a automático.
- El interruptor **Emisión en vivo** y el botón **Detener salida** controlan el motor.

Adaptar en conjunto análisis de paisaje, notificaciones, imágenes adjuntas,
comprobaciones de antigüedad y botones de inicio/parada. Revisar referencias a
sensores, cámaras y al identificador del add-on anterior. Una automatización que
siga leyendo la vista anterior podría publicar un paisaje distinto al emitido.
No reenlazar estas referencias mientras el emisor anterior siga siendo producción.

## Lista de comprobación operativa

1. Guardar configuración y estado de ambos emisores en ubicaciones privadas.
2. Validar emisión local con las cámaras y lista completas, incluyendo cambios,
   fallos simulados, recuperación y revisión visual. Una prueba de diez minutos
   no sustituye la observación prolongada de una emisión 24/7.
3. Preparar las adaptaciones anteriores y un procedimiento inverso de reversión.
4. Autorizar el cambio público. Detener primero el emisor anterior; entonces
   configurar el destino privado en Live Studio y arrancar su emisión.
5. Confirmar vídeo, audio, evento público, señales de frescura y automatizaciones.
   Si falla, detener el nuevo antes de reactivar el anterior.

Los marcadores de música de otros proyectos no se importan automáticamente. Si se
necesita conservar exactamente la canción, preparar y validar una conversión privada
del marcador. No copiar directorios de datos enteros entre add-ons.
