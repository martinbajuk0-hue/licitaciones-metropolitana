"""Carga centralizada de configuración y base de conocimiento.

Todos los módulos (monitor, analyzer, risk, checklist, pricing, report)
leen la configuración a través de este módulo en vez de abrir archivos
YAML por su cuenta. Mantiene un único punto de verdad para rutas y evita
repetir lógica de carga/caché en cada script.
"""
from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"
PROMPTS_DIR = BASE_DIR / "prompts"
TEMPLATES_DIR = BASE_DIR / "templates"

DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

ARCHIVO_VISTOS = DATA_DIR / "licitaciones_vistas.json"

OCDS_URL = "https://www.comprasestatales.gub.uy/ocds/releases"
RSS_URL = "https://www.comprasestatales.gub.uy/ocds/rss"


def _cargar_yaml(ruta: Path) -> Any:
    if not ruta.exists():
        raise FileNotFoundError(
            f"No se encontró {ruta}. Este archivo es parte de la base de "
            "conocimiento requerida (ver docs/ARQUITECTURA.md)."
        )
    with open(ruta, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@functools.lru_cache(maxsize=None)
def empresa() -> dict:
    return _cargar_yaml(CONFIG_DIR / "empresa.yaml")


@functools.lru_cache(maxsize=None)
def keywords() -> dict:
    return _cargar_yaml(KNOWLEDGE_DIR / "keywords.yaml")


@functools.lru_cache(maxsize=None)
def sinonimos() -> dict:
    return _cargar_yaml(KNOWLEDGE_DIR / "sinonimos.yaml")


@functools.lru_cache(maxsize=None)
def organismos() -> dict:
    return _cargar_yaml(KNOWLEDGE_DIR / "organismos.yaml")


@functools.lru_cache(maxsize=None)
def productos() -> dict:
    return _cargar_yaml(KNOWLEDGE_DIR / "productos.yaml")


@functools.lru_cache(maxsize=None)
def precios() -> dict:
    return _cargar_yaml(KNOWLEDGE_DIR / "precios.yaml")


def todas_las_palabras_clave() -> list[str]:
    """Aplana knowledge/keywords.yaml en una lista única de términos."""
    kw = keywords()
    terminos: list[str] = []
    for lista in kw.get("productos", {}).values():
        terminos.extend(lista)
    terminos.extend(kw.get("terminologia_pliegos", []))
    return terminos


def palabras_clave_por_categoria() -> dict[str, list[str]]:
    categorias = dict(keywords().get("productos", {}))
    terminologia = keywords().get("terminologia_pliegos", [])
    if terminologia:
        categorias["terminologia_pliegos"] = terminologia
    return categorias


# ─── Variables de entorno / secretos ──────────────────────────────────────
# Nunca se leen directamente en los módulos: todo pasa por acá para que
# quede documentado qué variables de entorno usa el sistema.

def gmail_user() -> str | None:
    return os.environ.get("GMAIL_USER")


def gmail_app_password() -> str | None:
    return os.environ.get("GMAIL_APP_PASSWORD")


def email_destino() -> str | None:
    return os.environ.get("EMAIL_DESTINO") or gmail_user()


def anthropic_api_key() -> str | None:
    """Si está seteada, analyzer.py usa la API de Claude para el análisis
    profundo del pliego (resumen ejecutivo, riesgos narrativos). Si no está
    seteada, el sistema sigue funcionando con extracción basada en reglas
    (regex + keywords), marcando explícitamente qué requiere revisión manual.
    """
    return os.environ.get("ANTHROPIC_API_KEY")


def umbral_estrellas() -> dict:
    """Umbrales de puntaje usados por report.py para la clasificación ★.
    Configurable por variable de entorno para ajustar sin tocar código.
    """
    return {
        5: int(os.environ.get("UMBRAL_5_ESTRELLAS", 85)),
        4: int(os.environ.get("UMBRAL_4_ESTRELLAS", 65)),
        3: int(os.environ.get("UMBRAL_3_ESTRELLAS", 45)),
        2: int(os.environ.get("UMBRAL_2_ESTRELLAS", 25)),
    }
