"""Historial de adjudicaciones de Metropolitana con código de artículo ARCE.

Origen de los datos: revisión manual de las 617 compras adjudicadas a
Metropolitana S.A. entre 2025 y 2026 (comprasestatales.gub.uy), abriendo la
ficha de detalle de cada una para extraer el desglose ítem por ítem —
incluye el "Código de artículo" que ARCE asigna a cada producto/servicio,
el mismo clasificador que usan herramientas de terceros (ej. Simple Compras
Públicas) para armar sus reportes de "mapa de mercado" y "precios de
referencia". Los datos quedaron congelados en
knowledge/historial_adjudicaciones_metropolitana.json — no se vuelven a
recalcular en cada corrida, así que no reflejan adjudicaciones posteriores
a la fecha de generación (ver el campo "generado" del propio JSON).

Este módulo expone lo mínimo para la primera funcionalidad calcada de lo
que hace un servicio de avisos como el de Simple Compras Públicas "en
primera instancia": marcar, para cada llamado nuevo, si Metropolitana ya
le vendió antes al Estado ese mismo tipo de producto — la línea
"Ya adjudicaste antes: X, Y, Z" que aparece primero en sus emails, antes
de cualquier análisis de precios o de mercado (eso queda para una etapa
posterior, ver docs/ARQUITECTURA.md).
"""
from __future__ import annotations

import functools
import json
import re
import unicodedata
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent
HISTORIAL_PATH = _BASE_DIR / "knowledge" / "historial_adjudicaciones_metropolitana.json"


def _normalizar(texto: str) -> str:
    """MAYÚSCULAS, sin acentos, espacios colapsados — para comparar el
    término que encontró analyzer.identificar_productos() en el pliego
    contra el nombre de producto tal como lo escribió ARCE en la ficha de
    la compra histórica (que no sigue ninguna convención fija: a veces es
    el sustantivo solo, "MOQUETTE", a veces con el verbo, "COLOCACION DE
    VINILICOS").
    """
    texto = unicodedata.normalize("NFKD", texto.upper())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip()


@functools.lru_cache(maxsize=1)
def _cargar() -> dict:
    if not HISTORIAL_PATH.exists():
        return {"items_metropolitana": [], "items_otros_proveedores": []}
    with open(HISTORIAL_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@functools.lru_cache(maxsize=1)
def _items_metropolitana_normalizados() -> list[tuple[str, dict]]:
    """(nombre_producto_normalizado, registro original) de cada ítem que
    Metropolitana ya adjudicó — precalculado una vez por proceso, ya que
    se consulta por cada llamado nuevo que pasa el filtro de relevancia.
    """
    return [(_normalizar(item["producto"]), item) for item in _cargar().get("items_metropolitana", []) if item.get("producto")]


def _matchea(termino_normalizado: str, producto_normalizado: str) -> bool:
    """Match conservador por substring en ambos sentidos: un término corto
    del pliego ("VINILICO") debe aparecer dentro del nombre del producto
    histórico ("VINILICO PARA PISO") o viceversa. No es un match semántico
    — es exactamente el mismo criterio de "primera instancia" que se ve en
    el ejemplo de Simple Compras Públicas (nombres de producto calzando
    literalmente), documentado como punto de partida a mejorar más
    adelante si generа falsos positivos/negativos.
    """
    if not termino_normalizado or not producto_normalizado:
        return False
    return termino_normalizado in producto_normalizado or producto_normalizado in termino_normalizado


_CODIGOS_NO_ESPECIFICOS = {
    # Códigos de artículo ARCE que NO identifican un producto concreto del
    # rubro de Metropolitana (pisos/revestimientos/contenedores/etc.) sino
    # una categoría genérica de servicio/administrativa que cualquier
    # rubro puede usar — matchear por estos códigos no es evidencia de que
    # el llamado nuevo tenga algo que ver con Metropolitana. Cada uno tiene
    # evidencia concreta, no es una exclusión especulativa (ver
    # conversación 2026-08-18).
    "0",       # Placeholder/dato faltante en knowledge/historial_adjudicaciones_
               # metropolitana.json: bajo "código" 0 quedaron agrupados 5
               # productos sin relación entre sí (moquette, mano de obra,
               # instalación...) — no es un clasificador real de ARCE.
    "747",     # ENTREGA DE ENCOMIENDAS Y PAQUETES DENTRO DEL PAIS — servicio
               # de mensajería/logística, no un producto de pisos.
    "28031",   # CONTRATACION DE MANO DE OBRA — código genérico de "mano de
               # obra" que ARCE reutiliza en cualquier rubro (limpieza,
               # seguridad, jardinería...), no específico de instalación de
               # pisos.
    "35420",   # CONTRATACION DE SERVICIOS PROFESIONALES — FALSO POSITIVO REAL
               # detectado en la auditoría en vivo del 2026-08-18 (run #195):
               # disparó contra Licitación Abreviada A191575/2026 (Intendencia
               # de Montevideo, "Contratación de servicios profesionales con
               # destino al Departamento de Planificación"), que no tiene nada
               # que ver con pisos.
    "72449",   # ARRENDAMIENTO DE PISO — es un alquiler, no una venta/
               # instalación (importe $0 en el historial, probablemente un
               # alquiler puntual de piso para un evento). Contradice
               # directamente el filtro de alquiler de inmueble (ver
               # monitor._es_alquiler_de_inmueble()), así que no debe
               # disparar el match "sí o sí".
    "26627",   # ACONDICIONAMIENTO DE EDIFICIO — genérico, no específico del
               # rubro de pisos (podría ser electricidad, pintura, etc.).
    "27478",   # MANTENIMIENTO EDILICIO — genérico, mismo riesgo que el
               # anterior.
}


@functools.lru_cache(maxsize=1)
def _codigos_metropolitana() -> dict[str, str]:
    """codigo de artículo (str) -> nombre de producto (tal como figura en
    ARCE) de cada ítem que Metropolitana ya adjudicó, EXCLUYENDO los
    códigos genéricos/administrativos de _CODIGOS_NO_ESPECIFICOS.

    Señal MUCHO más fuerte que el match por texto de productos_ya_
    adjudicados(): el "codigo" es el clasificador exacto que asigna ARCE
    (visible como "Cód. Artículo" en la ficha de cada llamado, y como
    tender.items[].classification.id en el JSON OCDS — ver
    monitor._codigos_articulo()). Si un llamado nuevo pide un ítem con
    el mismo código que uno que Metropolitana ya facturó, es certeza de
    que existe un artículo concreto para ofertar — no una coincidencia de
    palabras que puede aparecer en un contexto ajeno al rubro. PERO esa
    certeza solo vale para códigos específicos de un producto físico: un
    código genérico de servicio (mano de obra, servicios profesionales,
    mensajería...) puede pertenecer a cualquier rubro, así que no alcanza
    como evidencia por sí solo.
    """
    out: dict[str, str] = {}
    for item in _cargar().get("items_metropolitana", []):
        codigo = item.get("codigo")
        producto = item.get("producto")
        if not codigo or not producto:
            continue
        codigo = str(codigo)
        if codigo in _CODIGOS_NO_ESPECIFICOS:
            continue
        if codigo not in out:
            out[codigo] = producto
    return out


def productos_por_codigo_ya_adjudicado(codigos: list[str]) -> list[str]:
    """Dada la lista de códigos de artículo (classification.id de OCDS) de
    los ítems de un llamado nuevo, devuelve los nombres de producto del
    historial de Metropolitana que matchean por CÓDIGO EXACTO (no por
    texto) — nombres deduplicados, orden estable.

    Pedido explícito del usuario 2026-08-18: si hay match por código, hay
    que enviar el llamado por mail sí o sí (ver monitor.es_relevante()),
    porque significa que Metropolitana ya le vendió ese artículo puntual
    al Estado antes.
    """
    if not codigos:
        return []
    mapa = _codigos_metropolitana()
    vistos: set[str] = set()
    resultado: list[str] = []
    for codigo in codigos:
        producto = mapa.get(str(codigo))
        if producto and producto not in vistos:
            vistos.add(producto)
            resultado.append(producto)
    return resultado


def productos_ya_adjudicados(terminos: list[str]) -> list[str]:
    """Dada la lista de términos que analyzer.identificar_productos()
    encontró en el pliego de un llamado nuevo (ProductoIdentificado.
    termino_encontrado), devuelve los nombres de producto del historial
    de Metropolitana que matchean — para armar la línea
    "Ya adjudicaste antes: X, Y, Z" del email y del visor.

    Devuelve nombres de producto tal como figuran en el historial
    (deduplicados, orden estable), no los términos de entrada — así el
    mensaje muestra el nombre "oficial" de ARCE, no la palabra clave
    interna que lo disparó.
    """
    if not terminos:
        return []
    terminos_norm = [_normalizar(t) for t in terminos]
    vistos: set[str] = set()
    resultado: list[str] = []
    for producto_norm, item in _items_metropolitana_normalizados():
        if producto_norm in vistos:
            continue
        for termino_norm in terminos_norm:
            if _matchea(termino_norm, producto_norm):
                vistos.add(producto_norm)
                resultado.append(item["producto"])
                break
    return resultado
