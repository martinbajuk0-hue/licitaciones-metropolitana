# Prompt maestro: análisis integral de un pliego

Este es el prompt "orquestador": lo que debe hacer cualquier sesión de
Claude Code (o persona) que reciba un pliego nuevo, en el mismo orden que
sigue el pipeline automático (`parser.py` → `analyzer.py` → `risk.py` →
`checklist.py` → `report.py`).

---

1. Asegurate de tener **todo** el pliego y sus anexos, no solo el
   documento principal (`parser.extraer_pliego`).
2. Leé el pliego completo — no solo el título ni el índice
   (`analyzer.extraer_campos_clave` + `analyzer.identificar_productos`).
3. Identificá productos Metropolitana aunque el título no los mencione
   (ver `prompts/identificacion_productos.md`).
4. Extraé organismo, número, fechas, garantías, criterios de evaluación.
5. Detectá riesgos, multas, certificaciones especiales y contradicciones
   (ver `prompts/deteccion_riesgos.md`).
6. Generá el checklist documental (ver `prompts/checklist_documental.md`).
7. Recomendá productos y alternativas equivalentes (`pricing.py`).
8. Armá el resumen ejecutivo (`prompts/resumen_ejecutivo.md`).
9. Buscá antecedentes y adjudicaciones similares — **paso manual**: el
   sistema no tiene acceso a un historial de adjudicaciones propio; buscar
   en comprasestatales.gub.uy por organismo/rubro y documentar lo que se
   encuentre.
10. Estimá probabilidad de éxito (`analyzer.estimar_probabilidad_exito`).
11. Generá el cronograma de tareas (`report.generar_cronograma`).
12. Clasificá la oportunidad ★ (`report.clasificar_oportunidad`,
    ver `prompts/clasificacion_oportunidad.md`).
13. Si corresponde presentarse, avanzar con
    `prompts/borrador_oferta_tecnica.md` y `templates/oferta_administrativa.md`.

Regla transversal: **nunca inventar información**. Todo dato no encontrado
se declara explícitamente como faltante, con indicación de dónde debería
buscarse (pliego, anexo, consulta al organismo, o dato interno de
Metropolitana como precios/certificaciones).
