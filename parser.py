"""Extracción de texto de la documentación de una licitación.

Cubre el paso 3-4 del flujo ("Descargar toda la documentación" / "Leer
íntegramente el pliego"): PDF, Word, Excel e imágenes (OCR best-effort).

Las dependencias no esenciales (python-docx, openpyxl, pytesseract) son
opcionales: si no están instaladas, el parser degrada avisando qué tipo de
archivo no pudo leer en vez de fallar todo el pipeline. Esto es intencional
— un pliego con un anexo en Excel no debería tirar abajo el análisis del
PDF principal.
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MetropolitanaLicitaciones/1.0)"}

EXTENSIONES_SOPORTADAS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


@dataclass
class DocumentoExtraido:
    nombre: str
    url: str
    tipo: str
    texto: str = ""
    paginas_leidas: int = 0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.texto.strip())


@dataclass
class PliegoExtraido:
    documentos: list[DocumentoExtraido] = field(default_factory=list)

    @property
    def texto_completo(self) -> str:
        return "\n\n".join(d.texto for d in self.documentos if d.texto)

    @property
    def documentos_con_error(self) -> list[DocumentoExtraido]:
        return [d for d in self.documentos if d.error]


# ─── Extractores por tipo de archivo ──────────────────────────────────────

def _extraer_pdf(path: Path, max_paginas: int = 40) -> tuple[str, int]:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError("Falta la librería 'pypdf' (pip install pypdf)") from e

    reader = PdfReader(str(path))
    texto = []
    n = min(len(reader.pages), max_paginas)
    for i in range(n):
        texto.append(reader.pages[i].extract_text() or "")
    return "\n".join(texto), n


def _extraer_docx(path: Path) -> tuple[str, int]:
    try:
        import docx
    except ImportError as e:
        raise RuntimeError("Falta la librería 'python-docx' (pip install python-docx)") from e

    doc = docx.Document(str(path))
    partes = [p.text for p in doc.paragraphs]
    for tabla in doc.tables:
        for fila in tabla.rows:
            partes.append(" | ".join(c.text for c in fila.cells))
    return "\n".join(partes), 1


def _extraer_xlsx(path: Path) -> tuple[str, int]:
    try:
        import openpyxl
    except ImportError as e:
        raise RuntimeError("Falta la librería 'openpyxl' (pip install openpyxl)") from e

    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    partes = []
    hojas = 0
    for hoja in wb.worksheets:
        hojas += 1
        partes.append(f"### Hoja: {hoja.title}")
        for fila in hoja.iter_rows(values_only=True):
            valores = [str(v) for v in fila if v is not None]
            if valores:
                partes.append(" | ".join(valores))
    return "\n".join(partes), hojas


def _extraer_imagen(path: Path) -> tuple[str, int]:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:
        raise RuntimeError(
            "Falta 'pytesseract'/'Pillow' o el binario de Tesseract OCR no está "
            "instalado (pip install pytesseract pillow, y el paquete de sistema tesseract-ocr)"
        ) from e

    texto = pytesseract.image_to_string(Image.open(path), lang="spa+eng")
    return texto, 1


_EXTRACTORES = {
    ".pdf": _extraer_pdf,
    ".docx": _extraer_docx,
    ".xlsx": _extraer_xlsx,
    ".png": _extraer_imagen,
    ".jpg": _extraer_imagen,
    ".jpeg": _extraer_imagen,
    ".tif": _extraer_imagen,
    ".tiff": _extraer_imagen,
}


def extraer_archivo_local(path: Path, nombre: Optional[str] = None, url: str = "") -> DocumentoExtraido:
    """Extrae texto de un archivo ya descargado en disco."""
    nombre = nombre or path.name
    ext = path.suffix.lower()
    extractor = _EXTRACTORES.get(ext)

    if extractor is None:
        if ext in (".doc", ".xls"):
            return DocumentoExtraido(
                nombre=nombre, url=url, tipo=ext,
                error=(
                    f"Formato legado '{ext}' no soportado directamente. "
                    "Convertir a .docx/.xlsx o exportar a PDF antes de analizar."
                ),
            )
        return DocumentoExtraido(nombre=nombre, url=url, tipo=ext, error=f"Extensión no soportada: {ext}")

    try:
        texto, paginas = extractor(path)
        return DocumentoExtraido(nombre=nombre, url=url, tipo=ext, texto=texto, paginas_leidas=paginas)
    except Exception as e:  # noqa: BLE001 - queremos degradar, no abortar el pipeline
        return DocumentoExtraido(nombre=nombre, url=url, tipo=ext, error=str(e))


def descargar_y_extraer(url: str, timeout: int = 30) -> DocumentoExtraido:
    """Descarga un documento por URL y extrae su texto."""
    nombre = url.rstrip("/").split("/")[-1] or url
    ext = Path(nombre).suffix.lower()
    if not ext:
        ext = ".pdf"  # los portales de compras suelen servir PDFs sin extensión en la URL

    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        return DocumentoExtraido(nombre=nombre, url=url, tipo=ext, error=f"No se pudo descargar: {e}")

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(r.content)
        tmp_path = Path(f.name)

    try:
        return extraer_archivo_local(tmp_path, nombre=nombre, url=url)
    finally:
        tmp_path.unlink(missing_ok=True)


def encontrar_links_documentos(html: str, base_url: str = "") -> list[str]:
    """Busca links a documentos descargables (pdf/doc/xls/imagen) en una página HTML."""
    patron = r'href=["\']([^"\']+\.(?:pdf|docx?|xlsx?|png|jpe?g|tiff?))["\']'
    links = re.findall(patron, html, re.IGNORECASE)
    resultado = []
    for link in links:
        if link.startswith("http"):
            resultado.append(link)
        elif base_url:
            resultado.append(base_url.rstrip("/") + "/" + link.lstrip("/"))
    return resultado


def extraer_pliego(url_licitacion: str, max_documentos: int = 10) -> PliegoExtraido:
    """Punto de entrada principal: dada la URL de una licitación en
    comprasestatales.gub.uy, descarga y extrae todos los documentos
    adjuntos que pueda encontrar.
    """
    pliego = PliegoExtraido()
    try:
        r = requests.get(url_licitacion, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        pliego.documentos.append(
            DocumentoExtraido(nombre=url_licitacion, url=url_licitacion, tipo="pagina", error=str(e))
        )
        return pliego

    links = encontrar_links_documentos(r.text, base_url="https://www.comprasestatales.gub.uy")
    for link in links[:max_documentos]:
        pliego.documentos.append(descargar_y_extraer(link))

    return pliego
