"""Estadísticas agregadas de adjudicaciones históricas para la pestaña
"Performance" del visor (docs/index.html), calcada de proveedoruy.com/
performance (ver conversación 2026-08-18).

Fuente de datos: la MISMA que usa historial.py — knowledge/
historial_adjudicaciones_metropolitana.json (761 ítems, 508 llamados
distintos adjudicados a Metropolitana entre 2025 y 2026, con organismo,
tipo, número, producto, código de artículo, cantidad, importe y fecha por
ítem). Es un dato congelado (ver el campo "generado" del propio JSON), así
que estas estadísticas tampoco se recalculan a partir de llamados
posteriores a esa fecha.

IMPORTANTE — qué NO incluye este módulo: ProveedorUY muestra además
"Participaciones" (llamados donde Metropolitana ofertó, haya ganado o no),
"Tasa de éxito" y "Organismos donde más perdés". Esos datos requieren
saber también las compras en las que Metropolitana participó y NO ganó —
algo que no está en nuestro historial (que solo registra adjudicaciones
ganadas) ni es trivial de obtener: el JSON OCDS de un llamado activo no
expone la lista de oferentes, así que reconstruir el historial de
participación/pérdidas requeriría relevar individualmente el acta de
apertura de cada llamado histórico en ARCE — un trabajo mucho más grande
que el que ya se hizo para las 761 adjudicaciones ganadas. Decisión del
usuario 2026-08-18: publicar primero lo que sí se puede calcular con los
datos que ya tenemos, y dejar el relevamiento de participaciones/pérdidas
para más adelante. El HTML deja esto explícito en vez de simular el dato.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import historial as historial_mod

_BASE_DIR = Path(__file__).resolve().parent
PERFORMANCE_PATH = _BASE_DIR / "docs" / "data" / "performance.json"


def _clave_llamado(item: dict) -> tuple:
    # (organismo, numero) identifica un llamado de forma suficientemente
    # única dentro del historial: "numero" solo repite entre organismos
    # distintos (ver auditoría 2026-08-18: 501 números únicos pero 508
    # pares organismo+número únicos).
    return (item.get("organismo"), item.get("numero"))


def _anio(fecha: str | None) -> str | None:
    # Fechas del historial vienen como "DD/MM/AAAA".
    if not fecha or "/" not in fecha:
        return None
    partes = fecha.split("/")
    if len(partes) != 3 or len(partes[2]) != 4:
        return None
    return partes[2]


def calcular() -> dict:
    items = historial_mod._cargar().get("items_metropolitana", [])

    llamados_vistos: set[tuple] = set()
    organismos_de_llamado: dict[tuple, str] = {}
    tipo_de_llamado: dict[tuple, str] = {}
    anio_de_llamado: dict[tuple, str | None] = {}

    total_adjudicado = 0.0
    items_adjudicados = 0

    por_anio: dict[str, dict] = defaultdict(lambda: {"importe": 0.0, "llamados": set()})
    por_organismo: dict[str, dict] = defaultdict(lambda: {"importe": 0.0, "llamados": set()})
    por_tipo: dict[str, dict] = defaultdict(lambda: {"importe": 0.0, "llamados": set(), "items": 0})
    por_producto: dict[str, dict] = defaultdict(lambda: {"importe": 0.0, "veces": 0, "organismos": set()})
    producto_por_organismo: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: {"importe": 0.0, "veces": 0}))

    for item in items:
        organismo = item.get("organismo") or "No especificado"
        tipo = item.get("tipo") or "No especificado"
        producto = item.get("producto") or "No especificado"
        importe = float(item.get("importe") or 0)
        clave = _clave_llamado(item)
        anio = _anio(item.get("fecha"))

        llamados_vistos.add(clave)
        organismos_de_llamado[clave] = organismo
        tipo_de_llamado[clave] = tipo
        anio_de_llamado[clave] = anio

        total_adjudicado += importe
        items_adjudicados += 1

        if anio:
            por_anio[anio]["importe"] += importe
            por_anio[anio]["llamados"].add(clave)

        por_organismo[organismo]["importe"] += importe
        por_organismo[organismo]["llamados"].add(clave)

        por_tipo[tipo]["importe"] += importe
        por_tipo[tipo]["llamados"].add(clave)
        por_tipo[tipo]["items"] += 1

        por_producto[producto]["importe"] += importe
        por_producto[producto]["veces"] += 1
        por_producto[producto]["organismos"].add(organismo)

        pxo = producto_por_organismo[organismo][producto]
        pxo["importe"] += importe
        pxo["veces"] += 1

    total_llamados = len(llamados_vistos)
    organismos_distintos = len({o for o in organismos_de_llamado.values()})

    evolucion_anual = sorted(
        (
            {"anio": anio, "importe": round(v["importe"], 2), "llamados": len(v["llamados"])}
            for anio, v in por_anio.items()
        ),
        key=lambda r: r["anio"],
    )

    top_organismos = sorted(
        (
            {"organismo": o, "importe": round(v["importe"], 2), "llamados": len(v["llamados"])}
            for o, v in por_organismo.items()
        ),
        key=lambda r: -r["importe"],
    )

    distribucion_tipo = sorted(
        (
            {
                "tipo": t,
                "llamados": len(v["llamados"]),
                "items": v["items"],
                "importe": round(v["importe"], 2),
            }
            for t, v in por_tipo.items()
        ),
        key=lambda r: -r["importe"],
    )

    articulos_mas_adjudicados = sorted(
        (
            {
                "producto": p,
                "veces": v["veces"],
                "organismos": len(v["organismos"]),
                "importe": round(v["importe"], 2),
            }
            for p, v in por_producto.items()
        ),
        key=lambda r: -r["veces"],
    )

    articulos_por_organismo = []
    # Mismo orden que top_organismos, tope en los primeros 8 para no
    # inflar el JSON con organismos marginales — el visor solo necesita
    # los principales para el desglose "artículos más adjudicados por
    # organismo" (calcado de proveedoruy.com/performance).
    for row in top_organismos[:8]:
        organismo = row["organismo"]
        productos = sorted(
            (
                {"producto": p, "veces": v["veces"], "importe": round(v["importe"], 2)}
                for p, v in producto_por_organismo[organismo].items()
            ),
            key=lambda r: -r["veces"],
        )[:5]
        articulos_por_organismo.append({
            "organismo": organismo,
            "llamados": row["llamados"],
            "articulos": productos,
        })

    concentracion_top = top_organismos[0] if top_organismos else None
    concentracion_pct = (
        round(100 * concentracion_top["importe"] / total_adjudicado, 1)
        if concentracion_top and total_adjudicado
        else 0
    )

    return {
        "generado": historial_mod._cargar().get("generado"),
        "total_adjudicado": round(total_adjudicado, 2),
        "items_adjudicados": items_adjudicados,
        "total_llamados": total_llamados,
        "organismos_distintos": organismos_distintos,
        "evolucion_anual": evolucion_anual,
        "top_organismos": top_organismos,
        "distribucion_tipo": distribucion_tipo,
        "articulos_mas_adjudicados": articulos_mas_adjudicados,
        "articulos_por_organismo": articulos_por_organismo,
        "concentracion": {
            "organismo": concentracion_top["organismo"] if concentracion_top else None,
            "importe": concentracion_top["importe"] if concentracion_top else 0,
            "porcentaje": concentracion_pct,
        },
    }


def generar() -> None:
    """Recalcula y guarda docs/data/performance.json. Se llama una vez acá
    (dato congelado, no cambia entre corridas del pipeline) y puede
    volver a llamarse manualmente si knowledge/historial_adjudicaciones_
    metropolitana.json se actualiza más adelante.
    """
    PERFORMANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PERFORMANCE_PATH, "w", encoding="utf-8") as f:
        json.dump(calcular(), f, ensure_ascii=False, indent=2, sort_keys=False)


if __name__ == "__main__":
    generar()
    print(f"Generado {PERFORMANCE_PATH}")
