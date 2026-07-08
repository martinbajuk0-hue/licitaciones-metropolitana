"""Paso 1-4 del flujo: revisar diariamente nuevos llamados en Compras
Estatales (ARCE), detectar aclaraciones/modificaciones sobre licitaciones
ya vistas, descargar la documentación y correr el pipeline completo
(analyzer + risk + checklist + report) sobre las que resulten relevantes.

Uso:
    python monitor.py              # corrida normal (usada por el cron de GitHub Actions)
    python monitor.py --sin-email  # corre el pipeline pero no envía email (debug local)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

import requests

import config.settings as settings
import parser as parser_mod
import report as report_mod

MAX_DOCUMENTOS_POR_LICITACION = 5


# ─── Estado (licitaciones ya vistas) ──────────────────────────────────────
# Formato: { id: {"titulo": str, "hash": str, "primera_deteccion": iso, "notificaciones": int} }
# Compatible hacia atrás: si el archivo viejo era una lista simple de ids,
# se migra automáticamente al formato nuevo en la primera corrida.

def cargar_vistos() -> dict:
    if not settings.ARCHIVO_VISTOS.exists():
        return {}
    with open(settings.ARCHIVO_VISTOS, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):  # formato legado
        return {uid: {"titulo": "", "hash": "", "primera_deteccion": "", "notificaciones": 1} for uid in data}
    return data


def guardar_vistos(vistos: dict) -> None:
    with open(settings.ARCHIVO_VISTOS, "w", encoding="utf-8") as f:
        json.dump(vistos, f, ensure_ascii=False, indent=2)


def _hash_contenido(lic: dict) -> str:
    return hashlib.md5((lic["titulo"] + "|" + lic["descripcion"]).encode("utf-8")).hexdigest()


# ─── Fetch de licitaciones (OCDS / RSS) ───────────────────────────────────

def obtener_licitaciones() -> list[dict]:
    """Intenta OCDS releases; si falla, usa el RSS.

    Evidencia recogida corriendo esto en producción (ver commits de este
    branch): el feed RSS de comprasestatales.gub.uy NO trae texto de
    negocio en el <item> — solo un identificador interno como <title>
    (ej. "id_compra:1354587,release_id:adjudicacion-1354587"), <category>
    y <link> al release individual en JSON. Por eso acá se sigue el link
    de cada item category=="llamado" (nuevos llamados — lo que pide el
    paso 1 del flujo) para obtener el título/descripción reales.

    PENDIENTE (no implementado, no inventado): aclar_llamado/adjudicacion/
    ajuste_* no se procesan todavía. El feed sí permite correlacionarlos
    con el id_compra del llamado original (visible en el propio <title>),
    pero vincularlos para el paso 2 (detectar aclaraciones/modificaciones/
    adjudicaciones sobre licitaciones ya vistas) requiere diseño propio —
    hoy monitor.py solo cubre "detectar llamados nuevos".
    """
    licitaciones = []

    try:
        r = requests.get(settings.OCDS_URL, headers=parser_mod.HEADERS, timeout=30)
        print(f"  OCDS: status={r.status_code} content-type={r.headers.get('content-type')} body[:300]={r.text[:300]!r}")
        if r.status_code == 200:
            data = r.json()
            releases = data if isinstance(data, list) else data.get("releases", [])
            print(f"  OCDS: {len(releases)} release(s) en la respuesta")
            for rel in releases:
                tender = rel.get("tender", {})
                title = tender.get("title", "") or rel.get("title", "")
                desc = tender.get("description", "") or ""
                ocid = rel.get("ocid", "") or rel.get("id", "")
                date = rel.get("date", "")[:10] if rel.get("date") else ""
                url = (
                    f"https://www.comprasestatales.gub.uy/consultas/detalle/id/{ocid.split('-')[-1]}"
                    if ocid else ""
                )
                licitaciones.append({"id": ocid, "titulo": title, "descripcion": desc, "fecha": date, "url": url})
            if licitaciones:
                return licitaciones
    except Exception as e:  # noqa: BLE001
        print(f"OCDS JSON falló: {e}")

    try:
        import xml.etree.ElementTree as ET

        r = requests.get(settings.RSS_URL, headers=parser_mod.HEADERS, timeout=30)
        print(f"  RSS: status={r.status_code} content-type={r.headers.get('content-type')} body[:300]={r.text[:300]!r}")
        root = ET.fromstring(r.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        channel = root.find("channel")

        if channel is None:
            for entry in root.findall("atom:entry", ns):
                title = entry.findtext("atom:title", default="", namespaces=ns)
                link = entry.findtext("atom:id", default="", namespaces=ns)
                date = (entry.findtext("atom:updated", default="", namespaces=ns) or "")[:10]
                uid = hashlib.md5(link.encode()).hexdigest()
                licitaciones.append({"id": uid, "titulo": title, "descripcion": "", "fecha": date, "url": link})
            return licitaciones

        todos_los_items = channel.findall("item")

        def _tipo_release(item) -> str:
            # El <category> del feed no distingue de forma confiable
            # "llamado" (confirmado con evidencia: un item de adjudicación
            # trae category="award"). El release_id embebido en <guid>/
            # <title> sí es confiable: "llamado-123", "adjudicacion-123",
            # "aclar_llamado-123-0", "ajuste_llamado-123", etc.
            guid = item.findtext("guid", default="") or item.findtext("title", default="")
            m = re.match(r"^([a-z_]+)-\d", guid)
            return m.group(1) if m else ""

        items_llamado = [it for it in todos_los_items if _tipo_release(it) == "llamado"]
        tipos_vistos = sorted({_tipo_release(it) for it in todos_los_items})
        print(f"  RSS: {len(todos_los_items)} item(s) totales, {len(items_llamado)} de tipo 'llamado'. Tipos vistos: {tipos_vistos}")

        primer_release_impreso = False
        for item in items_llamado:
            link = item.findtext("link", default="")
            guid = item.findtext("guid", default="") or link
            date = item.findtext("pubDate", default="")
            uid = hashlib.md5(guid.encode()).hexdigest()

            titulo, desc = "", ""
            try:
                rr = requests.get(link, headers=parser_mod.HEADERS, timeout=15)
                if not primer_release_impreso:
                    print(f"  RSS->release: status={rr.status_code} body[:1500]={rr.text[:1500]!r}")
                    primer_release_impreso = True
                if rr.status_code == 200:
                    rel = rr.json()
                    # El JSON es un release package OCDS: uri/version/publisher
                    # a nivel superior, y la release real (con tender/parties)
                    # anidada en "releases": [...]. Confirmado con evidencia
                    # del log — el primer intento buscaba "tender" en el nivel
                    # equivocado y por eso siempre volvía vacío.
                    if isinstance(rel, dict) and isinstance(rel.get("releases"), list) and rel["releases"]:
                        rel = rel["releases"][0]
                    tender = rel.get("tender", {}) if isinstance(rel, dict) else {}
                    titulo = tender.get("title") or (rel.get("title") if isinstance(rel, dict) else "") or ""
                    desc = tender.get("description") or ""
            except Exception as e:  # noqa: BLE001
                if not primer_release_impreso:
                    print(f"  RSS->release: error obteniendo {link}: {e}")
                    primer_release_impreso = True

            licitaciones.append({
                "id": uid,
                "titulo": titulo or item.findtext("title", default=""),
                "descripcion": desc,
                "fecha": date,
                "url": link,
            })
    except Exception as e:  # noqa: BLE001
        print(f"RSS también falló: {e}")

    return licitaciones


# ─── Filtro por palabras clave ─────────────────────────────────────────────

def es_relevante(lic: dict) -> tuple[bool, str | None, str | None, str]:
    """Devuelve (relevante, keyword, fuente, texto_pliego_si_se_leyo)."""
    texto_base = (lic["titulo"] + " " + lic["descripcion"]).lower()
    for kw in settings.todas_las_palabras_clave():
        if kw.lower() in texto_base:
            return True, kw, "título/descripción", ""

    print(f"  Leyendo pliego de: {lic['titulo'][:60]}...")
    pliego = parser_mod.extraer_pliego(lic["url"], max_documentos=MAX_DOCUMENTOS_POR_LICITACION)
    texto_pliego = pliego.texto_completo
    texto_lower = texto_pliego.lower()
    for kw in settings.todas_las_palabras_clave():
        if kw.lower() in texto_lower:
            return True, kw, "pliego (PDF/Word/Excel)", texto_pliego

    return False, None, None, texto_pliego


# ─── Email ──────────────────────────────────────────────────────────────────

def enviar_email(nuevas: list[dict], modificadas: list[dict]) -> None:
    gmail_user = settings.gmail_user()
    gmail_pass = settings.gmail_app_password()
    dest = settings.email_destino()

    if not gmail_user or not gmail_pass:
        print("  GMAIL_USER/GMAIL_APP_PASSWORD no configurados: se omite el envío de email.")
        return

    total = len(nuevas) + len(modificadas)
    subject = f"🏗️ {total} novedad(es) de licitaciones para Metropolitana — {datetime.today().strftime('%d/%m/%Y')}"

    def _tarjeta(lic: dict, etiqueta: str, color: str) -> str:
        clasif = lic.get("clasificacion")
        clasif_html = (
            f'<p style="margin:0 0 4px;font-size:13px;color:#555;">⭐ {clasif.simbolo} — {clasif.etiqueta} (score {clasif.puntaje}/100)</p>'
            if clasif else ""
        )
        return f"""
        <div style="border-left:4px solid {color};padding:12px 16px;margin-bottom:16px;background:#f8f9fa;border-radius:0 6px 6px 0;">
            <p style="margin:0 0 4px;font-size:11px;font-weight:700;color:{color};text-transform:uppercase;">{etiqueta}</p>
            <p style="margin:0 0 6px;font-size:15px;font-weight:600;color:#1a1a1a;">{lic['titulo']}</p>
            <p style="margin:0 0 4px;font-size:13px;color:#555;">📅 {lic['fecha']} &nbsp;|&nbsp; 🔑 Coincidencia: <strong>{lic.get('keyword','')}</strong> &nbsp;|&nbsp; 📄 Encontrado en: <em>{lic.get('fuente','título')}</em></p>
            {clasif_html}
            <a href="{lic['url']}" style="display:inline-block;margin-top:8px;font-size:13px;color:#1a73e8;">Ver pliego →</a>
        </div>
        """

    html_items = "".join(_tarjeta(lic, "Nueva licitación", "#1a73e8") for lic in nuevas)
    html_items += "".join(_tarjeta(lic, "Aclaración / modificación detectada", "#e8711a") for lic in modificadas)

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#1a1a1a;">
        <h2 style="color:#1a73e8;margin-bottom:4px;">🔔 Novedades de licitaciones</h2>
        <p style="color:#666;font-size:13px;margin-top:0;">Detectadas automáticamente para <strong>Metropolitana Pisos</strong></p>
        <hr style="border:none;border-top:1px solid #e0e0e0;margin:16px 0;">
        {html_items}
        <p style="font-size:11px;color:#aaa;margin-top:24px;">Monitoreo automático vía ARCE · comprasestatales.gub.uy · Informes completos en la carpeta reports/ del repositorio.</p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = dest
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, dest, msg.as_string())

    print(f"✅ Email enviado ({len(nuevas)} nuevas, {len(modificadas)} modificadas).")


# ─── Main ──────────────────────────────────────────────────────────────────

def main(enviar_email_flag: bool = True) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Consultando ARCE...")

    vistos = cargar_vistos()
    licitaciones = obtener_licitaciones()
    print(f"  Total obtenidas: {len(licitaciones)}")

    nuevas: list[dict] = []
    modificadas: list[dict] = []

    for lic in licitaciones:
        hash_actual = _hash_contenido(lic)
        previo = vistos.get(lic["id"])

        if previo is not None:
            if previo.get("hash") and previo["hash"] != hash_actual:
                lic["keyword"] = "(título/descripción cambió desde la última revisión)"
                lic["fuente"] = "cambio detectado"
                modificadas.append(lic)
                vistos[lic["id"]]["hash"] = hash_actual
                vistos[lic["id"]]["notificaciones"] = previo.get("notificaciones", 1) + 1
            continue

        relevante, kw, fuente, texto_pliego = es_relevante(lic)
        vistos[lic["id"]] = {
            "titulo": lic["titulo"],
            "hash": hash_actual,
            "primera_deteccion": datetime.now().isoformat(),
            "notificaciones": 1 if relevante else 0,
        }

        if not relevante:
            continue

        lic["keyword"] = kw
        lic["fuente"] = fuente

        if not texto_pliego:
            pliego = parser_mod.extraer_pliego(lic["url"], max_documentos=MAX_DOCUMENTOS_POR_LICITACION)
            texto_pliego = pliego.texto_completo
            errores = [d.nombre for d in pliego.documentos_con_error]
        else:
            errores = []

        texto_para_informe = texto_pliego or (lic["titulo"] + "\n" + lic["descripcion"])
        informe = report_mod.analizar_licitacion(lic["titulo"], lic["url"], texto_para_informe, errores)
        ruta_informe = report_mod.guardar_informe(lic["titulo"], informe.markdown)
        print(f"  Informe generado: {ruta_informe} ({informe.clasificacion.simbolo} score {informe.clasificacion.puntaje})")

        # Misma clasificación que queda en el informe guardado — nunca se
        # recalcula por separado con menos datos (evita que el email
        # muestre una estrella distinta a la del informe real).
        lic["clasificacion"] = informe.clasificacion

        nuevas.append(lic)

    guardar_vistos(vistos)
    print(f"  Nuevas relevantes: {len(nuevas)} · Modificadas: {len(modificadas)}")

    if (nuevas or modificadas) and enviar_email_flag:
        enviar_email(nuevas, modificadas)
    elif not nuevas and not modificadas:
        print("  Sin novedades.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sin-email", action="store_true", help="No enviar email (para debug local)")
    args = ap.parse_args()
    main(enviar_email_flag=not args.sin_email)
