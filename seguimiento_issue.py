"""Procesa el GitHub Issue que dispara .github/workflows/seguimiento.yml
(abierto desde docs/index.html, botones "🔔 Seguir esta licitación" /
"Dejar de seguir") y agrega/quita la licitación correspondiente de
docs/data/seguimiento.json.

No se llama a mano — lo invoca ese workflow, con el título, cuerpo y
etiquetas del issue como variables de entorno (ISSUE_TITLE, ISSUE_BODY,
ISSUE_LABELS, esta última una lista separada por comas). Esas variables
llegan directo del propio issue de GitHub: NUNCA se ejecuta nada de su
contenido, solo se lo parsea como texto plano para extraer el número de
licitación y algunos campos informativos.

Escribe:
  - docs/data/seguimiento.json actualizado (si corresponde).
  - comentario_issue.txt: el mensaje que el workflow postea de vuelta en
    el issue antes de cerrarlo.
  - $GITHUB_OUTPUT: cambio=true/false, para que el workflow sepa si hay
    algo nuevo que commitear.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

import seguimiento

COMENTARIO_PATH = Path(__file__).resolve().parent / "comentario_issue.txt"


def _extraer_id(titulo: str, cuerpo: str) -> str | None:
    # El botón del visor arma el título como "seguir: {id}" / "dejar de
    # seguir: {id}" — se busca el número ahí primero. Si alguien abrió el
    # issue a mano y el título no trae un número, se cae a buscar el
    # patrón de la ficha ARCE ("/id/<numero>") en el cuerpo, y como
    # último recurso cualquier número largo suelto en el cuerpo.
    m = re.search(r"(\d{4,})", titulo or "")
    if m:
        return m.group(1)
    m = re.search(r"/id/(\d+)", cuerpo or "")
    if m:
        return m.group(1)
    m = re.search(r"(\d{4,})", cuerpo or "")
    return m.group(1) if m else None


def _extraer_campo(cuerpo: str, etiqueta: str) -> str:
    # El botón del visor arma el cuerpo como líneas "Etiqueta: valor"
    # (ver docs/index.html) — ej. "Título: ...", "Organismo: ...",
    # "Ficha: https://...".
    m = re.search(rf"^{re.escape(etiqueta)}:\s*(.+)$", cuerpo or "", re.MULTILINE)
    return m.group(1).strip() if m else ""


def _es_baja(titulo: str) -> bool:
    return bool(re.match(r"^\s*dejar\b", titulo or "", re.IGNORECASE))


def main() -> None:
    titulo_issue = os.environ.get("ISSUE_TITLE", "")
    cuerpo = os.environ.get("ISSUE_BODY", "")

    id_compra = _extraer_id(titulo_issue, cuerpo)
    datos = seguimiento.cargar()
    cambio = False

    if id_compra is None:
        mensaje = (
            'No pude identificar el número de licitación en este issue. '
            'Usá el botón "🔔 Seguir esta licitación" (o "Dejar de seguir") del visor '
            "en vez de crear el issue a mano — cierro este issue, podés volver a "
            "intentarlo desde ahí."
        )
    elif _es_baja(titulo_issue):
        if id_compra in datos:
            titulo_lic = datos[id_compra].get("titulo") or f"Llamado {id_compra}"
            del datos[id_compra]
            cambio = True
            mensaje = (
                f"Dejaste de seguir **{titulo_lic}** ({id_compra}). Ya no vas a recibir "
                "avisos de aclaraciones, ajustes o adjudicaciones sobre este llamado."
            )
        else:
            mensaje = f"La licitación {id_compra} no estaba en tu lista de seguimiento — no había nada que quitar."
    else:
        titulo_lic = _extraer_campo(cuerpo, "Título") or f"Llamado {id_compra}"
        organismo = _extraer_campo(cuerpo, "Organismo")
        url_ficha = (
            _extraer_campo(cuerpo, "Ficha")
            or f"https://www.comprasestatales.gub.uy/consultas/detalle/id/{id_compra}"
        )
        previa = datos.get(id_compra, {})
        datos[id_compra] = {
            "titulo": titulo_lic,
            "organismo": organismo,
            "url_ficha": url_ficha,
            "marcado_en": previa.get("marcado_en") or datetime.now().isoformat(timespec="seconds"),
            "guids_notificados": previa.get("guids_notificados", []),
            "ultima_revision": previa.get("ultima_revision"),
        }
        cambio = True
        mensaje = (
            f"✅ Ahora estás siguiendo **{titulo_lic}** ({id_compra}). Si ARCE publica una "
            "aclaración, un ajuste o una adjudicación sobre este llamado, te va a llegar "
            "destacado en el próximo email del monitoreo (corre 3 veces al día)."
        )

    if cambio:
        seguimiento.guardar(datos)

    COMENTARIO_PATH.write_text(mensaje, encoding="utf-8")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"cambio={'true' if cambio else 'false'}\n")


if __name__ == "__main__":
    main()
