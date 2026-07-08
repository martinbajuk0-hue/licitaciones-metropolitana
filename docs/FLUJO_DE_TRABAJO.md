# Flujo de trabajo

> Contenido íntegro del documento fuente "Prompt Claude Code Licitaciones
> Metropolitana — Parte 2", con el mapeo a cada módulo que lo implementa.

1. Revisar diariamente nuevos llamados.
2. Detectar aclaraciones, modificaciones y adjudicaciones.
3. Descargar toda la documentación.
4. Leer íntegramente el pliego.
5. Identificar productos de Metropolitana aunque el título no los mencione.
6. Elaborar un resumen ejecutivo.
7. Extraer: organismo, número, fechas, garantías, visitas, consultas,
   entrega, documentación, criterios de evaluación.
8. Detectar riesgos, multas, penalidades, certificaciones especiales y
   contradicciones.
9. Preparar checklist documental (RUPE, DGI, BPS, poderes, certificados,
   catálogos, fichas técnicas, garantías, seguros).
10. Recomendar productos y alternativas equivalentes.
11. Elaborar borrador de oferta técnica y administrativa.
12. Buscar antecedentes y adjudicaciones similares.
13. Estimar probabilidad de éxito.
14. Generar cronograma de tareas.
15. Clasificar la oportunidad (★★★★★ Excelente … ★ No presentarse).

Nunca inventes información. Si falta un dato, indicá exactamente qué falta
y dónde obtenerlo.

## Mapeo paso → módulo

| Paso | Módulo / archivo | Automatizado hoy |
|---|---|---|
| 1. Revisar diariamente | `monitor.py` + `.github/workflows/monitor.yml` (cron 3x/día) | Sí |
| 2. Aclaraciones/modificaciones | `monitor.py` (hash de título+descripción contra `data/licitaciones_vistas.json`) | Sí, para cambios de título/descripción. Adjudicaciones publicadas como releases OCDS nuevos requieren revisión manual del release completo — el feed OCDS no siempre distingue el `tag` del release en este pipeline. |
| 3. Descargar documentación | `parser.py` (`extraer_pliego`) | Sí, para links directos a PDF/Word/Excel/imagen encontrados en la página del llamado |
| 4. Leer íntegramente el pliego | `parser.py` + `analyzer.py` | Sí (texto completo, no solo primeras páginas, salvo el límite `max_paginas`/`max_documentos` configurable) |
| 5. Identificar productos aunque el título no los mencione | `analyzer.identificar_productos()` | Sí, basado en `knowledge/keywords.yaml`. Casos no cubiertos por keywords requieren revisión manual (ver `prompts/identificacion_productos.md`) |
| 6. Resumen ejecutivo | `analyzer.generar_resumen_ejecutivo()` | Sí — con `ANTHROPIC_API_KEY`: resumen narrativo vía Claude. Sin la key: resumen extractivo básico por reglas |
| 7. Extraer campos clave | `analyzer.extraer_campos_clave()` | Parcial: fechas, organismo, número, garantías por regex. Lo que no se encuentra se lista explícitamente en `campos.faltantes` |
| 8. Riesgos | `risk.py` | Sí, heurístico. Complementar con `prompts/deteccion_riesgos.md` para lectura manual |
| 9. Checklist documental | `checklist.py` | Sí, contrasta contra el texto del pliego |
| 10. Productos y alternativas equivalentes | `pricing.sugerir_productos_equivalentes()` + `knowledge/productos.yaml` | Parcial — requiere que `equivalencias_recomendadas` esté completo |
| 11. Borrador de oferta técnica/administrativa | `templates/oferta_tecnica.md`, `templates/oferta_administrativa.md` | Plantilla — redacción final es manual (o asistida por Claude Code con `prompts/borrador_oferta_tecnica.md`) |
| 12. Antecedentes y adjudicaciones similares | — | **Manual.** El sistema no tiene acceso a un histórico propio de adjudicaciones; buscar en comprasestatales.gub.uy por organismo/rubro |
| 13. Probabilidad de éxito | `analyzer.estimar_probabilidad_exito()` | Sí, score 0-100 auditable (ver razones en el informe) |
| 14. Cronograma de tareas | `report.generar_cronograma()` | Sí |
| 15. Clasificación ★ | `report.clasificar_oportunidad()` | Sí, umbrales configurables en `config/settings.umbral_estrellas()` |

## Regla transversal: nunca inventar información

Todos los módulos siguen la misma convención: un dato no encontrado se
reporta como tal (`None`, lista vacía, o string `"PENDIENTE: ..."`), nunca
se completa con un valor supuesto. `pricing.py` lleva esto al extremo: si
un producto no tiene precio cargado en `knowledge/precios.yaml`, la
cotización se marca como incompleta en vez de estimar un número.
