# Agentes especializados

Este documento define agentes especializados que mapean 1:1 con los
módulos del pipeline (ver `docs/ARQUITECTURA.md`). Sirven como guía tanto
para invocar subagentes de Claude Code sobre una etapa puntual, como para
que cualquier persona/LLM entienda el contrato de entrada/salida de cada
etapa sin tener que leer el código.

Cada agente tiene: objetivo, entradas, salidas, módulo que implementa la
parte determinística, y el prompt de referencia para la parte que requiere
criterio (no toda la lógica es automatizable con reglas — ver
`docs/FLUJO_DE_TRABAJO.md`, columna "Automatizado hoy").

---

## Agente Rastreador (monitoreo)

- **Objetivo:** detectar licitaciones nuevas y cambios (aclaraciones,
  modificaciones) en Compras Estatales (ARCE), pasos 1-2 del flujo.
- **Entrada:** ninguna (corre por cron) o invocación manual.
- **Salida:** lista de licitaciones nuevas/modificadas relevantes, con
  keyword y fuente de la coincidencia.
- **Módulo:** `monitor.py`.
- **Config que usa:** `knowledge/keywords.yaml`, `data/licitaciones_vistas.json`.

## Agente Lector de Pliegos

- **Objetivo:** convertir toda la documentación de una licitación (pliego
  principal + anexos, en PDF/Word/Excel/imagen) en texto plano, sin
  perder ningún documento en silencio. Pasos 3-4.
- **Entrada:** URL de la licitación o archivo local.
- **Salida:** texto completo concatenado + lista de documentos que no se
  pudieron leer (y por qué).
- **Módulo:** `parser.py`.
- **Limitación conocida:** formatos `.doc`/`.xls` legados no se leen
  directamente (hay que convertir a `.docx`/`.xlsx`/PDF); OCR de imágenes
  requiere Tesseract instalado en el sistema.

## Agente Analista

- **Objetivo:** extraer campos estructurados, identificar productos
  Metropolitana (aunque el título no los mencione), generar el resumen
  ejecutivo y estimar la probabilidad de éxito. Pasos 5-7, 12-13.
- **Entrada:** texto completo del pliego (del Agente Lector de Pliegos).
- **Salida:** `CamposClave` (organismo, número, fechas, garantías,
  criterios de evaluación, faltantes explícitos), lista de
  `ProductoIdentificado`, resumen ejecutivo, score 0-100 con razones.
- **Módulo:** `analyzer.py`.
- **Prompt de referencia (para la parte no cubierta por regex):**
  `prompts/resumen_ejecutivo.md`, `prompts/identificacion_productos.md`.
- **Capacidad opcional:** resumen narrativo vía Claude si hay
  `ANTHROPIC_API_KEY`; si no, resumen extractivo por reglas.

## Agente de Riesgos

- **Objetivo:** detectar multas, penalidades, plazos ajustados,
  certificaciones especiales exigidas y contradicciones internas del
  pliego. Paso 8.
- **Entrada:** texto completo del pliego.
- **Salida:** lista de `Riesgo` (categoría, severidad, descripción,
  fragmento textual de evidencia).
- **Módulo:** `risk.py`.
- **Prompt de referencia:** `prompts/deteccion_riesgos.md` (para
  complementar manualmente lo que las reglas no capturan).

## Agente de Checklist Documental

- **Objetivo:** determinar qué documentación exige explícitamente el
  pliego (RUPE, DGI, BPS, poderes, certificados, catálogos, fichas
  técnicas, garantías, seguros) y qué ítems estándar no se mencionan y
  hay que verificar igual. Paso 9.
- **Entrada:** texto completo del pliego.
- **Salida:** lista de `ItemChecklist` con estado y evidencia.
- **Módulo:** `checklist.py`.
- **Prompt de referencia:** `prompts/checklist_documental.md`.

## Agente de Cotización

- **Objetivo:** recomendar productos equivalentes y armar un borrador de
  presupuesto. Paso 10.
- **Entrada:** especificación del pliego (texto libre) o lista de
  `(producto_id, cantidad)`.
- **Salida:** sugerencias de `knowledge/productos.yaml` →
  `equivalencias_recomendadas`; cotización detallada con subtotal, margen,
  IVA y total — o ítems marcados `SIN PRECIO CARGADO` si
  `knowledge/precios.yaml` no tiene el dato.
- **Módulo:** `pricing.py`.
- **Regla dura:** nunca estima un precio no cargado.

## Agente de Informe

- **Objetivo:** orquestar a todos los agentes anteriores y producir el
  documento final: resumen ejecutivo, datos clave, productos, riesgos,
  checklist, cronograma y clasificación ★. Pasos 6, 9, 14, 15.
- **Entrada:** título, URL, texto del pliego.
- **Salida:** informe en Markdown (`reports/<fecha>-<slug>.md`).
- **Módulo:** `report.py`.
- **Prompt de referencia:** `prompts/clasificacion_oportunidad.md`.

## Agente de Oferta (borrador)

- **Objetivo:** redactar el borrador de oferta técnica y administrativa a
  partir del informe ya generado. Paso 11.
- **Entrada:** informe de `report.py` + `knowledge/productos.yaml` +
  `config/empresa.yaml`.
- **Salida:** documento completado a partir de `templates/oferta_tecnica.md`
  y `templates/oferta_administrativa.md`.
- **Módulo:** sin automatizar por reglas (requiere criterio) — usar
  `prompts/borrador_oferta_tecnica.md` con una sesión de Claude Code.

## Agente de Antecedentes (manual)

- **Objetivo:** buscar adjudicaciones y antecedentes similares en
  comprasestatales.gub.uy para estimar competencia y precios de mercado.
  Paso 12.
- **Estado:** no automatizado — el sistema no tiene acceso a un histórico
  propio de adjudicaciones de Metropolitana. Requiere búsqueda manual
  (o una sesión de Claude Code con acceso a WebFetch/WebSearch) por
  organismo y rubro.

---

## Cómo se invoca esto en la práctica

`cli.py analizar` corre en secuencia: Agente Lector de Pliegos → Agente
Analista → Agente de Riesgos → Agente de Checklist Documental → Agente de
Informe. Los agentes de Cotización, Oferta y Antecedentes se invocan por
separado, sobre un informe ya generado, porque requieren decisiones
comerciales que no deberían disparar automáticamente en cada corrida del
cron.
