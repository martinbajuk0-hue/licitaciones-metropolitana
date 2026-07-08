# Guía de uso

## Instalación

```bash
pip install -r requirements.txt
```

Las dependencias marcadas como opcionales en `requirements.txt` (Word,
Excel, OCR, Claude API) se pueden omitir si no se van a usar esas
funciones — `parser.py` y `analyzer.py` degradan avisando qué no pudieron
procesar, no rompen el resto del pipeline.

## Variables de entorno

| Variable | Requerida | Uso |
|---|---|---|
| `GMAIL_USER` | Para enviar email | Cuenta Gmail remitente |
| `GMAIL_APP_PASSWORD` | Para enviar email | [Contraseña de aplicación de Gmail](https://myaccount.google.com/apppasswords) |
| `EMAIL_DESTINO` | No (default: `GMAIL_USER`) | Destinatario de las notificaciones |
| `ANTHROPIC_API_KEY` | No | Habilita el resumen ejecutivo narrativo vía Claude en vez del resumen extractivo por reglas |
| `UMBRAL_5_ESTRELLAS`, `UMBRAL_4_ESTRELLAS`, `UMBRAL_3_ESTRELLAS`, `UMBRAL_2_ESTRELLAS` | No | Ajustan los cortes de puntaje de la clasificación ★ |

## Correr el monitoreo diario manualmente

```bash
python monitor.py                # corre completo, envía email si hay novedades
python monitor.py --sin-email    # corre el pipeline pero no envía email (debug)
```

El cron de producción está en `.github/workflows/monitor.yml` (corre a las
7am, 12pm y 6pm hora Uruguay).

## Analizar una licitación puntual

```bash
# Por URL (descarga y lee todos los documentos que encuentre en la página)
python cli.py analizar --url "https://www.comprasestatales.gub.uy/..." --titulo "Suministro de pisos - Intendencia de X"

# Por archivo local ya descargado
python cli.py analizar --archivo ./pliego.pdf --titulo "Suministro de pisos - Intendencia de X"

# Ver el informe completo en la terminal además de guardarlo
python cli.py analizar --url "..." --titulo "..." --stdout
```

El informe se guarda en `reports/<fecha>-<slug>.md`.

## Armar una cotización

```bash
python cli.py cotizar --items piso_spc:120 zocalo:40 --margen 25
```

Requiere que los `producto_id` usados existan en `knowledge/productos.yaml`
y tengan precio cargado en `knowledge/precios.yaml` — si no, el ítem sale
marcado como `SIN PRECIO CARGADO`.

## Agregar una palabra clave o producto nuevo

1. Editar `knowledge/keywords.yaml` (agregar el término en la categoría
   correspondiente).
2. Si es un producto nuevo del catálogo, agregarlo también en
   `knowledge/productos.yaml`.
3. Si tiene variantes/sinónimos frecuentes, agregarlos en
   `knowledge/sinonimos.yaml`.

No hace falta tocar ningún archivo `.py` para esto.

## Cargar la lista de precios real

Editar `knowledge/precios.yaml` siguiendo el formato documentado en el
propio archivo (un bloque por `producto_id`, con `precio_unitario`,
`moneda`, `iva_incluido`, `vigencia`, `fuente`).

## Correr los tests

```bash
python -m unittest discover -s tests -v
```
