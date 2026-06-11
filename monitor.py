import requests
import json
import os
import smtplib
import hashlib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
PALABRAS_CLAVE = [
    "piso", "pisos", "piso vinílico", "piso laminado", "piso flotante",
    "revestimiento", "revestimientos", "alfombra", "alfombras",
    "césped sintético", "cesped sintetico", "césped artificial", "pasto sintético",
    "pasto artificial", "cancha", "canchas", "SPC", "vinílico", "vinilico",
    "parquet", "porcelanato", "baldosa", "baldosas", "deck", "goma eva",
    "tapizado", "tapiz", "moquette", "linóleo", "linoleum",
]

ARCHIVO_VISTOS = "licitaciones_vistas.json"
OCDS_URL = "https://www.comprasestatales.gub.uy/ocds/releases"
RSS_URL  = "https://www.comprasestatales.gub.uy/ocds/rss"

# ─── CARGA / GUARDA IDs YA VISTOS ─────────────────────────────────────────────
def cargar_vistos():
    if os.path.exists(ARCHIVO_VISTOS):
        with open(ARCHIVO_VISTOS, "r") as f:
            return set(json.load(f))
    return set()

def guardar_vistos(vistos):
    with open(ARCHIVO_VISTOS, "w") as f:
        json.dump(list(vistos), f)

# ─── FETCH DE LICITACIONES ─────────────────────────────────────────────────────
def obtener_licitaciones():
    """Intenta OCDS releases; si falla, usa el RSS."""
    licitaciones = []

    # -- Intento 1: endpoint OCDS JSON
    try:
        r = requests.get(OCDS_URL, timeout=30)
        if r.status_code == 200:
            data = r.json()
            releases = data if isinstance(data, list) else data.get("releases", [])
            for rel in releases:
                tender = rel.get("tender", {})
                title = tender.get("title", "") or rel.get("title", "")
                desc  = tender.get("description", "") or ""
                ocid  = rel.get("ocid", "") or rel.get("id", "")
                date  = rel.get("date", "")[:10] if rel.get("date") else ""
                url   = f"https://www.comprasestatales.gub.uy/consultas/detalle/id/{ocid.split('-')[-1]}" if ocid else ""
                licitaciones.append({
                    "id": ocid,
                    "titulo": title,
                    "descripcion": desc,
                    "fecha": date,
                    "url": url,
                })
            if licitaciones:
                return licitaciones
    except Exception as e:
        print(f"OCDS JSON falló: {e}")

    # -- Intento 2: RSS feed
    try:
        import xml.etree.ElementTree as ET
        r = requests.get(RSS_URL, timeout=30)
        root = ET.fromstring(r.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        channel = root.find("channel")
        if channel is None:
            # Atom feed
            for entry in root.findall("atom:entry", ns):
                title = entry.findtext("atom:title", default="", namespaces=ns)
                link  = entry.findtext("atom:id", default="", namespaces=ns)
                date  = entry.findtext("atom:updated", default="", namespaces=ns)[:10]
                uid   = hashlib.md5(link.encode()).hexdigest()
                licitaciones.append({"id": uid, "titulo": title, "descripcion": "", "fecha": date, "url": link})
        else:
            for item in channel.findall("item"):
                title = item.findtext("title", default="")
                link  = item.findtext("link", default="")
                desc  = item.findtext("description", default="")
                date  = item.findtext("pubDate", default="")
                uid   = hashlib.md5(link.encode()).hexdigest()
                licitaciones.append({"id": uid, "titulo": title, "descripcion": desc, "fecha": date, "url": link})
    except Exception as e:
        print(f"RSS también falló: {e}")

    return licitaciones

# ─── FILTRO POR PALABRAS CLAVE ─────────────────────────────────────────────────
def es_relevante(lic):
    texto = (lic["titulo"] + " " + lic["descripcion"]).lower()
    for kw in PALABRAS_CLAVE:
        if kw.lower() in texto:
            return True, kw
    return False, None

# ─── ENVÍO DE EMAIL ────────────────────────────────────────────────────────────
def enviar_email(nuevas):
    gmail_user   = os.environ["GMAIL_USER"]
    gmail_pass   = os.environ["GMAIL_APP_PASSWORD"]
    dest         = os.environ.get("EMAIL_DESTINO", gmail_user)

    subject = f"🏗️ {len(nuevas)} licitación(es) nueva(s) para Metropolitana — {datetime.today().strftime('%d/%m/%Y')}"

    html_items = ""
    for lic in nuevas:
        html_items += f"""
        <div style="border-left:4px solid #1a73e8;padding:12px 16px;margin-bottom:16px;background:#f8f9fa;border-radius:0 6px 6px 0;">
            <p style="margin:0 0 6px;font-size:15px;font-weight:600;color:#1a1a1a;">{lic['titulo']}</p>
            <p style="margin:0 0 4px;font-size:13px;color:#555;">📅 {lic['fecha']} &nbsp;|&nbsp; 🔑 Coincidencia: <strong>{lic['keyword']}</strong></p>
            {'<p style="margin:4px 0;font-size:13px;color:#555;">' + lic['descripcion'][:200] + '...</p>' if lic['descripcion'] else ''}
            <a href="{lic['url']}" style="display:inline-block;margin-top:8px;font-size:13px;color:#1a73e8;">Ver pliego →</a>
        </div>
        """

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#1a1a1a;">
        <h2 style="color:#1a73e8;margin-bottom:4px;">🔔 Nuevas licitaciones relevantes</h2>
        <p style="color:#666;font-size:13px;margin-top:0;">Detectadas automáticamente para <strong>Metropolitana SA</strong></p>
        <hr style="border:none;border-top:1px solid #e0e0e0;margin:16px 0;">
        {html_items}
        <p style="font-size:11px;color:#aaa;margin-top:24px;">Monitoreo automático vía ARCE · comprasestatales.gub.uy</p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = gmail_user
    msg["To"]      = dest
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, dest, msg.as_string())

    print(f"✅ Email enviado con {len(nuevas)} licitaciones.")

# ─── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Consultando ARCE...")

    vistos      = cargar_vistos()
    licitaciones = obtener_licitaciones()
    print(f"  Total obtenidas: {len(licitaciones)}")

    nuevas = []
    for lic in licitaciones:
        if lic["id"] in vistos:
            continue
        relevante, kw = es_relevante(lic)
        if relevante:
            lic["keyword"] = kw
            nuevas.append(lic)
        vistos.add(lic["id"])

    guardar_vistos(vistos)
    print(f"  Nuevas relevantes: {len(nuevas)}")

    if nuevas:
        enviar_email(nuevas)
    else:
        print("  Sin novedades.")

if __name__ == "__main__":
    main()
