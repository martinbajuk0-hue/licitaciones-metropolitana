"""Análisis del pliego (pasos 5-7 y 12-13 del flujo).

- extraer_campos_clave: organismo, número, fechas, garantías, visitas,
  consultas, entrega, documentación, criterios de evaluación — todo por
  reglas (regex), funciona siempre, sin dependencias externas.
- identificar_productos: cruza el texto contra knowledge/keywords.yaml y
  knowledge/productos.yaml, incluso si el título no menciona nada de
  Metropolitana (regla del rol).
- generar_resumen_ejecutivo: si hay ANTHROPIC_API_KEY configurada, pide un
  resumen ejecutivo real a Claude usando prompts/resumen_ejecutivo.md como
  system prompt. Si no hay API key, arma un resumen extractivo simple a
  partir de los campos ya detectados por reglas, dejando explícito que es
  un resumen automático básico y no un análisis narrativo.
- estimar_probabilidad_exito: score heurístico 0-100 combinando fuerza de
  match de productos, riesgos detectados y prioridad del organismo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

import config.settings as settings

_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


@dataclass
class CamposClave:
    organismo: str | None = None
    numero_licitacion: str | None = None
    fecha_apertura: str | None = None
    fecha_entrega: str | None = None
    fecha_consultas: str | None = None
    fecha_visita: str | None = None
    garantia_mantenimiento_oferta: str | None = None
    garantia_fiel_cumplimiento: str | None = None
    criterios_evaluacion: list[str] = field(default_factory=list)
    faltantes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "organismo": self.organismo,
            "numero_licitacion": self.numero_licitacion,
            "fecha_apertura": self.fecha_apertura,
            "fecha_entrega": self.fecha_entrega,
            "fecha_consultas": self.fecha_consultas,
            "fecha_visita": self.fecha_visita,
            "garantia_mantenimiento_oferta": self.garantia_mantenimiento_oferta,
            "garantia_fiel_cumplimiento": self.garantia_fiel_cumplimiento,
            "criterios_evaluacion": self.criterios_evaluacion,
        }
        d["faltantes"] = self.faltantes
        return d


@dataclass
class ProductoIdentificado:
    categoria: str
    termino_encontrado: str
    fragmento: str

    def to_dict(self) -> dict:
        return {"categoria": self.categoria, "termino_encontrado": self.termino_encontrado, "fragmento": self.fragmento}


# ─── Campos clave ─────────────────────────────────────────────────────

_PATRON_FECHA_TEXTUAL = re.compile(
    r"(\d{1,2})\s+de\s+(" + "|".join(_MESES) + r")\s+(?:de\s+)?(\d{4})", re.IGNORECASE
)
_PATRON_FECHA_NUMERICA = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")


def _normalizar_fecha(match: re.Match) -> str:
    grupos = match.groups()
    if len(grupos) == 3 and grupos[1].lower() in _MESES:
        dia, mes_txt, anio = grupos
        return f"{int(anio):04d}-{_MESES[mes_txt.lower()]:02d}-{int(dia):02d}"
    dia, mes, anio = grupos
    return f"{int(anio):04d}-{int(mes):02d}-{int(dia):02d}"


_PATRON_PLAZO_DIAS = re.compile(r"\d{1,3}\s*d[ií]as(?:\s+(?:corridos|h[áa]biles))?", re.IGNORECASE)


def _ventana_por_lineas(texto: str, inicio: int, max_lineas: int = 1, max_chars: int = 250) -> str:
    """Ventana de búsqueda acotada, por defecto a la línea actual desde
    `inicio`.

    Evita que la búsqueda de un dato "se cuele" hacia el valor de la
    siguiente etiqueta del pliego (ej. que "plazo de entrega" termine
    matcheando la fecha de "consultas hasta" que viene en la línea de
    abajo). Preferimos no encontrar el dato (queda como faltante,
    explícito) antes que devolver uno incorrecto tomado de otro campo.
    """
    fin = min(len(texto), inicio + max_chars)
    trozo = texto[inicio:fin]
    lineas = trozo.split("\n")
    return "\n".join(lineas[:max_lineas])


def _buscar_fecha_cerca_de(texto: str, patrones_contexto: list[str]) -> str | None:
    for patron_ctx in patrones_contexto:
        for m in re.finditer(patron_ctx, texto, re.IGNORECASE):
            ventana = _ventana_por_lineas(texto, m.end())
            fm = _PATRON_FECHA_TEXTUAL.search(ventana) or _PATRON_FECHA_NUMERICA.search(ventana)
            if fm:
                return _normalizar_fecha(fm)
    return None


def _buscar_plazo_entrega(texto: str) -> str | None:
    """El plazo de entrega en los pliegos uruguayos suele ser una fecha
    fija ("entrega antes del 20/08/2026") o un plazo relativo ("30 días
    corridos desde la orden de compra"). Probamos ambos; nunca inventamos
    una fecha absoluta a partir de un plazo relativo.
    """
    for patron_ctx in [r"plazo\s+de\s+entrega", r"fecha\s+de\s+entrega"]:
        for m in re.finditer(patron_ctx, texto, re.IGNORECASE):
            ventana = _ventana_por_lineas(texto, m.end())
            fm = _PATRON_FECHA_TEXTUAL.search(ventana) or _PATRON_FECHA_NUMERICA.search(ventana)
            if fm:
                return _normalizar_fecha(fm)
            dm = _PATRON_PLAZO_DIAS.search(ventana)
            if dm:
                return f"{dm.group(0)} (plazo relativo — no es una fecha fija, calcular desde la orden de compra/notificación)"
    return None


def _buscar_organismo(texto: str) -> str | None:
    orgs = settings.organismos()
    todos = (
        orgs.get("intendencias", [])
        + orgs.get("ministerios", [])
        + orgs.get("empresas_publicas_y_entes_autonomos", [])
        + orgs.get("educacion", [])
        + orgs.get("salud", [])
    )
    for org in todos:
        # usar solo la parte antes de "(" o "-" para matchear el pliego real
        nombre_corto = re.split(r"[-(]", org)[0].strip()
        if nombre_corto.lower() in texto.lower():
            return org

    m = re.search(r"municipio\s+de\s+([a-záéíóúñ\s]{3,40})", texto, re.IGNORECASE)
    if m:
        return f"Municipio de {m.group(1).strip().title()}"

    sin = settings.sinonimos().get("organismos", {})
    for sigla, nombre_completo in sin.items():
        if re.search(rf"\b{sigla}\b", texto):
            return nombre_completo

    return None


def _buscar_numero_licitacion(texto: str) -> str | None:
    patrones = [
        r"licitaci[óo]n\s+(?:abreviada|p[úu]blica)?\s*(?:n[°ºo]?\.?\s*)?(\d{1,6}[/-]\d{2,4})",
        r"expediente\s+(?:n[°ºo]?\.?\s*)?([\w./-]{4,20})",
        r"compra\s+(?:n[°ºo]?\.?\s*)?(\d{1,6}[/-]\d{2,4})",
    ]
    for patron in patrones:
        m = re.search(patron, texto, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _buscar_garantia(texto: str, patron_ctx: str) -> str | None:
    # Hasta 40 caracteres de texto libre entre la etiqueta y el porcentaje,
    # para tolerar variantes como "garantía de fiel cumplimiento DE CONTRATO: 5%"
    # sin cruzar a la línea siguiente (evita capturar el % de otro campo).
    m = re.search(patron_ctx + r"[^%\n]{0,40}?(\d+(?:[.,]\d+)?)\s*%", texto, re.IGNORECASE)
    if m:
        return f"{m.group(1)}%"
    return None


def _buscar_criterios_evaluacion(texto: str) -> list[str]:
    m = re.search(r"criterios?\s+de\s+evaluaci[óo]n(.{0,900})", texto, re.IGNORECASE | re.DOTALL)
    if not m:
        return []
    bloque = m.group(1)
    # Los criterios suelen terminar en el primer párrafo en blanco; lo que
    # sigue después normalmente es otro requisito del pliego, no un criterio
    # más (evita mezclar párrafos no relacionados en la lista).
    corte = re.search(r"\n[ \t]*\n", bloque)
    if corte:
        bloque = bloque[: corte.start()]
    items = re.split(r"\n|;|(?=\d\s*[.)-])", bloque)
    return [i.strip(" .-\t") for i in items if len(i.strip()) > 8][:8]


def extraer_campos_clave(texto: str) -> CamposClave:
    campos = CamposClave()
    campos.organismo = _buscar_organismo(texto)
    campos.numero_licitacion = _buscar_numero_licitacion(texto)
    campos.fecha_apertura = _buscar_fecha_cerca_de(texto, [r"fecha\s+de\s+apertura", r"apertura\s+de\s+ofertas"])
    campos.fecha_entrega = _buscar_plazo_entrega(texto)
    campos.fecha_consultas = _buscar_fecha_cerca_de(texto, [r"consultas\s+hasta", r"plazo\s+(?:para|de)\s+consultas"])
    campos.fecha_visita = _buscar_fecha_cerca_de(texto, [r"visita\s+(?:de\s+)?obra", r"visita\s+previa"])
    campos.garantia_mantenimiento_oferta = _buscar_garantia(texto, r"garant[íi]a\s+de\s+mantenimiento\s+de\s+oferta")
    campos.garantia_fiel_cumplimiento = _buscar_garantia(texto, r"garant[íi]a\s+de\s+fiel\s+cumplimiento")
    campos.criterios_evaluacion = _buscar_criterios_evaluacion(texto)

    for nombre_campo, valor in [
        ("organismo", campos.organismo),
        ("número de licitación/expediente", campos.numero_licitacion),
        ("fecha de apertura", campos.fecha_apertura),
        ("fecha/plazo de entrega", campos.fecha_entrega),
        ("fecha límite de consultas", campos.fecha_consultas),
        ("criterios de evaluación", campos.criterios_evaluacion or None),
    ]:
        if not valor:
            campos.faltantes.append(
                f"{nombre_campo}: no se encontró en el texto analizado. "
                "Verificar manualmente en el pliego original (puede estar en un anexo no descargado, "
                "una imagen escaneada, o usar una redacción no cubierta por los patrones de analyzer.py)."
            )

    return campos


# ─── Identificación de productos ──────────────────────────────────────────

def identificar_productos(texto: str) -> list[ProductoIdentificado]:
    texto_lower = texto.lower()
    encontrados: list[ProductoIdentificado] = []
    vistos = set()

    for categoria, terminos in settings.palabras_clave_por_categoria().items():
        for termino in terminos:
            idx = settings.buscar_palabra_clave(texto_lower, termino)
            if idx == -1:
                continue
            clave = (categoria, termino.lower())
            if clave in vistos:
                continue
            vistos.add(clave)
            inicio = max(0, idx - 60)
            fin = min(len(texto), idx + len(termino) + 60)
            encontrados.append(
                ProductoIdentificado(
                    categoria=categoria,
                    termino_encontrado=termino,
                    fragmento=texto[inicio:fin].replace("\n", " ").strip(),
                )
            )
    return encontrados


def identificar_contexto(texto: str) -> dict[str, list[str]]:
    """lugares_uso / aplicaciones detectados en el texto — señal DÉBIL,
    nunca decide relevancia por sí sola (ver knowledge/keywords.yaml).
    Se usa solo para enriquecer el informe cuando ya hubo un match fuerte
    (identificar_productos no vacío).
    """
    texto_lower = texto.lower()
    contexto: dict[str, list[str]] = {}
    for grupo, terminos in settings.palabras_clave_contexto().items():
        encontrados = sorted({
            t for t in terminos if settings.coincide_palabra_clave(texto_lower, t)
        })
        if encontrados:
            contexto[grupo] = encontrados[:15]
    return contexto


# ─── Resumen ejecutivo ─────────────────────────────────────────────────────

def _resumen_extractivo(texto: str, campos: CamposClave, productos: list[ProductoIdentificado]) -> str:
    categorias = sorted({settings.etiqueta_categoria(p.categoria) for p in productos})
    organismo = campos.organismo or "organismo no identificado"
    categorias_txt = ", ".join(categorias) if categorias else "ninguna coincidencia directa de categoría"
    lineas = [
        # Línea "QUÉ ES:" con el mismo formato que generar_resumen_ejecutivo()
        # le pide a Claude (ver prompts/resumen_ejecutivo.md) — así
        # extraer_que_es() funciona igual tenga o no ANTHROPIC_API_KEY
        # configurada, sin que monitor.py tenga que distinguir el origen.
        f"QUÉ ES: Licitación de {organismo} — categorías de producto detectadas: {categorias_txt}.",
        "",
        f"Organismo: {campos.organismo or 'no identificado — verificar manualmente'}.",
        f"Número: {campos.numero_licitacion or 'no identificado — verificar manualmente'}.",
        f"Fecha de apertura: {campos.fecha_apertura or 'no identificada — verificar manualmente'}.",
        f"Categorías de producto detectadas: {categorias_txt}.",
        "Resumen generado por reglas (sin ANTHROPIC_API_KEY configurada): "
        "es un extracto de campos, no un análisis narrativo completo del pliego.",
    ]
    return "\n".join(lineas)


def extraer_que_es(resumen: str) -> str:
    """Extrae la línea "QUÉ ES: ..." del resumen ejecutivo (ver
    prompts/resumen_ejecutivo.md y _resumen_extractivo() más arriba) para
    usarla como resumen corto en los emails de monitor.py y
    revisar_resultados.py — pedido del usuario 2026-08-24: "un pequeño
    resumen contándome de qué es cada licitación", para poder decidir si
    vale la pena abrir el pliego sin tener que leerlo primero.

    Si el resumen no trae esa línea en el formato esperado (por ejemplo,
    una respuesta de Claude que no respetó el prompt), se cae a recortar
    el resumen completo a 220 caracteres en vez de dejar el campo vacío.
    """
    for linea in resumen.splitlines():
        linea = linea.strip()
        if linea.upper().startswith(("QUÉ ES:", "QUE ES:")):
            texto = linea.split(":", 1)[1].strip()
            if texto:
                return texto
    texto_plano = " ".join(resumen.split())
    if len(texto_plano) <= 220:
        return texto_plano
    return texto_plano[:220].rstrip() + "…"


def generar_resumen_ejecutivo(texto: str, campos: CamposClave, productos: list[ProductoIdentificado]) -> str:
    api_key = settings.anthropic_api_key()
    if not api_key:
        return _resumen_extractivo(texto, campos, productos)

    try:
        import anthropic
    except ImportError:
        return _resumen_extractivo(texto, campos, productos) + (
            "\n\n(ANTHROPIC_API_KEY está configurada pero falta instalar el paquete 'anthropic': "
            "pip install anthropic"
        )

    prompt_path = settings.PROMPTS_DIR / "resumen_ejecutivo.md"
    system_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else (
        "Actúa como el Departamento de Licitaciones de Metropolitana Pisos. "
        "Generá un resumen ejecutivo claro y accionable del siguiente pliego."
    )

    client = anthropic.Anthropic(api_key=api_key)
    texto_recortado = texto[:15000]
    respuesta = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1200,
        system=system_prompt,
        messages=[{"role": "user", "content": f"Texto del pliego:\n\n{texto_recortado}"}],
    )
    return "".join(block.text for block in respuesta.content if hasattr(block, "text"))


# ─── Probabilidad de éxito ──────────────────────────────────────────────────

def estimar_probabilidad_exito(
    campos: CamposClave,
    productos: list[ProductoIdentificado],
    riesgos_altos: int,
    riesgos_medios: int,
    items_checklist_faltantes: int,
) -> dict:
    score = 0
    razones = []

    n_categorias = len({p.categoria for p in productos})
    aporte_productos = min(40, n_categorias * 12)
    score += aporte_productos
    razones.append(f"+{aporte_productos} por {n_categorias} categoría(s) de producto identificadas")

    if campos.organismo:
        score += 15
        razones.append("+15 por organismo identificado (prioritario según el rol)")

    faltantes = len(campos.faltantes)
    penal_faltantes = min(20, faltantes * 4)
    score -= penal_faltantes
    if penal_faltantes:
        razones.append(f"-{penal_faltantes} por {faltantes} campo(s) clave no identificados (a verificar manualmente)")

    penal_riesgo_alto = min(30, riesgos_altos * 10)
    score -= penal_riesgo_alto
    if penal_riesgo_alto:
        razones.append(f"-{penal_riesgo_alto} por {riesgos_altos} riesgo(s) de severidad alta")

    penal_riesgo_medio = min(15, riesgos_medios * 3)
    score -= penal_riesgo_medio
    if penal_riesgo_medio:
        razones.append(f"-{penal_riesgo_medio} por {riesgos_medios} riesgo(s) de severidad media")

    penal_checklist = min(20, items_checklist_faltantes * 2)
    score -= penal_checklist
    if penal_checklist:
        razones.append(f"-{penal_checklist} por {items_checklist_faltantes} ítem(s) documentales a verificar")

    score = max(0, min(100, score + 30))  # piso base de 30 si hay al menos un producto identificado
    if n_categorias == 0:
        score = max(0, score - 30)
        razones.append("-30 adicional: ninguna categoría de producto Metropolitana identificada en el texto analizado")

    return {"score": score, "razones": razones}
