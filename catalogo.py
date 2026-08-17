"""Persistencia liviana para el visor web (docs/index.html).

Hasta ahora el pipeline (monitor.py) analizaba cada llamado y el resultado
se perdía apenas terminaba la corrida: el informe se guardaba en
reports/*.md (gitignored, vive solo en el runner efímero de GitHub
Actions) y lo único que llegaba a la persona era el email. No había forma
de volver a ver "qué encontramos la semana pasada" sin buscar en la
bandeja de entrada.

Este módulo guarda, para cada llamado que pasó el filtro de relevancia:
  - un resumen (organismo, fechas clave, categoría, score, links) en
    docs/data/llamados.json — un único JSON versionado en git, no en cache
    ni gitignored, que es lo que lee docs/index.html vía fetch();
  - el informe completo en Markdown en docs/informes/{id}.md, también
    versionado en git, para que el visor lo pueda mostrar completo.

No hay backend: GitHub Pages sirve docs/ como sitio estático, y el
workflow de GitHub Actions (.github/workflows/monitor.yml) hace commit +
push de estos dos archivos/carpetas después de cada corrida — el mismo
mecanismo que ya se usaba para actualizar data/licitaciones_vistas.json,
solo que ahora versionado en vez de cacheado (el cache de Actions es
efímero y no served para servir un sitio).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import config.settings as settings
import report as report_mod

_BASE_DIR = Path(__file__).resolve().parent
CATALOGO_DIR = _BASE_DIR / "docs" / "data"
INFORMES_DIR = _BASE_DIR / "docs" / "informes"
CATALOGO_PATH = CATALOGO_DIR / "llamados.json"


def _slug(id_: str) -> str:
    """El id de un llamado puede ser un ocid (con ':' y '-') o un hash
    md5 (cuando se usó el fallback RSS) — nunca un nombre de archivo
    seguro de por sí, así que se sanitiza antes de usarlo como filename.
    """
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", id_)[:120] or "llamado"


def _cargar_catalogo() -> dict:
    if not CATALOGO_PATH.exists():
        return {}
    with open(CATALOGO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _guardar_catalogo(data: dict) -> None:
    CATALOGO_DIR.mkdir(parents=True, exist_ok=True)
    with open(CATALOGO_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)


def registrar_llamado(lic: dict, informe: report_mod.InformeLicitacion) -> None:
    """Registra (o re-registra) un llamado relevante en el catálogo del
    visor y guarda su informe completo versionado en git.

    Se llama para TODO llamado que pasó el filtro de relevancia de
    es_relevante() — deliberadamente ANTES del filtro de
    SCORE_MINIMO_EMAIL: ese filtro decide qué llega por mail, no qué
    aparece en el visor. La idea del visor es poder ver el panorama
    completo (incluidos los de score bajo) sin depender del email.
    """
    catalogo = _cargar_catalogo()
    id_ = lic["id"]
    slug = _slug(id_)

    INFORMES_DIR.mkdir(parents=True, exist_ok=True)
    (INFORMES_DIR / f"{slug}.md").write_text(informe.markdown, encoding="utf-8")

    categorias = sorted({p.categoria for p in informe.productos})
    etiquetas = sorted({settings.etiqueta_categoria(c) for c in categorias})

    previa = catalogo.get(id_, {})
    catalogo[id_] = {
        "id": id_,
        "titulo": lic["titulo"],
        "organismo": informe.campos.organismo,
        "numero_licitacion": informe.campos.numero_licitacion,
        "fecha_publicacion": lic.get("fecha"),
        "fecha_apertura": informe.campos.fecha_apertura,
        "fecha_consultas": informe.campos.fecha_consultas,
        "fecha_visita": informe.campos.fecha_visita,
        "categorias": categorias,
        "categorias_etiquetas": etiquetas,
        "keyword": lic.get("keyword"),
        "fuente_match": lic.get("fuente"),
        "score": informe.clasificacion.puntaje,
        "nivel": informe.clasificacion.nivel,
        "simbolo": informe.clasificacion.simbolo,
        "etiqueta_clasificacion": informe.clasificacion.etiqueta,
        "url_ficha": lic.get("url"),
        "documentos": lic.get("documentos") or [],
        "informe": f"informes/{slug}.md",
        "cambio_detectado": False,
        "primera_deteccion": previa.get("primera_deteccion") or datetime.now().isoformat(timespec="seconds"),
        "ultima_actualizacion": datetime.now().isoformat(timespec="seconds"),
        "notificaciones": previa.get("notificaciones", 0) + 1,
    }
    _guardar_catalogo(catalogo)


def registrar_modificacion(lic: dict) -> None:
    """Para aclaraciones/cambios de título-descripción detectados sobre un
    llamado ya visto (rama 'modificadas' de monitor.main()): a diferencia
    de registrar_llamado(), acá NO hay informe nuevo — monitor.py no
    vuelve a leer el pliego en este caso — así que solo se actualiza la
    marca de "hubo un cambio" sobre la entrada existente. Si el llamado
    nunca había pasado por registrar_llamado() (por ejemplo, la primera
    vez que se vio no era relevante y ahora el cambio sí lo hace parecer
    relevante, algo que monitor.py hoy no re-evalúa — ver PENDIENTE en
    monitor.obtener_licitaciones()), no hay entrada que actualizar y no
    se crea una a medias.
    """
    catalogo = _cargar_catalogo()
    id_ = lic["id"]
    if id_ not in catalogo:
        return
    catalogo[id_]["cambio_detectado"] = True
    catalogo[id_]["ultima_actualizacion"] = datetime.now().isoformat(timespec="seconds")
    catalogo[id_]["notificaciones"] = catalogo[id_].get("notificaciones", 0) + 1
    _guardar_catalogo(catalogo)
