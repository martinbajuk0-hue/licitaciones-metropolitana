"""Seguimiento de resultados de adjudicación: para cada llamado que ya está
en el catálogo del visor (docs/data/llamados.json), determina si
Metropolitana se presentó y si ganó o perdió — lo que el usuario pidió el
2026-08-19 ("recordame como saber el tema de las licitaciones que me
presente y perdí").

Cómo funciona: la misma ficha humana de ARCE que ya guardamos como
"url_ficha" de cada llamado (comprasestatales.gub.uy/consultas/detalle/
id/<N>) va cambiando de contenido con el tiempo:

  1. Antes de la apertura de ofertas: solo el pliego, sin más.
  2. Después de la apertura: aparece la tabla "Proveedores participantes"
     (RUT + nombre de cada oferente) — esto ya nos dice si Metropolitana
     se presentó, aunque todavía no haya resolución.
  3. Después de la adjudicación: además aparecen "Resolución" (texto
     libre: "Adjudicada totalmente", "Adjudicada parcialmente",
     "Declarada sin efecto", "Todas las ofertas rechazadas", u otros que
     ARCE publique — no se asume un listado cerrado) y, en "Ítems
     adjudicados", qué proveedor ganó cada ítem/renglón.

No hay una API separada para esto: es la misma URL que ya visita una
persona para ver el llamado a simple vista, así que scrapear su HTML es
el único camino (confirmado navegando ARCE en vivo el 2026-08-19 — ver
conversación). Evitamos inventar estados: "ganamos"/"perdimos" surge
pura y exclusivamente de comparar RUT_METROPOLITANA contra el RUT que
ARCE lista como proveedor de cada ítem adjudicado, nunca de inferencias
sobre el texto de "Resolución".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

import parser as parser_mod

# RUT de Metropolitana S.A. tal como se presenta en las ofertas ante ARCE
# (dato provisto por el usuario 2026-08-19, no inferido).
RUT_METROPOLITANA = "210196570018"

# "Ítem Nº 2 MESA DE MADERA Y METAL (Cód. Artículo 5633) Proveedor: BLUM SA
# (RUT 211101590014) Variación:M4 ..." — confirmado en vivo sobre varias
# fichas de ARCE (LA 5/2026 y LA 14/2026, 2026-08-19). Se aplica sobre el
# texto ya aplanado de toda la página (BeautifulSoup.get_text(" ")), así
# que no depende de qué tags concretos use ARCE para envolver cada ítem —
# solo de esta secuencia literal de texto, que si ARCE la cambia hace que
# esto deje de matchear (fail-safe: sin items → sin "ganamos", nunca un
# resultado inventado).
_RE_ITEM_ADJUDICADO = re.compile(
    r"Ítem\s*Nº\s*\d+\s+.+?\(Cód\.\s*Artículo\s*\d+\)\s*Proveedor:\s*(.+?)\s*\(RUT\s*(\d+)\)"
)

# El número de compra de ARCE (comprasestatales.gub.uy) es el mismo tanto
# en la URL del JSON OCDS (".../ocds/release/llamado-<N>") como en la
# ficha humana (".../consultas/detalle/id/<N>") — confirmado en el fix de
# "Ver ficha en ARCE" (2026-08-18, ver tests/test_catalogo.py). Esto deja
# el seguimiento de resultados funcionando incluso para las entradas del
# catálogo guardadas ANTES de ese fix, cuyo "url_ficha" todavía apunta al
# JSON en vez de a la ficha humana.
_RE_ID_COMPRA = re.compile(r"(\d+)/?$")


def url_ficha_humana(url_ficha: str) -> str | None:
    """Normaliza cualquier URL de ARCE (JSON OCDS o ficha humana) a la
    ficha humana (consultas/detalle/id/<N>) — la única que trae la tabla
    de proveedores participantes y la resolución de adjudicación."""
    if not url_ficha:
        return None
    m = _RE_ID_COMPRA.search(url_ficha.strip().rstrip("/"))
    if not m:
        return None
    return f"https://www.comprasestatales.gub.uy/consultas/detalle/id/{m.group(1)}"


@dataclass
class ResultadoAdjudicacion:
    """Snapshot de una consulta a la ficha de ARCE de un llamado."""

    resolucion: str | None = None
    resolucion_nro: str | None = None
    fecha_resolucion: str | None = None
    monto_total: str | None = None
    # (rut, nombre) de cada oferente listado en "Proveedores participantes".
    oferentes: list[tuple[str, str]] = field(default_factory=list)
    # (rut, nombre) por cada ítem/renglón adjudicado — un proveedor que
    # ganó varios ítems aparece repetido, uno por ítem.
    ganadores_por_item: list[tuple[str, str]] = field(default_factory=list)

    @property
    def tiene_resolucion(self) -> bool:
        return bool(self.resolucion)

    @property
    def nos_presentamos(self) -> bool:
        return any(rut == RUT_METROPOLITANA for rut, _ in self.oferentes)

    @property
    def ganamos(self) -> bool | None:
        """None si todavía no hay resolución, o si Metropolitana no se
        presentó (no aplica "ganamos/perdimos" en ese caso). True/False
        solo cuando ya hay resolución Y nos presentamos."""
        if not self.tiene_resolucion or not self.nos_presentamos:
            return None
        return any(rut == RUT_METROPOLITANA for rut, _ in self.ganadores_por_item)


def estado_resumen(resultado: ResultadoAdjudicacion) -> str:
    """Cuatro estados posibles, usados como clave para decidir qué entra
    en el email de resultados (ver revisar_resultados.py):
      - "pendiente": ARCE todavía no publicó una resolución.
      - "no_presentamos": ya hay resolución, pero Metropolitana no está
        entre los oferentes — no es ni "ganamos" ni "perdimos".
      - "ganamos" / "perdimos": ya hay resolución y Metropolitana se
        presentó.
    """
    if not resultado.tiene_resolucion:
        return "pendiente"
    if not resultado.nos_presentamos:
        return "no_presentamos"
    return "ganamos" if resultado.ganamos else "perdimos"


def _texto_campo(soup: BeautifulSoup, etiqueta: str) -> str | None:
    """Los campos de la ficha (Resolución, Resolución Nro, Fecha
    Resolución, Monto Total de la Compra...) están en pares de <li>
    consecutivos: "<li>Etiqueta:</li><li>Valor</li>" (confirmado en vivo
    2026-08-19). Se busca por texto exacto en vez de por clase CSS porque
    la clase ("col-md-6 col-xs-6") es genérica de layout, no específica
    del campo."""
    for li in soup.find_all("li"):
        if li.get_text(strip=True) == etiqueta:
            siguiente = li.find_next_sibling("li")
            if siguiente:
                texto = siguiente.get_text(strip=True)
                return texto or None
    return None


def _oferentes_participantes(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Lee la tabla "Proveedores participantes" (RUT + nombre de cada
    oferente) directamente de su estructura HTML — más confiable que
    regex sobre texto aplanado porque cada celda es su propio <td>."""
    caption = soup.find("caption", string=lambda s: bool(s and "Proveedores participantes" in s))
    if caption is None:
        return []
    tabla = caption.find_parent("table")
    if tabla is None:
        return []
    tbody = tabla.find("tbody")
    if tbody is None:
        return []
    oferentes: list[tuple[str, str]] = []
    for tr in tbody.find_all("tr"):
        celdas = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(celdas) >= 3 and celdas[0].strip().upper() == "RUT":
            oferentes.append((celdas[1].strip(), celdas[2].strip()))
    return oferentes


def parsear_ficha(html: str) -> ResultadoAdjudicacion:
    """Parsea el HTML de una ficha de ARCE (consultas/detalle/id/<N>) a
    un ResultadoAdjudicacion. Separado de obtener_resultado() para poder
    testear el parseo sin red (ver tests/test_resultados.py)."""
    soup = BeautifulSoup(html, "html.parser")

    oferentes = _oferentes_participantes(soup)

    texto_plano = soup.get_text(" ", strip=True)
    ganadores = [
        (rut.strip(), nombre.strip())
        for nombre, rut in _RE_ITEM_ADJUDICADO.findall(texto_plano)
    ]

    return ResultadoAdjudicacion(
        resolucion=_texto_campo(soup, "Resolución:"),
        resolucion_nro=_texto_campo(soup, "Resolución Nro:"),
        fecha_resolucion=_texto_campo(soup, "Fecha Resolución:"),
        monto_total=_texto_campo(soup, "Monto Total de la Compra:"),
        oferentes=oferentes,
        ganadores_por_item=ganadores,
    )


def obtener_resultado(url_ficha: str) -> ResultadoAdjudicacion | None:
    """Consulta la ficha de ARCE de un llamado y devuelve su resultado
    actual, o None si la URL no se pudo normalizar o la consulta falló
    (red, HTTP, etc. — se loguea pero no interrumpe el resto de la
    corrida, igual que _leer_pliego() en monitor.py)."""
    url = url_ficha_humana(url_ficha)
    if not url:
        print(f"  ⚠️ No se pudo determinar la ficha humana a partir de: {url_ficha!r}")
        return None
    try:
        r = requests.get(url, headers=parser_mod.HEADERS, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  ⚠️ No se pudo consultar {url}: {e}")
        return None
    return parsear_ficha(r.text)
