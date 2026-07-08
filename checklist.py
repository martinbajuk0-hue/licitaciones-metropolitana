"""Checklist documental (paso 9 del flujo).

Combina una lista estándar de documentación habitual en licitaciones
uruguayas (RUPE, DGI, BPS, poderes, certificados, catálogos, fichas
técnicas, garantías, seguros) con una búsqueda en el texto del pliego
para marcar qué ítems están explícitamente exigidos, cuáles no se
mencionan (hay que verificar si igual aplican) y con qué evidencia.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class EstadoItem(str, Enum):
    EXIGIDO_EN_PLIEGO = "exigido_en_pliego"
    ESTANDAR_NO_MENCIONADO = "estandar_no_mencionado_verificar"


@dataclass
class ItemChecklist:
    id: str
    nombre: str
    estado: EstadoItem
    evidencia: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "nombre": self.nombre, "estado": self.estado.value, "evidencia": self.evidencia}


# Documentación estándar que casi siempre debe verificarse en una compra
# pública uruguaya, independientemente de que el pliego la mencione con
# estas palabras exactas. id -> (nombre, patrones de búsqueda)
_ITEMS_ESTANDAR: dict[str, tuple[str, list[str]]] = {
    "rupe": ("Inscripción activa en RUPE", [r"rupe"]),
    "dgi": ("Certificado único de DGI vigente", [r"certificado\s+[úu]nico\s+de\s+dgi", r"\bdgi\b"]),
    "bps": ("Certificado único de BPS vigente", [r"certificado\s+[úu]nico\s+de\s+bps", r"\bbps\b"]),
    "poderes": ("Poderes / representación legal vigentes", [r"poder(?:es)?\s+(?:notarial|de\s+representaci[óo]n)", r"representante\s+legal"]),
    "certificado_notarial": ("Certificado notarial de vigencia / representación", [r"certificado\s+notarial"]),
    "antecedentes_financieros": ("Estados contables / antecedentes financieros", [r"estados?\s+contables?", r"balance"]),
    "catalogos": ("Catálogos de producto", [r"cat[áa]logo"]),
    "fichas_tecnicas": ("Fichas técnicas de los productos ofertados", [r"ficha\s+t[ée]cnica"]),
    "muestras": ("Muestras físicas de producto", [r"muestra[s]?\s+(?:f[íi]sica[s]?|de\s+producto)"]),
    "garantia_mantenimiento_oferta": ("Garantía de mantenimiento de oferta", [r"garant[íi]a\s+de\s+mantenimiento\s+de\s+oferta"]),
    "garantia_fiel_cumplimiento": ("Garantía de fiel cumplimiento de contrato", [r"garant[íi]a\s+de\s+fiel\s+cumplimiento"]),
    "seguros": ("Pólizas de seguro (responsabilidad civil / accidentes)", [r"p[óo]liza", r"seguro\s+de\s+responsabilidad\s+civil", r"seguro\s+contra\s+accidentes"]),
    "antecedentes_similares": ("Antecedentes en obras/suministros similares", [r"antecedentes?\s+(?:en|de)\s+(?:obras?|suministros?)"]),
    "visita_obra": ("Constancia de visita de obra (si el pliego la exige)", [r"visita\s+(?:de\s+)?obra", r"visita\s+previa"]),
    "declaracion_jurada": ("Declaraciones juradas exigidas", [r"declaraci[óo]n\s+jurada"]),
    "identificacion_oferente": ("Formulario de identificación del oferente", [r"identificaci[óo]n\s+del\s+oferente"]),
}


def _buscar_evidencia(texto: str, patrones: list[str]) -> str:
    for patron in patrones:
        m = re.search(patron, texto, re.IGNORECASE)
        if m:
            inicio = max(0, m.start() - 60)
            fin = min(len(texto), m.end() + 60)
            return texto[inicio:fin].replace("\n", " ").strip()
    return ""


def generar_checklist(texto: str) -> list[ItemChecklist]:
    items = []
    for item_id, (nombre, patrones) in _ITEMS_ESTANDAR.items():
        evidencia = _buscar_evidencia(texto, patrones)
        estado = EstadoItem.EXIGIDO_EN_PLIEGO if evidencia else EstadoItem.ESTANDAR_NO_MENCIONADO
        items.append(ItemChecklist(id=item_id, nombre=nombre, estado=estado, evidencia=evidencia))
    return items


def items_pendientes_de_verificar(items: list[ItemChecklist]) -> list[ItemChecklist]:
    return [i for i in items if i.estado == EstadoItem.ESTANDAR_NO_MENCIONADO]


def items_exigidos(items: list[ItemChecklist]) -> list[ItemChecklist]:
    return [i for i in items if i.estado == EstadoItem.EXIGIDO_EN_PLIEGO]
