# Prompt: Identificación de productos Metropolitana en un pliego

Complementa `analyzer.identificar_productos()`, que solo hace matching de
substring contra `knowledge/keywords.yaml`. Para los casos donde el pliego
usa una redacción no cubierta por esa lista.

---

Leé el objeto de la compra y las especificaciones técnicas del pliego
completo. Preguntate, aunque el título no lo diga:

- ¿Hay una obra civil, remodelación, refacción o acondicionamiento que
  probablemente incluya piso, revestimiento de pared, césped o alfombra
  aunque no se detalle en el título del llamado?
- ¿El organismo es un tipo de organización que típicamente compra estos
  productos (escuela, hospital, gimnasio, plaza, oficina pública, cancha)?
- ¿Alguna palabra genérica del pliego ("solado", "pavimento",
  "recubrimiento de suelo", "superficie deportiva") podría estar
  describiendo un producto de Metropolitana con otro nombre?

Si encontrás una coincidencia que `knowledge/keywords.yaml` no cubre,
agregala ahí (es la forma correcta de que el sistema la detecte
automáticamente la próxima vez) y anotá también el término nuevo en
`knowledge/sinonimos.yaml` si es una variante de un producto ya existente.

Nunca descartes una licitación solamente por el título.
