# Clasificación de oportunidades (★)

Implementada en `analyzer.estimar_probabilidad_exito()` +
`report.clasificar_oportunidad()`. Ver también `prompts/clasificacion_oportunidad.md`
para el criterio en palabras.

## Fórmula del score (0-100)

Punto de partida: 30 (piso base si se identificó al menos un producto).

| Factor | Efecto |
|---|---|
| Categorías de producto Metropolitana identificadas | +12 por categoría, hasta +40 |
| Organismo identificado (de `knowledge/organismos.yaml` o `knowledge/sinonimos.yaml`) | +15 |
| Campos clave no identificados (`campos.faltantes`) | -4 por campo, hasta -20 |
| Riesgos de severidad alta (`risk.py`) | -10 por riesgo, hasta -30 |
| Riesgos de severidad media | -3 por riesgo, hasta -15 |
| Ítems de checklist documental sin evidencia en el pliego | -2 por ítem, hasta -20 |
| Ninguna categoría de producto identificada | -30 adicional |

El score final se acota a `[0, 100]`.

## Umbrales por defecto

| Score | Nivel |
|---|---|
| ≥ 85 | ★★★★★ Excelente |
| ≥ 65 | ★★★★ Buena |
| ≥ 45 | ★★★ Dudosa |
| ≥ 25 | ★★ Poco conveniente |
| < 25 | ★ No presentarse |

Configurables sin tocar código vía variables de entorno (ver
`docs/GUIA_USO.md`).

## Por qué es una fórmula y no una decisión de un LLM

El score debe ser reproducible y auditable — el informe siempre incluye la
sección "Por qué este puntaje" con cada sumando/resta explicado. Si en el
futuro se agrega el resumen ejecutivo vía Claude (`ANTHROPIC_API_KEY`),
ese resumen es narrativo y complementario, pero **no** reemplaza ni
recalcula el score numérico.
