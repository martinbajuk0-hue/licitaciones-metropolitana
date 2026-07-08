# Prompt / criterio: Clasificación de la oportunidad

`report.clasificar_oportunidad()` calcula esto con una fórmula numérica
auditable (ver `analyzer.estimar_probabilidad_exito` y
`config/settings.umbral_estrellas`). Este documento explica el criterio en
palabras, para cuando una persona quiera clasificar a mano o ajustar los
umbrales.

| Nivel | Símbolo | Cuándo usarlo |
|---|---|---|
| 5 | ★★★★★ Excelente | Productos Metropolitana claramente aplicables, organismo prioritario, sin riesgos altos, documentación estándar. |
| 4 | ★★★★ Buena | Productos aplicables con algún ajuste, riesgos manejables, falta poca información. |
| 3 | ★★★ Dudosa | Aplicación parcial o indirecta de productos, riesgos medios relevantes, o información clave faltante que puede cambiar la evaluación. |
| 2 | ★★ Poco conveniente | Match débil de producto, riesgos altos, plazos o garantías desproporcionados. |
| 1 | ★ No presentarse | Sin relación real con productos Metropolitana, o riesgo/costo de participar claramente mayor al beneficio. |

Reglas:
- La clasificación automática es un punto de partida, no la decisión
  final. Un ★★★ con un dato crítico faltante puede subir a ★★★★ apenas se
  consigue ese dato — o bajar a ★★ si el dato es desfavorable.
- Documentar siempre el motivo del puntaje (el sistema ya lo hace en la
  sección "Por qué este puntaje" del informe).
