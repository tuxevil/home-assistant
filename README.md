# Tuxevil · Home Assistant

Proyectos abiertos para Home Assistant. Licencia MIT.

## Live Studio — 0.3.0 (versión de desarrollo)

Motor local de streaming: varios lives independientes, cámaras RTSP, música y textos actualizables
sobre el vídeo. La integración de Home Assistant se distribuye por separado para
que HACS pueda gestionar sus versiones.

| Proyecto | Ubicación | Instalación |
| --- | --- | --- |
| Live Studio Engine | [`live_studio/`](live_studio/) | Repositorio de apps/add-ons de HAOS |
| Live Studio Engine 2 | [`live_studio_2/`](live_studio_2/) | Segunda salida independiente y opcional en HAOS |
| Live Studio | [tuxevil/ha-live-studio](https://github.com/tuxevil/ha-live-studio) | Integración HACS mediante repositorio personalizado |

## Instalar el motor en HAOS

Añadir `https://github.com/tuxevil/home-assistant`
en Ajustes → Apps → Tienda → Repositorios. Instalar **Live Studio Engine** y seguir
su [documentación](live_studio/DOCS.md).

El repositorio puede alojar más apps y documentación. Las futuras integraciones
HACS tendrán repositorios propios; no se agrupan varios dominios dentro de un
mismo `custom_components/` para su distribución por HACS.

Incluye cambio continuo entre cámaras y selección automática opcional con IA.
No incluye GPU, OAuth de YouTube ni migración automática de instalaciones existentes.
