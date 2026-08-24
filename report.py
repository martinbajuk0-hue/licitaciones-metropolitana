"""Genera el informe ejecutivo final de una licitación (pasos 6, 9, 14 y 15
del flujo): resumen ejecutivo, checklist, riesgos, cronograma de tareas y
clasificación por estrellas. Es el módulo que junta el trabajo de
parser.py, analyzer.py, risk.py, checklist.py y pricing.py en un único
documento Markdown legible por una persona.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import analyzer
import checklist as checklist_mod
import config.settings as settings
import historial
import risk as risk_mod

_ETIQUETA_CONTEXTO = {
    "lugares_uso": "Lugar de uso mencionado",
    "aplicaciones": "Aplicación mencionada",
}

_ESTRELLAS = {
    5: ("★★★★★", "Excelente"),
    4: ("★★★★", "Buena"),
    3: ("★★★", "Dudosa"),
    2: ("★★", "Poco conveniente"),
    1: ("★", "No presentarse"),
}


@dataclass
class Clasificacion:
    puntaje: int
    nivel: int
    simbolo: str
    etiqueta: str


def clasificar_oportunidad(score: int) -> Clasificacion:
    umbrales = settings.umbral_estrellas()
    if score >= umbrales[5]:
        nivel = 5
    elif score >= umbrales[4]:
        nivel = 4
    elif score >= umbrales[3]:
        nivel = 3
    elif score >= umbrales[2]:
        nivel = 2
    else:
        nivel = 1
    simbolo, etiqueta = _ESTRELLAS[nivel]
    return Clasificacion(puntaje=score, nivel=nivel, simbolo=simbolo, etiqueta=etiqueta)


def texto_cierre(fecha_apertura: str | None, hoy: date | None = None) -> str:
    """"Cierra en N días" / "Cierra hoy" / "Cierra mañana" — el formato que
    usa Simple Compras Públicas en sus avisos (ver Ejemplo_Alerta_Email_
    Metropolitana.png, reunión del 14/08/2026) porque se lee mucho más
    rápido que una fecha ISO suelta al decidir qué llamados revisar primero.

    fecha_apertura ya viene normalizada a 'YYYY-MM-DD' por
    analyzer._normalizar_fecha(). Si no se identificó o no se puede
    parsear, se dice explícitamente en vez de mostrar un número confuso.
    """
    if not fecha_apertura:
        return "Fecha de cierre no identificada — verificar manualmente"
    hoy = hoy or date.today()
    try:
        fecha = date.fromisoformat(fecha_apertura)
    except ValueError:
        return "Fecha de cierre no identificada — verificar manualmente"
    dias = (fecha - hoy).days
    if dias < 0:
        return f"Cierre {fecha_apertura} (ya pasó — verificar si sigue vigente)"
    if dias == 0:
        return "Cierra hoy"
    if dias == 1:
        return "Cierra mañana"
    return f"Cierra en {dias} días"


def generar_cronograma(campos: analyzer.CamposClave, hoy: date | None = None) -> list[dict]:
    hoy = hoy or date.today()
    tareas = [
        {"tarea": "Lectura integral del pliego y anexos", "cuando": hoy.isoformat()},
        {"tarea": "Armar checklist documental y reunir certificados", "cuando": (hoy + timedelta(days=1)).isoformat()},
    ]

    if campos.fecha_visita:
        tareas.append({"tarea": "Asistir a visita de obra", "cuando": campos.fecha_visita})
    if campos.fecha_consultas:
        tareas.append({"tarea": "Enviar consultas/aclaraciones si corresponde", "cuando": campos.fecha_consultas})

    tareas.append({"tarea": "Definir productos y armar cotización", "cuando": "según disponibilidad, antes de apertura"})
    tareas.append({"tarea": "Redactar oferta técnica y administrativa", "cuando": "según disponibilidad, antes de apertura"})

    if campos.fecha_apertura:
        tareas.append({"tarea": "Entrega de oferta (fecha de apertura)", "cuando": campos.fecha_apertura})
    else:
        tareas.append({"tarea": "Entrega de oferta", "cuando": "FECHA DE APERTURA NO IDENTIFICADA — verificar manualmente antes de planificar"})

    return tareas


def _md_lista(items: list[str]) -> str:
    if not items:
        return "_(ninguno)_\n"
    return "\n".join(f"- {i}" for i in items) + "\n"


@dataclass
class InformeLicitacion:
    """Resultado completo de analizar una licitación: todo lo que calculó
    el pipeline (no solo el Markdown), para que quien orquesta (monitor.py,
    cli.py) pueda usar `clasificacion`, `riesgos`, etc. directamente sin
    tener que recalcularlos por su cuenta ni parsear el Markdown de vuelta.
    """

    titulo: str
    url: str
    campos: analyzer.CamposClave
    productos: list[analyzer.ProductoIdentificado]
    contexto: dict[str, list[str]]
    riesgos: list[risk_mod.Riesgo]
    checklist: list[checklist_mod.ItemChecklist]
    resumen: str
    que_es: str
    probabilidad: dict
    clasificacion: Clasificacion
    cronograma: list[dict]
    ya_adjudicados: list[str]
    cierre: str
    markdown: str


def analizar_licitacion(
    titulo: str,
    url: str,
    texto_pliego: str,
    documentos_con_error: list[str] | None = None,
    codigos_articulo: list[str] | None = None,
) -> InformeLicitacion:
    campos = analyzer.extraer_campos_clave(texto_pliego)
    productos = analyzer.identificar_productos(texto_pliego)
    # lugares_uso/aplicaciones son señal débil (ver knowledge/keywords.yaml):
    # solo se calculan y muestran como contexto si ya hubo un match fuerte.
    contexto = analyzer.identificar_contexto(texto_pliego) if productos else {}
    riesgos = risk_mod.analizar_riesgos(texto_pliego)
    items_checklist = checklist_mod.generar_checklist(texto_pliego)
    pendientes_checklist = checklist_mod.items_pendientes_de_verificar(items_checklist)
    resumen = analyzer.generar_resumen_ejecutivo(texto_pliego, campos, productos)
    # Resumen corto de 1 frase ("qué es esta licitación") para los emails
    # de monitor.py/revisar_resultados.py — ver analyzer.extraer_que_es()
    # y prompts/resumen_ejecutivo.md. Pedido del usuario 2026-08-24.
    que_es = analyzer.extraer_que_es(resumen)

    riesgos_altos = [r for r in riesgos if r.severidad.value == "alta"]
    riesgos_medios = [r for r in riesgos if r.severidad.value == "media"]

    probabilidad = analyzer.estimar_probabilidad_exito(
        campos, productos, len(riesgos_altos), len(riesgos_medios), len(pendientes_checklist)
    )

    # Match por código de artículo (classification.id de OCDS) contra el
    # historial — señal EXACTA (no por texto), ver historial.
    # productos_por_codigo_ya_adjudicado(). Cuando hay match, se suma un
    # bonus fuerte al score: es la certeza más alta posible de que
    # Metropolitana tiene un artículo concreto para ofertar. Pedido
    # explícito del usuario 2026-08-18.
    ya_adjudicados_por_codigo = historial.productos_por_codigo_ya_adjudicado(codigos_articulo or [])
    if ya_adjudicados_por_codigo:
        bonus = 25
        probabilidad["score"] = min(100, probabilidad["score"] + bonus)
        probabilidad["razones"].append(
            f"+{bonus} por código de artículo ARCE ya adjudicado a Metropolitana antes (match exacto, "
            f"no por texto): {', '.join(ya_adjudicados_por_codigo)}"
        )

    clasificacion = clasificar_oportunidad(probabilidad["score"])
    cronograma = generar_cronograma(campos)

    categorias_detectadas = sorted({settings.etiqueta_categoria(p.categoria) for p in productos})

    # "Ya adjudicaste antes" — primer campo que muestra el aviso de Simple
    # Compras Públicas antes que ningún otro análisis (ver historial.py).
    # El match por código va primero (señal más fuerte), deduplicado contra
    # el match por texto.
    ya_adjudicados = list(dict.fromkeys(
        ya_adjudicados_por_codigo + historial.productos_ya_adjudicados([p.termino_encontrado for p in productos])
    ))
    cierre = texto_cierre(campos.fecha_apertura)

    partes = [
        f"# Informe de licitación: {titulo}",
        "",
        f"**URL:** {url}" if url else "",
        f"**Generado:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Qué es:** {que_es}",
        "",
        f"## Clasificación: {clasificacion.simbolo} — {clasificacion.etiqueta} (score {clasificacion.puntaje}/100)",
        "",
        "### Por qué este puntaje",
        _md_lista(probabilidad["razones"]),
        "## Resumen ejecutivo",
        resumen,
        "",
        "## Datos clave",
        f"- Organismo: {campos.organismo or '**NO IDENTIFICADO — verificar manualmente**'}",
        f"- Número de licitación/expediente: {campos.numero_licitacion or '**NO IDENTIFICADO — verificar manualmente**'}",
        f"- Fecha de apertura: {campos.fecha_apertura or '**NO IDENTIFICADA — verificar manualmente**'} ({cierre})",
        f"- Plazo/fecha de entrega: {campos.fecha_entrega or 'no identificado — verificar manualmente'}",
        f"- Fecha límite de consultas: {campos.fecha_consultas or 'no identificada — verificar manualmente'}",
        f"- Fecha de visita de obra: {campos.fecha_visita or 'no identificada / puede no aplicar'}",
        f"- Garantía de mantenimiento de oferta: {campos.garantia_mantenimiento_oferta or 'no identificada — verificar manualmente'}",
        f"- Garantía de fiel cumplimiento: {campos.garantia_fiel_cumplimiento or 'no identificada — verificar manualmente'}",
        "",
        "### Criterios de evaluación detectados",
        _md_lista(campos.criterios_evaluacion),
        "### Datos que faltan y dónde buscarlos",
        _md_lista(campos.faltantes) if campos.faltantes else "_(No se detectaron faltantes en los campos analizados; igual verificar contra el pliego original.)_\n",
        "## Productos Metropolitana identificados",
        f"Categorías detectadas: {', '.join(categorias_detectadas) if categorias_detectadas else 'NINGUNA — revisar el pliego completo manualmente antes de descartar (regla: nunca descartar solo por el título).'}",
        "",
        _md_lista([f"**{settings.etiqueta_categoria(p.categoria)}** (\"{p.termino_encontrado}\"): ...{p.fragmento}..." for p in productos[:25]]),
        "### Ya adjudicaste antes" if ya_adjudicados else None,
        (
            "Metropolitana ya le vendió al Estado alguno de estos productos antes "
            f"(historial 2025-2026, ver knowledge/historial_adjudicaciones_metropolitana.json): {', '.join(ya_adjudicados)}."
            if ya_adjudicados else None
        ),
        "### Contexto adicional (lugar de uso / aplicación)" if contexto else None,
        (
            _md_lista(
                [f"{_ETIQUETA_CONTEXTO.get(grupo, grupo)}: {', '.join(terminos)}" for grupo, terminos in contexto.items()]
            )
            if contexto else None
        ),
        "## Riesgos detectados",
        f"Altos: {len(riesgos_altos)} · Medios: {len(riesgos_medios)} · Total: {len(riesgos)}",
        "",
        _md_lista([f"[{r.severidad.value.upper()}] {r.categoria}: {r.descripcion} — «{r.fragmento}»" for r in riesgos]),
        "## Checklist documental",
        "### Exigidos explícitamente en el pliego",
        _md_lista([f"{i.nombre} — evidencia: «{i.evidencia}»" for i in checklist_mod.items_exigidos(items_checklist)]),
        "### Estándar, no mencionado en el pliego (verificar si igual aplica)",
        _md_lista([i.nombre for i in pendientes_checklist]),
        "## Cronograma de tareas",
        _md_lista([f"{t['cuando']}: {t['tarea']}" for t in cronograma]),
        "## Documentos que no se pudieron leer",
        _md_lista(documentos_con_error or []),
        "---",
        "_Informe generado automáticamente. No sustituye la lectura íntegra del pliego por una persona del equipo de licitaciones. "
        "Todo campo marcado como 'no identificado' o 'PENDIENTE' requiere verificación manual antes de tomar una decisión de presentarse._",
    ]
    markdown = "\n".join(p for p in partes if p is not None)

    return InformeLicitacion(
        titulo=titulo,
        url=url,
        campos=campos,
        productos=productos,
        contexto=contexto,
        riesgos=riesgos,
        checklist=items_checklist,
        resumen=resumen,
        que_es=que_es,
        probabilidad=probabilidad,
        clasificacion=clasificacion,
        cronograma=cronograma,
        ya_adjudicados=ya_adjudicados,
        cierre=cierre,
        markdown=markdown,
    )


def generar_informe_markdown(
    titulo: str,
    url: str,
    texto_pliego: str,
    documentos_con_error: list[str] | None = None,
) -> str:
    """Atajo para cuando solo interesa el Markdown (ej. cli.py). Si además
    se necesita la clasificación/riesgos/etc. para otra cosa (ej. el email
    de monitor.py), usar analizar_licitacion() directamente para no
    recalcular el pipeline dos veces.
    """
    return analizar_licitacion(titulo, url, texto_pliego, documentos_con_error).markdown


def guardar_informe(titulo: str, contenido_md: str) -> str:
    import re as _re

    slug = _re.sub(r"[^a-z0-9]+", "-", titulo.lower()).strip("-")[:80] or "licitacion"
    fecha = datetime.now().strftime("%Y%m%d-%H%M%S")
    ruta = settings.REPORTS_DIR / f"{fecha}-{slug}.md"
    ruta.write_text(contenido_md, encoding="utf-8")
    return str(ruta)
