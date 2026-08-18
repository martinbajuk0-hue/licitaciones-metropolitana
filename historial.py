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


@functools.lru_cache(maxsize=1)
def _codigos_metropolitana() -> dict[str, str]:
    """codigo de artículo (str) -> nombre de producto (tal como figura en
    ARCE) de cada ítem que Metropolitana ya adjudicó.

    Señal MUCHO más fuerte que el match por texto de productos_ya_
    adjudicados(): el "codigo" es el clasificador exacto que asigna ARCE
    (visible como "Cód. Artículo" en la ficha de cada llamado, y como
    tender.items[].classification.id en el JSON OCDS — ver
    monitor._codigos_articulo()). Si un llamado nuevo pide un ítem con
    el mismo código que uno que Metropolitana ya facturó, es certeza de
    que existe un artículo concreto para ofertar — no una coincidencia de
    palabras que puede aparecer en un contexto ajeno al rubro.
    """
    out: dict[str, str] = {}
    for item in _cargar().get("items_metropolitana", []):
        codigo = item.get("codigo")
        producto = item.get("producto")
        if codigo and producto and str(codigo) not in out:
            out[str(codigo)] = producto
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
