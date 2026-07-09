"""Carga centralizada de configuración y base de conocimiento.

Todos los módulos (monitor, analyzer, risk, checklist, pricing, report)
leen la configuración a través de este módulo en vez de abrir archivos
YAML por su cuenta. Mantiene un único punto de verdad para rutas y evita
repetir lógica de carga/caché en cada script.
"""
from __future__ import annotations

import functools
import os
import re
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


# Listas de knowledge/keywords.yaml que son señal FUERTE: una sola
# coincidencia dispara relevancia por sí sola (ver header del propio YAML
# para la justificación de por qué "lugares_uso" y "aplicaciones" quedan
# afuera de esta lista — son señal débil, ver GRUPOS_CONTEXTO más abajo).
_GRUPOS_SEÑAL_FUERTE = [
    "terminologia_pliegos",
    "materiales",
    "normativas",
    "marcas",
    "errores_comunes",
    "abreviaturas",
]

# Listas que NUNCA disparan relevancia por sí solas — son demasiado
# genéricas (aparecen en casi cualquier licitación pública de Uruguay
# sin importar el rubro). Se usan solo como contexto adicional una vez
# que la licitación ya fue marcada relevante por una señal fuerte.
_GRUPOS_CONTEXTO = ["lugares_uso", "aplicaciones"]


def todas_las_palabras_clave() -> list[str]:
    """Aplana knowledge/keywords.yaml en la lista de términos "señal
    fuerte" usada para decidir si una licitación es relevante. NO incluye
    lugares_uso/aplicaciones (ver palabras_clave_contexto()).
    """
    kw = keywords()
    terminos: list[str] = []
    for datos_categoria in kw.get("categorias", {}).values():
        terminos.extend(datos_categoria.get("keywords", []))
    for grupo in _GRUPOS_SEÑAL_FUERTE:
        terminos.extend(kw.get(grupo, []))
    return terminos


def palabras_clave_contexto() -> dict[str, list[str]]:
    """lugares_uso / aplicaciones: nunca disparan relevancia solas.
    analyzer.identificar_contexto() las usa para enriquecer el informe
    únicamente después de que ya hubo un match de señal fuerte.
    """
    kw = keywords()
    return {grupo: kw.get(grupo, []) for grupo in _GRUPOS_CONTEXTO}


_ETIQUETAS_CATEGORIA = {
    "pisos_vinilicos": "Pisos vinílicos",
    "pisos_spc": "Pisos SPC",
    "pisos_flotantes": "Pisos flotantes/laminados",
    "pisos_madera": "Pisos de madera",
    "pisos_goma": "Pisos de goma",
    "pisos_deportivos": "Pisos deportivos",
    "cesped_sintetico": "Césped sintético",
    "insumos_canchas": "Insumos para canchas",
    "alfombras": "Alfombras",
    "moquettes": "Moquettes",
    "felpudos": "Felpudos y camineros",
    "paneles_revestimientos": "Paneles y revestimientos de pared",
    "piedrafina": "Piedrafina",
    "jardines_verticales": "Jardines verticales",
    "decks_exterior": "Deck y exterior",
    "accesorios": "Accesorios de instalación",
    "adhesivos": "Adhesivos",
    "servicios": "Servicios",
    "terminologia_pliegos": "Terminología genérica del pliego (revisar manualmente qué producto aplica)",
    "materiales": "Material mencionado (revisar contexto)",
    "normativas": "Normativa/certificación mencionada",
    "marcas": "Marca de mercado mencionada",
    "errores_comunes": "Variante/error ortográfico de un término del rubro",
    "abreviaturas": "Abreviatura técnica del rubro",
}


def etiqueta_categoria(categoria: str) -> str:
    """Nombre legible de una categoría de knowledge/keywords.yaml, para
    mostrar en informes en vez del slug interno (ej. 'pisos_vinilicos').
    """
    return _ETIQUETAS_CATEGORIA.get(categoria, categoria)


def palabras_clave_por_categoria() -> dict[str, list[str]]:
    """Como todas_las_palabras_clave(), pero conservando a qué categoría
    pertenece cada término — usado por analyzer.identificar_productos()
    para mostrar "categoría (\"término\"): ...fragmento..." en el informe.
    """
    kw = keywords()
    categorias = {
        nombre: datos.get("keywords", []) for nombre, datos in kw.get("categorias", {}).items()
    }
    for grupo in _GRUPOS_SEÑAL_FUERTE:
        lista = kw.get(grupo, [])
        if lista:
            categorias[grupo] = lista
    return categorias


# Términos cortos (<=5 caracteres, sin espacios) matchean por límite de
# palabra en vez de substring plano: con la ampliación de knowledge/
# keywords.yaml para incluir abreviaturas técnicas (spc, pu, eva, sbr...),
# un substring search ingenuo generaría falsos positivos absurdos (ej.
# "pu" dentro de "publico"). Los términos largos/multi-palabra siguen
# usando substring, que ya es suficientemente específico.
_UMBRAL_TERMINO_CORTO = 5
_regex_cache: dict[str, re.Pattern] = {}


def _es_termino_corto(kw: str) -> bool:
    return len(kw) <= _UMBRAL_TERMINO_CORTO and " " not in kw


def coincide_palabra_clave(texto_lower: str, kw: str) -> bool:
    """True si `kw` aparece en `texto_lower` (ya en minúsculas). Para
    términos cortos exige límite de palabra; para el resto, substring.
    """
    kw_lower = kw.lower()
    if not _es_termino_corto(kw_lower):
        return kw_lower in texto_lower
    patron = _regex_cache.get(kw_lower)
    if patron is None:
        patron = re.compile(r"(?<![a-záéíóúñ0-9])" + re.escape(kw_lower) + r"(?![a-záéíóúñ0-9])")
        _regex_cache[kw_lower] = patron
    return bool(patron.search(texto_lower))


def buscar_palabra_clave(texto_lower: str, kw: str) -> int:
    """Como coincide_palabra_clave(), pero devuelve el índice del match (o
    -1) — usado donde hace falta la posición para extraer un fragmento.
    """
    kw_lower = kw.lower()
    if not _es_termino_corto(kw_lower):
        return texto_lower.find(kw_lower)
    patron = _regex_cache.get(kw_lower)
    if patron is None:
        patron = re.compile(r"(?<![a-záéíóúñ0-9])" + re.escape(kw_lower) + r"(?![a-záéíóúñ0-9])")
        _regex_cache[kw_lower] = patron
    m = patron.search(texto_lower)
    return m.start() if m else -1


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
