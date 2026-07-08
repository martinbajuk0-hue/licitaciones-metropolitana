"""Ayuda a cotizar (paso 10-11 del flujo): recomienda productos y arma un
borrador de presupuesto a partir de knowledge/precios.yaml.

Regla dura: si un producto no tiene precio cargado en
knowledge/precios.yaml, este módulo NUNCA estima ni inventa un número.
Devuelve el ítem marcado explícitamente como sin precio y qué hacer para
cargarlo. Esto es deliberado: cotizar con un precio inventado es peor que
no cotizar.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import config.settings as settings


@dataclass
class ItemCotizacion:
    producto_id: str
    nombre: str
    cantidad: float
    unidad: str
    precio_unitario: Optional[float]
    moneda: Optional[str]
    subtotal: Optional[float]
    nota: str = ""

    def to_dict(self) -> dict:
        return {
            "producto_id": self.producto_id,
            "nombre": self.nombre,
            "cantidad": self.cantidad,
            "unidad": self.unidad,
            "precio_unitario": self.precio_unitario,
            "moneda": self.moneda,
            "subtotal": self.subtotal,
            "nota": self.nota,
        }


def _buscar_producto(producto_id: str) -> Optional[dict]:
    for categoria in settings.productos().get("categorias", {}).values():
        for subtipo in categoria.get("subtipos", []):
            if subtipo.get("id") == producto_id:
                return subtipo
    return None


def cotizar_item(producto_id: str, cantidad: float) -> ItemCotizacion:
    producto = _buscar_producto(producto_id)
    nombre = producto["nombre"] if producto else producto_id
    unidad = producto.get("unidad_venta", "m2") if producto else "m2"

    precios_cfg = settings.precios()
    entrada_precio = precios_cfg.get("precios", {}).get(producto_id)

    if not entrada_precio or entrada_precio.get("precio_unitario") is None:
        return ItemCotizacion(
            producto_id=producto_id,
            nombre=nombre,
            cantidad=cantidad,
            unidad=unidad,
            precio_unitario=None,
            moneda=None,
            subtotal=None,
            nota="SIN PRECIO CARGADO - completar en knowledge/precios.yaml antes de cotizar formalmente",
        )

    precio_unitario = float(entrada_precio["precio_unitario"])
    moneda = entrada_precio.get("moneda", precios_cfg.get("moneda_default", "UYU"))
    subtotal = round(precio_unitario * cantidad, 2)

    return ItemCotizacion(
        producto_id=producto_id,
        nombre=nombre,
        cantidad=cantidad,
        unidad=unidad,
        precio_unitario=precio_unitario,
        moneda=moneda,
        subtotal=subtotal,
        nota="" if entrada_precio.get("iva_incluido") else "Precio sin IVA",
    )


def cotizar(items: list[tuple[str, float]], margen_porcentaje: float = 0.0) -> dict:
    """items: lista de (producto_id, cantidad).
    margen_porcentaje: margen comercial a aplicar sobre el subtotal con precio cargado.
    """
    detalle = [cotizar_item(pid, cant) for pid, cant in items]
    con_precio = [d for d in detalle if d.subtotal is not None]
    sin_precio = [d for d in detalle if d.subtotal is None]

    subtotal = sum(d.subtotal for d in con_precio)
    margen = round(subtotal * (margen_porcentaje / 100), 2)
    subtotal_con_margen = subtotal + margen
    iva_pct = settings.precios().get("iva_uruguay_porcentaje", 22)
    iva = round(subtotal_con_margen * (iva_pct / 100), 2)
    total = subtotal_con_margen + iva

    return {
        "detalle": [d.to_dict() for d in detalle],
        "items_incompletos": [d.producto_id for d in sin_precio],
        "subtotal": subtotal,
        "margen_porcentaje": margen_porcentaje,
        "margen": margen,
        "iva_porcentaje": iva_pct,
        "iva": iva,
        "total": round(total, 2) if not sin_precio else None,
        "cotizacion_completa": len(sin_precio) == 0,
        "nota": (
            "Cotización incompleta: hay ítems sin precio cargado en knowledge/precios.yaml."
            if sin_precio else ""
        ),
    }


def sugerir_productos_equivalentes(especificacion_pliego: str) -> list[dict]:
    """Busca en knowledge/productos.yaml -> equivalencias_recomendadas una
    coincidencia aproximada con lo que pide el pliego.
    """
    especificacion_pliego = especificacion_pliego.lower()
    sugerencias = []
    for eq in settings.productos().get("equivalencias_recomendadas", []):
        palabras_clave = eq["especificacion_pliego"].lower().split()
        coincidencias = sum(1 for p in palabras_clave if p in especificacion_pliego)
        if coincidencias >= max(2, len(palabras_clave) // 2):
            sugerencias.append(eq)
    return sugerencias
