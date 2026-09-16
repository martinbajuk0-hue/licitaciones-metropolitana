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

import multiprocessing
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MetropolitanaLicitaciones/1.0)"}

EXTENSIONES_SOPORTADAS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".odt", ".zip", ".7z", ".rar",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff",
}

# Timeout duro (en segundos) para la extracción de texto de UN documento.
#
# Evidencia real (corrida #206 de monitor.yml, 2026-08-20): un pliego en PDF
# con una fuente de codificación no estándar ("/SymbolSetEncoding") hizo que
# pypdf.extract_text() se volviera catastróficamente lento — el log repitió
# la advertencia "Advanced encoding /SymbolSetEncoding not implemented yet"
# sin parar durante 5h59m, hasta que GitHub mató el job entero por el límite
# de 6 horas. Se perdió TODA la corrida (todos los llamados ya procesados,
# no solo ese documento) porque no había ningún límite de tiempo alrededor
# de la extracción.
#
# Configurable vía env var para poder bajarlo en tests.
TIMEOUT_EXTRACCION_SEGUNDOS = int(os.environ.get("TIMEOUT_EXTRACCION_DOCUMENTO_SEGUNDOS", "120"))


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


def _extraer_doc_legado(path: Path) -> tuple[str, int]:
    """Extrae texto de un .doc binario legado (formato OLE/Compound File,
    anterior a Word 2007) usando el binario de sistema 'antiword'.

    No hay una librería Python confiable para este formato binario —
    antiword es la herramienta estándar de facto en Debian/Ubuntu (paquete
    'antiword', instalado en el workflow de CI vía apt-get).
    """
    if shutil.which("antiword") is None:
        raise RuntimeError(
            "Falta el binario 'antiword' (instalar vía 'apt-get install antiword') "
            "para leer archivos .doc en formato binario legado."
        )
    resultado = subprocess.run(
        ["antiword", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    if resultado.returncode != 0:
        raise RuntimeError(f"antiword falló (código {resultado.returncode}): {resultado.stderr.strip()[:300]}")
    return resultado.stdout, 1


def _extraer_xls_legado(path: Path) -> tuple[str, int]:
    """Extrae texto de un .xls binario legado (formato BIFF, anterior a
    Excel 2007) usando xlrd. IMPORTANTE: solo xlrd < 2.0 lee este formato —
    la versión 2.0 en adelante eliminó soporte legado y solo lee .xlsx
    (redundante con openpyxl). Ver requirements.txt (pin xlrd==1.2.0).
    """
    try:
        import xlrd
    except ImportError as e:
        raise RuntimeError("Falta la librería 'xlrd' (pip install xlrd==1.2.0) para leer .xls legado") from e

    wb = xlrd.open_workbook(str(path))
    partes = []
    for hoja in wb.sheets():
        partes.append(f"### Hoja: {hoja.name}")
        for fila_idx in range(hoja.nrows):
            valores = [str(v) for v in hoja.row_values(fila_idx) if v not in (None, "")]
            if valores:
                partes.append(" | ".join(valores))
    return "\n".join(partes), wb.nsheets


def _extraer_odt(path: Path) -> tuple[str, int]:
    """Extrae texto de un OpenDocument Text (.odt)."""
    try:
        from odf.opendocument import load
        from odf.text import H, P
        from odf import teletype
    except ImportError as e:
        raise RuntimeError("Falta la librería 'odfpy' (pip install odfpy) para leer .odt") from e

    doc = load(str(path))
    partes = []
    for parrafo in doc.getElementsByType(P) + doc.getElementsByType(H):
        texto = teletype.extractText(parrafo)
        if texto:
            partes.append(texto)
    return "\n".join(partes), 1


def _extraer_miembros_comprimido(nombres_y_bytes, extractores_internos) -> tuple[str, int]:
    """Lógica compartida por los tres formatos de archivo comprimido
    (.zip, .7z, .rar): recorre (nombre_interno, contenido) y despacha cada
    archivo interno al extractor de _EXTRACTORES que corresponda a su
    extensión, concatenando el texto de todos los que se puedan leer.
    """
    partes = []
    total = 0
    for nombre_interno, contenido in nombres_y_bytes:
        ext_interno = Path(nombre_interno).suffix.lower()
        extractor_interno = extractores_internos.get(ext_interno)
        if extractor_interno is None:
            continue
        with tempfile.NamedTemporaryFile(suffix=ext_interno, delete=False) as f:
            f.write(contenido)
            tmp_path = Path(f.name)
        try:
            texto_interno, n = extractor_interno(tmp_path)
            if texto_interno.strip():
                partes.append(f"### Archivo dentro del comprimido: {nombre_interno}\n{texto_interno}")
                total += n
        except Exception:
            continue
        finally:
            tmp_path.unlink(missing_ok=True)
    if not partes:
        raise RuntimeError(
            "El archivo comprimido no contiene ningún archivo en un formato soportado "
            "(o todos fallaron al leerse)"
        )
    return "\n\n".join(partes), total


def _extraer_zip(path: Path) -> tuple[str, int]:
    """Extrae texto recursivamente de los archivos soportados dentro de un
    .zip (frecuente en comprasestatales.gub.uy cuando el organismo sube el
    pliego + anexos comprimidos en un solo adjunto).

    Deliberadamente NO incluye ".zip" en el diccionario de extractores
    usado para la recursión interna: un .zip dentro de otro .zip no se
    sigue expandiendo, para evitar una bomba de descompresión con un
    adjunto malicioso o corrupto. (Mismo criterio en _extraer_7z/_extraer_rar
    respecto de su propio formato — no impide anidar TIPOS distintos entre
    sí, pero eso no es un vector de riesgo realista para pliegos oficiales.)
    """
    extractores_internos = {ext: fn for ext, fn in _EXTRACTORES.items() if ext != ".zip"}
    with zipfile.ZipFile(path) as zf:
        pares = ((info.filename, zf.read(info)) for info in zf.infolist() if not info.is_dir())
        return _extraer_miembros_comprimido(pares, extractores_internos)


def _extraer_7z(path: Path) -> tuple[str, int]:
    """Extrae texto recursivamente de los archivos soportados dentro de un .7z."""
    try:
        import py7zr
    except ImportError as e:
        raise RuntimeError("Falta la librería 'py7zr' (pip install py7zr) para leer .7z") from e

    extractores_internos = {ext: fn for ext, fn in _EXTRACTORES.items() if ext != ".7z"}
    with tempfile.TemporaryDirectory() as tmpdir:
        with py7zr.SevenZipFile(str(path), mode="r") as archivo:
            archivo.extractall(path=tmpdir)
        pares = [
            (p.relative_to(tmpdir).as_posix(), p.read_bytes())
            for p in Path(tmpdir).rglob("*")
            if p.is_file()
        ]
        return _extraer_miembros_comprimido(pares, extractores_internos)


def _extraer_rar(path: Path) -> tuple[str, int]:
    """Extrae texto recursivamente de los archivos soportados dentro de un
    .rar. Requiere el binario de sistema 'unrar' (rarfile es solo un
    wrapper que le delega la descompresión — el formato RAR es propietario
    y no hay una implementación pura Python confiable).
    """
    try:
        import rarfile
    except ImportError as e:
        raise RuntimeError("Falta la librería 'rarfile' (pip install rarfile) para leer .rar") from e

    if shutil.which("unrar") is None:
        raise RuntimeError(
            "Falta el binario 'unrar' (instalar vía 'apt-get install unrar') para leer archivos .rar."
        )
    extractores_internos = {ext: fn for ext, fn in _EXTRACTORES.items() if ext != ".rar"}
    with rarfile.RarFile(str(path)) as archivo:
        pares = [
            (info.filename, archivo.read(info))
            for info in archivo.infolist()
            if not info.is_dir()
        ]
        return _extraer_miembros_comprimido(pares, extractores_internos)


_EXTRACTORES = {
    ".pdf": _extraer_pdf,
    ".doc": _extraer_doc_legado,
    ".docx": _extraer_docx,
    ".xls": _extraer_xls_legado,
    ".xlsx": _extraer_xlsx,
    ".odt": _extraer_odt,
    ".zip": _extraer_zip,
    ".7z": _extraer_7z,
    ".rar": _extraer_rar,
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
        return DocumentoExtraido(nombre=nombre, url=url, tipo=ext, error=f"Extensión no soportada: {ext}")

    try:
        texto, paginas = extractor(path)
        return DocumentoExtraido(nombre=nombre, url=url, tipo=ext, texto=texto, paginas_leidas=paginas)
    except Exception as e:  # noqa: BLE001 - queremos degradar, no abortar el pipeline
        return DocumentoExtraido(nombre=nombre, url=url, tipo=ext, error=str(e))


def _correr_target_y_encolar(func, args: tuple, queue: "multiprocessing.Queue") -> None:
    """Target genérico del subproceso: corre func(*args) y pone el resultado
    en la queue. Función de módulo (no closure/lambda) para que
    multiprocessing pueda importarla en el hijo bajo el contexto "spawn".
    """
    queue.put(func(*args))


def ejecutar_con_timeout_duro(func: Callable, args: tuple, timeout_segundos: int, timeout_exitcode_a: Callable):
    """Corre func(*args) en un subproceso aparte y lo mata si no termina
    dentro de timeout_segundos.

    Usa multiprocessing (no concurrent.futures.ThreadPoolExecutor) a
    propósito: un cuelgue CPU-bound dentro de una librería en C/Python puro
    (ej. pypdf.extract_text() con una fuente de codificación rara — ver
    TIMEOUT_EXTRACCION_SEGUNDOS más arriba) no coopera con timeouts a nivel
    de threading, porque el GIL nunca se libera. Hace falta poder matar el
    proceso de verdad.

    func y sus args deben ser picklables (se pasan al subproceso vía
    multiprocessing bajo contexto "spawn"). Devuelve (resultado, se_agoto):
    si se_agoto es True, resultado es lo que devuelve timeout_exitcode_a()
    (para que el caller arme su propio objeto de error con sus propios
    campos, en vez de que esta función genérica conozca DocumentoExtraido).
    """
    ctx = multiprocessing.get_context("spawn")
    queue: "multiprocessing.Queue" = ctx.Queue()
    proceso = ctx.Process(target=_correr_target_y_encolar, args=(func, args, queue), daemon=True)
    proceso.start()
    proceso.join(timeout_segundos)

    if proceso.is_alive():
        proceso.kill()  # SIGKILL — terminate() (SIGTERM) podría no alcanzar si está trabado en código C
        proceso.join(5)
        return timeout_exitcode_a(None), True

    try:
        # get(timeout=...) en vez de get_nowait(): el feeder thread de la
        # Queue puede tardar un instante en terminar de escribir al pipe
        # después de que el proceso hijo ya se reportó como no-vivo — con
        # get_nowait() eso es una carrera real (Empty espurio).
        return queue.get(timeout=5), False
    except Exception:
        return timeout_exitcode_a(proceso.exitcode), False


def extraer_archivo_local_con_timeout(
    path: Path,
    nombre: Optional[str] = None,
    url: str = "",
    timeout_segundos: int = TIMEOUT_EXTRACCION_SEGUNDOS,
) -> DocumentoExtraido:
    """Igual que extraer_archivo_local(), pero corriendo la extracción en un
    subproceso aparte con un timeout duro.

    extraer_archivo_local() delega en librerías de terceros (pypdf,
    pytesseract, etc.) cuyo tiempo de ejecución no controlamos — un solo
    documento con una codificación/fuente problemática puede colgarse
    indefinidamente (ver comentario de TIMEOUT_EXTRACCION_SEGUNDOS más
    arriba, con la evidencia real de la corrida #206).
    """
    nombre_final = nombre or path.name
    tipo = path.suffix.lower()

    def _error_timeout(exitcode):
        if exitcode is None:
            return DocumentoExtraido(
                nombre=nombre_final, url=url, tipo=tipo,
                error=(
                    f"Extracción de texto excedió el timeout de {timeout_segundos}s "
                    "(probablemente una fuente/codificación problemática en el documento) — "
                    "se omite este documento puntual, el resto del pliego se sigue analizando."
                ),
            )
        return DocumentoExtraido(
            nombre=nombre_final, url=url, tipo=tipo,
            error=f"El subproceso de extracción terminó sin resultado (exit code {exitcode}).",
        )

    resultado, _se_agoto = ejecutar_con_timeout_duro(
        extraer_archivo_local, (path, nombre_final, url), timeout_segundos, _error_timeout,
    )
    return resultado


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
        return extraer_archivo_local_con_timeout(tmp_path, nombre=nombre, url=url)
    finally:
        tmp_path.unlink(missing_ok=True)


def encontrar_links_documentos(html: str, base_url: str = "") -> list[str]:
    """Busca links a documentos descargables (pdf/doc/xls/imagen) en una página HTML."""
    patron = r'href=["\']([^"\']+\.(?:pdf|docx?|xlsx?|odt|zip|7z|rar|png|jpe?g|tiff?))["\']'
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
