# Prompt: Borrador de oferta técnica

Usar junto con `templates/oferta_tecnica.md`.

---

Con base en el informe generado por `report.py` para esta licitación,
redactá un borrador de oferta técnica que:

1. Responda punto por punto las especificaciones técnicas del pliego, en
   el mismo orden en que aparecen (facilita la evaluación del organismo).
2. Para cada especificación, indique el producto Metropolitana propuesto
   (usar `knowledge/productos.yaml` y, si aplica,
   `pricing.sugerir_productos_equivalentes()`), con su ficha técnica
   adjunta.
3. Marque explícitamente cualquier especificación que Metropolitana no
   pueda cumplir tal cual está redactada, y proponga una alternativa
   equivalente con su justificación técnica — nunca omitir un punto del
   pliego en silencio.
4. Incluya plazo de entrega e instalación ofertado, coherente con el
   cronograma generado por `report.generar_cronograma()`.
5. Cite antecedentes de obras similares si están disponibles (paso 12 del
   flujo — hoy es responsabilidad del equipo comercial cargar antecedentes,
   el sistema no los infiere).

No completar campos económicos acá — esos van en la oferta administrativa
/ planilla de cotización (`pricing.py` + `templates/oferta_administrativa.md`).
