# Arquitectura

## Visión general

```
                 ┌───────────────────────┐
   cron 3x/día → │      monitor.py       │  paso 1-2: qué hay nuevo / qué cambió
                 └───────────┬───────────┘
                              │ URL de licitación relevante
                              ▼
                 ┌───────────────────────┐
                 │      parser.py        │  paso 3-4: descarga y extrae texto
                 │ PDF/Word/Excel/imagen │
                 └───────────┬───────────┘
                              │ texto completo del pliego
                              ▼
        ┌─────────────────────────────────────────┐
        │                analyzer.py                │  paso 5-7, 12-13
        │ campos clave · productos · resumen · score │
        └───────┬─────────────────┬─────────────────┘
                 │                 │
                 ▼                 ▼
        ┌───────────────┐ ┌───────────────────┐
        │    risk.py     │ │    checklist.py    │   paso 8-9
        │ multas/riesgos │ │ documentación      │
        └───────┬────────┘ └─────────┬──────────┘
                 │                    │
                 └─────────┬──────────┘
                            ▼
                 ┌───────────────────────┐
                 │      report.py        │  paso 6,9,14,15
                 │ informe .md + score ★ │
                 └───────────┬───────────┘
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
         reports/*.md              email (monitor.enviar_email)

        pricing.py (paso 10) y templates/*.md (paso 11) se usan
        aparte, sobre un informe ya generado, para armar la oferta.
```

`cli.py` expone el mismo pipeline (`parser → analyzer → risk → checklist →
report`) para correrlo a demanda sobre una licitación puntual, sin esperar
al cron.

## Por qué esta separación de módulos

Cada módulo hace una sola cosa y no depende de que los demás existan:

- `parser.py` no sabe nada de Metropolitana — solo convierte documentos a
  texto. Se podría reusar en otro proyecto sin cambios.
- `analyzer.py` no descarga nada ni genera Markdown — solo transforma
  texto en datos estructurados.
- `risk.py` y `checklist.py` son independientes entre sí; cualquiera de
  los dos puede fallar sin tumbar al otro.
- `report.py` es el único que conoce a todos los demás — es la capa de
  orquestación y presentación.
- `pricing.py` es el único que toca dinero, deliberadamente aislado para
  que la regla "nunca inventar precios" tenga un solo lugar donde
  aplicarse.

## Configuración y base de conocimiento

`config/settings.py` es el único punto de acceso a:

- `config/empresa.yaml` — datos societarios de Metropolitana.
- `knowledge/keywords.yaml` — términos de búsqueda por categoría de producto.
- `knowledge/sinonimos.yaml` — expansión de siglas y variantes.
- `knowledge/organismos.yaml` — organismos públicos prioritarios.
- `knowledge/productos.yaml` — catálogo de productos y equivalencias.
- `knowledge/precios.yaml` — lista de precios (vacía hasta que se cargue).

Ningún módulo abre estos YAML directamente; todos pasan por
`config/settings.py`, cacheado con `functools.lru_cache`. Esto significa
que **para ajustar el comportamiento del sistema casi nunca hace falta
tocar código** — alcanza con editar estos YAML.

### Señal fuerte vs. señal débil en `knowledge/keywords.yaml`

El archivo tiene ~3000 términos (`categorias.*.keywords`, `terminologia_pliegos`,
`materiales`, `normativas`, `marcas`, `errores_comunes`, `abreviaturas`,
`lugares_uso`, `aplicaciones`). No todos disparan relevancia de la misma forma:

- **Señal fuerte** (`config.settings.todas_las_palabras_clave()`): categorías
  de producto + terminología de pliegos + materiales + normativas + marcas +
  errores comunes + abreviaturas. Una sola coincidencia alcanza para marcar
  la licitación como relevante.
- **Señal débil / contexto** (`config.settings.palabras_clave_contexto()`):
  `lugares_uso` (escuela, hospital, intendencia...) y `aplicaciones`
  (interior, alto tránsito...) **nunca** disparan relevancia por sí solas —
  aparecen en prácticamente cualquier licitación pública de Uruguay sin
  importar el rubro. Solo se calculan y se muestran (`analyzer.identificar_contexto`)
  cuando la licitación ya fue marcada relevante por una señal fuerte, como
  dato adicional en el informe ("Contexto adicional: lugar de uso: escuela").

Esta separación se agregó después de que un chequeo automático
(`tests/test_settings_keywords.py::test_no_falsos_positivos_en_licitaciones_no_relacionadas`)
detectara que meter términos genéricos en la señal fuerte (siglas de
organismos, vocabulario administrativo tipo "compra directa"/"orden de
compra") hacía que el sistema marcara como relevante prácticamente
cualquier licitación pública. Al agregar términos nuevos a `keywords.yaml`,
preguntarse: *¿este término, aparecería en una licitación de CUALQUIER
rubro (computadoras, catering, uniformes)?* Si la respuesta es sí, va en
`lugares_uso`/`aplicaciones`, nunca en una de las listas de señal fuerte.

Los términos cortos (≤5 caracteres, sin espacio — ej. `pu`, `eva`, `sbr`)
matchean por límite de palabra (`config.settings.coincide_palabra_clave`),
no por substring plano, para evitar falsos positivos como "pu" dentro de
"publico".

## Estado persistente

`data/licitaciones_vistas.json` guarda, por id de licitación, título,
hash de título+descripción, fecha de primera detección y cantidad de
notificaciones. Se usa para:

- No volver a analizar una licitación ya vista.
- Detectar aclaraciones/modificaciones (cambia el hash → se notifica de
  nuevo, marcado como "modificada").

Es cacheado entre corridas del workflow de GitHub Actions vía
`actions/cache`.

## Integración opcional con Claude (LLM)

`analyzer.generar_resumen_ejecutivo()` intenta usar la API de Claude
(paquete `anthropic`, variable `ANTHROPIC_API_KEY`) para producir un
resumen narrativo de mejor calidad que el extractivo por reglas. Si la key
no está configurada, o el paquete no está instalado, el sistema sigue
funcionando con el resumen por reglas — **nunca falla el pipeline por
falta de LLM**, es una mejora opcional en capas.

## Reportes

`report.guardar_informe()` escribe cada informe en `reports/<fecha>-<slug>.md`.
Esta carpeta está en `.gitignore` (son artefactos generados, no código) —
si se quiere conservar el historial de informes en git, sacarla del
`.gitignore` y commitear manualmente los que interesen.

## Extender el sistema

- **Nuevo producto/keyword:** editar `knowledge/keywords.yaml` y
  `knowledge/productos.yaml`. No requiere tocar código.
- **Nuevo organismo prioritario:** editar `knowledge/organismos.yaml`.
- **Cargar precios reales:** editar `knowledge/precios.yaml` siguiendo el
  formato documentado en el propio archivo.
- **Nuevo tipo de riesgo a detectar:** agregar un patrón a la lista
  correspondiente en `risk.py` (`_PATRONES_*`).
- **Nuevo ítem de checklist:** agregar una entrada a `_ITEMS_ESTANDAR` en
  `checklist.py`.
- **Cambiar los umbrales de clasificación ★:** variables de entorno
  `UMBRAL_5_ESTRELLAS`, `UMBRAL_4_ESTRELLAS`, etc. (ver
  `config/settings.umbral_estrellas`), sin tocar código.
