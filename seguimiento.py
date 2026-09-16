"""Lista de licitaciones que el usuario marcó explícitamente para
seguimiento (ver docs/index.html, botones "🔔 Seguir esta licitación" /
"Dejar de seguir", y .github/workflows/seguimiento.yml +
seguimiento_issue.py, que agregan/quitan entradas acá a partir de un
GitHub Issue abierto desde esos botones).

Por qué existe esto además de monitor.obtener_licitaciones()/vistos: el
mecanismo real de ARCE para aclaraciones/modificaciones sobre un llamado
ya visto (releases "aclar_llamado-{id}"/"ajuste_llamado-{id}"/etc. en el
mismo feed RSS, ligados al mismo id_compra que el "llamado-{id}"
original — ver monitor._tipo_release()) está documentado como PENDIENTE
en monitor.obtener_licitaciones(): desde que se dejó de re-pedir el
detalle de TODO llamado ya visto (para no re-descargar el detalle de
miles de releases en cada corrida, ver ese docstring), monitor.py ya no
vuelve a mirar un llamado una vez que entra en vistos, sin importar si
después tiene una aclaración real.

Revisar esto para los ~600+ llamados ya vistos sería carísimo (implica un
fetch de detalle por release nuevo encontrado, en el peor caso). Para un
puñado de llamados marcados a mano por interés explícito del usuario, en
cambio, es barato — así que esto solo cubre esos, no un reemplazo general
del punto pendiente de arriba.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import requests

import config.settings as settings
import parser as parser_mod

_BASE_DIR = Path(__file__).resolve().parent
SEGUIMIENTO_PATH = _BASE_DIR / "docs" / "data" / "seguimiento.json"

# La publicación original ("llamado-{id}") no es una "novedad" para
# alguien que ya la vio y decidió seguirla — solo interesan los releases
# que aparecen DESPUÉS de esa publicación.
_TIPO_IGNORADO = "llamado"

_ETIQUETAS_TIPO = {
    "aclar_llamado": "Aclaración",
    "ajuste_llamado": "Ajuste / modificación",
    "adjudicacion": "Adjudicación",
    "recomendacion": "Recomendación de adjudicación",
    "acta_apertura": "Acta de apertura",
    "cancelacion": "Cancelación",
    "prorroga": "Prórroga",
}


def etiqueta_tipo(tipo: str) -> str:
    """Nombre legible para un tipo de release de ARCE (ver
    monitor._tipo_release()). Los tipos que no están en _ETIQUETAS_TIPO
    (no confirmados contra evidencia real) se muestran igual, solo que
    con el nombre crudo del feed en vez de una traducción — nunca se
    inventa una descripción para un tipo que no se conoce.
    """
    return _ETIQUETAS_TIPO.get(tipo, tipo.replace("_", " ").capitalize())


def _meses_a_relevar(ahora: datetime) -> list[tuple[int, int]]:
    """Mismo criterio que monitor._meses_a_relevar() (duplicado acá
    deliberadamente, no importado, para que este módulo no dependa de
    importar monitor — monitor SÍ importa este módulo, e importar en el
    sentido contrario crearía un ciclo)."""
    anio, mes = ahora.year, ahora.month
    anio_ant, mes_ant = (anio - 1, 12) if mes == 1 else (anio, mes - 1)
    return [(anio_ant, mes_ant), (anio, mes)]


def _tipo_y_id(guid: str) -> tuple[str, str] | None:
    m = re.match(r"^([a-z_]+)-(\d+)", guid)
    if not m:
        return None
    return m.group(1), m.group(2)


def cargar() -> dict:
    if not SEGUIMIENTO_PATH.exists():
        return {}
    with open(SEGUIMIENTO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar(seguimiento: dict) -> None:
    SEGUIMIENTO_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SEGUIMIENTO_PATH, "w", encoding="utf-8") as f:
        json.dump(seguimiento, f, ensure_ascii=False, indent=2, sort_keys=True)


def revisar(seguimiento: dict) -> list[dict]:
    """Recorre el feed RSS mensual (mes actual + anterior, igual criterio
    que monitor.obtener_licitaciones()) buscando, para cada id_compra en
    `seguimiento`, cualquier release que NO sea el "llamado" original y
    que todavía no se haya notificado (seguimiento[id]["guids_notificados"]).

    Devuelve una lista de dicts listos para el email (ver
    monitor.enviar_email(), sección de seguimiento) y actualiza
    `seguimiento` IN-PLACE (agrega el guid a guids_notificados y refresca
    "ultima_revision") — quien llama a esto es responsable de persistir
    con guardar() después si la lista devuelta no está vacía.

    Nunca lanza por una falla de red: una corrida sin conectividad al
    feed simplemente no encuentra novedades esta vez (se reintenta en la
    corrida siguiente), no debe tirar abajo el resto del pipeline.
    """
    if not seguimiento:
        return []

    import xml.etree.ElementTree as ET

    novedades: list[dict] = []

    for anio, mes in _meses_a_relevar(datetime.now()):
        url_mes = f"{settings.RSS_URL}/{anio}/{mes:02d}"
        try:
            r = requests.get(url_mes, headers=parser_mod.HEADERS, timeout=60)
        except Exception as e:  # noqa: BLE001
            print(f"  Seguimiento: error consultando {url_mes}: {e}")
            continue
        if r.status_code != 200:
            continue
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            continue
        channel = root.find("channel")
        if channel is None:
            continue

        for item in channel.findall("item"):
            guid = item.findtext("guid", default="") or item.findtext("title", default="")
            parsed = _tipo_y_id(guid)
            if not parsed:
                continue
            tipo, id_compra = parsed
            if tipo == _TIPO_IGNORADO or id_compra not in seguimiento:
                continue

            entrada = seguimiento[id_compra]
            if guid in entrada.get("guids_notificados", []):
                continue  # ya se avisó de este release en una corrida anterior

            link = item.findtext("link", default="")
            descripcion_release = ""
            try:
                rr = requests.get(link, headers=parser_mod.HEADERS, timeout=15)
                if rr.status_code == 200:
                    rel = rr.json()
                    if isinstance(rel, dict) and isinstance(rel.get("releases"), list) and rel["releases"]:
                        rel = rel["releases"][0]
                    tender = rel.get("tender", {}) if isinstance(rel, dict) else {}
                    descripcion_release = tender.get("description") or ""
            except Exception as e:  # noqa: BLE001
                print(f"  Seguimiento: error leyendo release {link}: {e}")

            novedades.append({
                "id_compra": id_compra,
                "tipo": tipo,
                "titulo": entrada.get("titulo") or f"Llamado {id_compra}",
                "organismo": entrada.get("organismo"),
                "descripcion_release": descripcion_release,
                "url_ficha": entrada.get("url_ficha")
                or f"https://www.comprasestatales.gub.uy/consultas/detalle/id/{id_compra}",
                "url_release": link,
            })
            entrada.setdefault("guids_notificados", []).append(guid)
            entrada["ultima_revision"] = datetime.now().isoformat(timespec="seconds")

    return novedades
