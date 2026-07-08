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
import risk as risk_mod

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


def generar_informe_markdown(
    titulo: str,
    url: str,
    texto_pliego: str,
    documentos_con_error: list[str] | None = None,
) -> str:
    campos = analyzer.extraer_campos_clave(texto_pliego)
    productos = analyzer.identificar_productos(texto_pliego)
    riesgos = risk_mod.analizar_riesgos(texto_pliego)
    items_checklist = checklist_mod.generar_checklist(texto_pliego)
    pendientes_checklist = checklist_mod.items_pendientes_de_verificar(items_checklist)
    resumen = analyzer.generar_resumen_ejecutivo(texto_pliego, campos, productos)

    riesgos_altos = [r for r in riesgos if r.severidad.value == "alta"]
    riesgos_medios = [r for r in riesgos if r.severidad.value == "media"]

    probabilidad = analyzer.estimar_probabilidad_exito(
        campos, productos, len(riesgos_altos), len(riesgos_medios), len(pendientes_checklist)
    )
    clasificacion = clasificar_oportunidad(probabilidad["score"])
    cronograma = generar_cronograma(campos)

    categorias_detectadas = sorted({p.categoria for p in productos})

    partes = [
        f"# Informe de licitación: {titulo}",
        "",
        f"**URL:** {url}" if url else "",
        f"**Generado:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
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
        f"- Fecha de apertura: {campos.fecha_apertura or '**NO IDENTIFICADA — verificar manualmente**'}",
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
        _md_lista([f"**{p.categoria}** (\"{p.termino_encontrado}\"): ...{p.fragmento}..." for p in productos[:25]]),
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
    return "\n".join(p for p in partes if p is not None)


def guardar_informe(titulo: str, contenido_md: str) -> str:
    import re as _re

    slug = _re.sub(r"[^a-z0-9]+", "-", titulo.lower()).strip("-")[:80] or "licitacion"
    fecha = datetime.now().strftime("%Y%m%d-%H%M%S")
    ruta = settings.REPORTS_DIR / f"{fecha}-{slug}.md"
    ruta.write_text(contenido_md, encoding="utf-8")
    return str(ruta)
