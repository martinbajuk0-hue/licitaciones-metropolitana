"""Detección de riesgos en un pliego (paso 8 del flujo).

Busca: multas y penalidades, plazos muy ajustados, certificaciones
especiales exigidas, garantías elevadas, y contradicciones (menciones
numéricas inconsistentes del mismo dato en distintas partes del pliego).

Es heurístico y basado en reglas — no reemplaza la lectura íntegra del
pliego por una persona, pero deja señalado *dónde mirar* con el fragmento
de texto que disparó cada alerta, para que la revisión humana sea rápida.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Severidad(str, Enum):
    ALTA = "alta"
    MEDIA = "media"
    BAJA = "baja"


@dataclass
class Riesgo:
    categoria: str
    severidad: Severidad
    descripcion: str
    fragmento: str

    def to_dict(self) -> dict:
        return {
            "categoria": self.categoria,
            "severidad": self.severidad.value,
            "descripcion": self.descripcion,
            "fragmento": self.fragmento,
        }


_PATRONES_MULTAS = [
    (r"multa[s]?\s+(?:de\s+)?(?:hasta\s+)?(\d+(?:[.,]\d+)?)\s*%", "Multa porcentual explícita"),
    (r"cl[áa]usula\s+penal", "Cláusula penal"),
    (r"mora\s+(?:autom[áa]tica|de pleno derecho)", "Mora automática"),
    (r"penalidad(?:es)?", "Penalidades mencionadas"),
    (r"rescisi[óo]n\s+(?:del\s+)?contrato", "Riesgo de rescisión contractual"),
]

_PATRON_PLAZO_ENTREGA_DIAS = re.compile(r"plazo\s+(?:de\s+)?entrega[^%\n]{0,20}?(\d{1,3})\s*d[ií]as", re.IGNORECASE)
UMBRAL_DIAS_PLAZO_AJUSTADO = 15

_PATRONES_PLAZOS_AJUSTADOS = [
    (r"48\s*horas", "Plazo de 48 horas mencionado"),
    (r"72\s*horas", "Plazo de 72 horas mencionado"),
]

_PATRONES_CERTIFICACIONES = [
    (r"iso\s*\d{4,5}", "Certificación ISO exigida"),
    (r"norma\s+unit", "Norma UNIT exigida"),
    (r"fifa\s+quality", "Certificación FIFA Quality exigida (césped sintético)"),
    (r"certificado\s+de\s+ensayo", "Certificado de ensayo de laboratorio exigido"),
    (r"reacci[óo]n\s+al\s+fuego", "Certificación de reacción al fuego exigida"),
    (r"certificaci[óo]n\s+ambiental", "Certificación ambiental exigida"),
    (r"declaraci[óo]n\s+de\s+origen", "Declaración de origen / DINAPYME exigida"),
]

_PATRONES_GARANTIAS = [
    # Hasta 40 caracteres libres entre la etiqueta y el %, para tolerar
    # variantes como "garantía de fiel cumplimiento DE CONTRATO: 5%" sin
    # cruzar a la línea siguiente.
    (r"garant[íi]a\s+de\s+mantenimiento\s+de\s+oferta[^%\n]{0,40}?(\d+(?:[.,]\d+)?)\s*%", "Garantía de mantenimiento de oferta"),
    (r"garant[íi]a\s+de\s+fiel\s+cumplimiento[^%\n]{0,40}?(\d+(?:[.,]\d+)?)\s*%", "Garantía de fiel cumplimiento"),
    (r"garant[íi]a\s+t[ée]cnica\s+(?:de\s+)?(?:m[íi]nimo\s+)?(\d+)\s*a[ñn]os?", "Garantía técnica de largo plazo exigida"),
]

_CONTEXTO_CHARS = 120


def _fragmento(texto: str, match: re.Match) -> str:
    inicio = max(0, match.start() - _CONTEXTO_CHARS // 2)
    fin = min(len(texto), match.end() + _CONTEXTO_CHARS // 2)
    return texto[inicio:fin].replace("\n", " ").strip()


def _buscar(texto: str, patrones: list[tuple[str, str]], categoria: str, severidad: Severidad) -> list[Riesgo]:
    riesgos = []
    vistos = set()
    for patron, descripcion in patrones:
        for match in re.finditer(patron, texto, re.IGNORECASE):
            clave = (descripcion, match.group(0).lower())
            if clave in vistos:
                continue
            vistos.add(clave)
            riesgos.append(
                Riesgo(
                    categoria=categoria,
                    severidad=severidad,
                    descripcion=descripcion,
                    fragmento=_fragmento(texto, match),
                )
            )
    return riesgos


def detectar_multas_y_penalidades(texto: str) -> list[Riesgo]:
    return _buscar(texto, _PATRONES_MULTAS, "multas_penalidades", Severidad.ALTA)


def detectar_plazos_ajustados(texto: str) -> list[Riesgo]:
    riesgos = _buscar(texto, _PATRONES_PLAZOS_AJUSTADOS, "plazos", Severidad.MEDIA)

    for match in _PATRON_PLAZO_ENTREGA_DIAS.finditer(texto):
        dias = int(match.group(1))
        if dias <= UMBRAL_DIAS_PLAZO_AJUSTADO:
            riesgos.append(
                Riesgo(
                    categoria="plazos",
                    severidad=Severidad.MEDIA,
                    descripcion=f"Plazo de entrega ajustado ({dias} días) — verificar viabilidad logística",
                    fragmento=_fragmento(texto, match),
                )
            )

    return riesgos


def detectar_certificaciones_especiales(texto: str) -> list[Riesgo]:
    return _buscar(texto, _PATRONES_CERTIFICACIONES, "certificaciones", Severidad.MEDIA)


def detectar_garantias_exigentes(texto: str) -> list[Riesgo]:
    return _buscar(texto, _PATRONES_GARANTIAS, "garantias", Severidad.MEDIA)


def detectar_contradicciones(texto: str) -> list[Riesgo]:
    """Heurística simple: si el mismo concepto (plazo de entrega, garantía
    de mantenimiento de oferta) aparece con valores numéricos distintos en
    el pliego, se marca como posible contradicción para revisión manual.
    """
    riesgos = []
    conceptos = {
        "plazo de entrega": _PATRON_PLAZO_ENTREGA_DIAS.pattern,
        "garantía de mantenimiento de oferta": r"garant[íi]a\s+de\s+mantenimiento\s+de\s+oferta[^%\n]{0,40}?(\d+(?:[.,]\d+)?)\s*%",
        "garantía de fiel cumplimiento": r"garant[íi]a\s+de\s+fiel\s+cumplimiento[^%\n]{0,40}?(\d+(?:[.,]\d+)?)\s*%",
    }
    for concepto, patron in conceptos.items():
        valores = set()
        matches = list(re.finditer(patron, texto, re.IGNORECASE))
        for m in matches:
            valores.add(m.group(1))
        if len(valores) > 1:
            fragmento = " | ".join(_fragmento(texto, m) for m in matches[:4])
            riesgos.append(
                Riesgo(
                    categoria="contradicciones",
                    severidad=Severidad.ALTA,
                    descripcion=f"Valores distintos para '{concepto}' en el mismo pliego: {sorted(valores)}",
                    fragmento=fragmento,
                )
            )
    return riesgos


def analizar_riesgos(texto: str) -> list[Riesgo]:
    """Corre todos los detectores y devuelve la lista consolidada,
    ordenada por severidad (alta primero).
    """
    riesgos: list[Riesgo] = []
    riesgos += detectar_multas_y_penalidades(texto)
    riesgos += detectar_plazos_ajustados(texto)
    riesgos += detectar_certificaciones_especiales(texto)
    riesgos += detectar_garantias_exigentes(texto)
    riesgos += detectar_contradicciones(texto)

    orden = {Severidad.ALTA: 0, Severidad.MEDIA: 1, Severidad.BAJA: 2}
    riesgos.sort(key=lambda r: orden[r.severidad])
    return riesgos
