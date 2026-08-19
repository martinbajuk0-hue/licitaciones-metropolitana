"""Revisa el resultado de adjudicación (ganamos/perdimos) de los llamados
del catálogo del visor que todavía no tienen uno conocido, y manda un
email cuando aparece uno nuevo. Pedido del usuario 2026-08-19: "recordame
como saber el tema de las licitaciones que me presente y perdí" — acá se
automatiza esa consulta en vez de tener que hacerla a mano en ARCE.

Por qué es un script aparte de monitor.py: monitor.py ya puede tardar más
de una hora leyendo pliegos nuevos (ver CHECKPOINT_CADA_N_ITEMS en
monitor.py) y corre 3 veces por día; los resultados de adjudicación no
cambian con esa frecuencia — ARCE suele tardar semanas o meses en resolver
una compra —, así que consultarlos en cada corrida del monitor sería
carga innecesaria tanto para nuestro runner como para el sitio de ARCE.
Este script corre una vez por día (ver .github/workflows/resultados.yml)
y solo consulta los llamados que TODAVÍA no tienen resultado conocido:
una vez que un llamado queda resuelto (ganamos/perdimos/no_presentamos)
no se lo vuelve a chequear, así que la carga de cada corrida decrece con
el tiempo en vez de crecer sin límite junto con el catálogo.

Qué entra al email y qué no: se manda un email cuando un llamado pasa a
"ganamos" o "perdimos" — es decir, cuando Metropolitana SÍ se presentó y
ya hay resolución. Los que pasan a "no_presentamos" (ARCE resolvió pero
Metropolitana nunca ofertó) se guardan igual en el catálogo para que se
vean en el visor, pero deliberadamente NO generan email: son la mayoría
de las entradas del catálogo (incluye llamados de score bajo que nunca
fueron candidatos reales — ver catalogo.registrar_llamado()), y
alertarlos por mail recrearía el mismo problema de volumen que ya se
corrigió el 2026-08-19 (ver DIAS_MAX_PARA_ALERTA_POR_MAIL/
MAX_ALERTAS_POR_EMAIL en monitor.py).
"""
from __future__ import annotations

import argparse
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import catalogo
import config.settings as settings
import resultados as resultados_mod

# Mismo patrón de checkpointing que monitor.py (ver CHECKPOINT_CADA_N_ITEMS
# ahí): guardar el catálogo cada N ítems revisados en vez de solo al
# final, para no perder todo el progreso si la corrida se corta a mitad
# de camino (son cientos de requests HTTP a ARCE, una por llamado
# pendiente).
CHECKPOINT_CADA_N_ITEMS = 25


def revisar_pendientes() -> tuple[list[dict], int]:
    """Recorre el catálogo del visor y revisa, contra la ficha de ARCE de
    cada llamado, los que todavía no tienen un resultado de adjudicación
    conocido (o cuyo último resultado conocido sigue siendo "pendiente").

    Devuelve (transiciones, total_pendientes_revisados):
      - transiciones: las entradas cuyo resultado pasó de "pendiente" a
        "ganamos"/"perdimos"/"no_presentamos" recién en esta corrida —
        son las candidatas al email (ver enviar_email_resultados()).
      - total_pendientes_revisados: cuántos llamados se consultaron por
        red en esta corrida (para el log de la corrida).
    """
    catalogo_actual = catalogo._cargar_catalogo()
    pendientes = [
        (id_, entrada)
        for id_, entrada in catalogo_actual.items()
        if (entrada.get("resultado") or {}).get("estado", "pendiente") == "pendiente"
        and entrada.get("url_ficha")
    ]
    print(f"  {len(pendientes)} llamado(s) sin resultado conocido de {len(catalogo_actual)} en el catálogo del visor.")

    transiciones: list[dict] = []
    for idx, (id_, entrada) in enumerate(pendientes, start=1):
        if idx > 1 and (idx - 1) % CHECKPOINT_CADA_N_ITEMS == 0:
            catalogo._guardar_catalogo(catalogo_actual)
            print(f"  ...checkpoint: {idx - 1}/{len(pendientes)} revisados.")

        resultado = resultados_mod.obtener_resultado(entrada["url_ficha"])
        if resultado is None:
            continue  # error de red puntual: se reintenta en la próxima corrida diaria

        estado_nuevo = resultados_mod.estado_resumen(resultado)
        entrada["resultado"] = {
            "estado": estado_nuevo,
            "resolucion": resultado.resolucion,
            "resolucion_nro": resultado.resolucion_nro,
            "fecha_resolucion": resultado.fecha_resolucion,
            "monto_total": resultado.monto_total,
            "nos_presentamos": resultado.nos_presentamos,
            "ganamos": resultado.ganamos,
            "ultima_revision": datetime.now().isoformat(timespec="seconds"),
        }
        if estado_nuevo != "pendiente":
            transiciones.append(entrada)

    catalogo._guardar_catalogo(catalogo_actual)
    return transiciones, len(pendientes)


def enviar_email_resultados(transiciones: list[dict]) -> None:
    """Manda un único email con los llamados que pasaron a "ganamos" o
    "perdimos" en esta corrida (ver docstring del módulo — "no_presentamos"
    queda afuera del email a propósito)."""
    ganamos = [e for e in transiciones if e["resultado"]["estado"] == "ganamos"]
    perdimos = [e for e in transiciones if e["resultado"]["estado"] == "perdimos"]
    if not ganamos and not perdimos:
        print("  Sin ganamos/perdimos nuevos — no se envía email (los 'no_presentamos' quedan solo en el visor).")
        return

    gmail_user = settings.gmail_user()
    gmail_pass = settings.gmail_app_password()
    dest = settings.email_destino()
    if not gmail_user or not gmail_pass:
        print("  GMAIL_USER/GMAIL_APP_PASSWORD no configurados: se omite el envío de email.")
        return

    total = len(ganamos) + len(perdimos)
    subject = (
        f"{'🏆' if ganamos else '📋'} Resultado de adjudicación: "
        f"{len(ganamos)} ganada(s), {len(perdimos)} perdida(s) — {datetime.today().strftime('%d/%m/%Y')}"
    )

    def _tarjeta(entrada: dict, gano: bool) -> str:
        r = entrada["resultado"]
        color = "#1e8e3e" if gano else "#c53929"
        etiqueta = "🏆 GANAMOS" if gano else "❌ PERDIMOS"
        return f"""
        <div style="border-left:4px solid {color};padding:12px 16px;margin-bottom:16px;background:#f8f9fa;border-radius:0 6px 6px 0;">
            <p style="margin:0 0 4px;font-size:11px;font-weight:700;color:{color};text-transform:uppercase;">{etiqueta}</p>
            <p style="margin:0 0 6px;font-size:15px;font-weight:600;color:#1a1a1a;">{entrada.get('titulo','')}</p>
            <p style="margin:0 0 4px;font-size:13px;color:#555;">🏢 {entrada.get('organismo') or 'Organismo no especificado'}</p>
            <p style="margin:0 0 4px;font-size:13px;color:#555;">📋 Resolución: <strong>{r.get('resolucion') or '—'}</strong> {('(Nº ' + r['resolucion_nro'] + ')') if r.get('resolucion_nro') else ''}</p>
            <p style="margin:0 0 4px;font-size:13px;color:#555;">📅 Fecha resolución: {r.get('fecha_resolucion') or '—'} &nbsp;|&nbsp; 💰 Monto total: {r.get('monto_total') or '—'}</p>
            <a href="{entrada.get('url_ficha','')}" style="display:inline-block;margin-top:8px;font-size:13px;color:#1a73e8;">Ver ficha en ARCE →</a>
        </div>
        """

    html_items = "".join(_tarjeta(e, True) for e in ganamos)
    html_items += "".join(_tarjeta(e, False) for e in perdimos)

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#1a1a1a;">
        <h2 style="color:#1a73e8;margin-bottom:4px;">📋 Resultados de adjudicación</h2>
        <p style="color:#666;font-size:13px;margin-top:0;">Licitaciones donde Metropolitana se presentó y ARCE ya resolvió</p>
        <hr style="border:none;border-top:1px solid #e0e0e0;margin:16px 0;">
        {html_items}
        <p style="font-size:11px;color:#aaa;margin-top:24px;">Seguimiento automático vía ARCE · comprasestatales.gub.uy · Catálogo completo en el visor.</p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = dest
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, dest, msg.as_string())
    except smtplib.SMTPRecipientsRefused as e:
        print(f"❌ El servidor de Gmail rechazó al destinatario (dirección inválida/inexistente): {e}")
        return
    except smtplib.SMTPResponseException as e:
        print(f"❌ Error SMTP al enviar: código {e.smtp_code} — {e.smtp_error}")
        return

    print(f"✅ Email de resultados aceptado por Gmail ({len(ganamos)} ganamos, {len(perdimos)} perdimos).")


def main(enviar_email_flag: bool = True) -> None:
    print(f"🔎 Revisando resultados de adjudicación — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    transiciones, revisados = revisar_pendientes()
    ganamos = [t for t in transiciones if t["resultado"]["estado"] == "ganamos"]
    perdimos = [t for t in transiciones if t["resultado"]["estado"] == "perdimos"]
    no_presentamos = [t for t in transiciones if t["resultado"]["estado"] == "no_presentamos"]
    print(
        f"  Revisados: {revisados} · Nuevos resultados: {len(transiciones)} "
        f"(🏆 {len(ganamos)} ganamos, ❌ {len(perdimos)} perdimos, ➖ {len(no_presentamos)} no nos presentamos)"
    )
    if enviar_email_flag:
        enviar_email_resultados(transiciones)
    else:
        print("  --sin-email: no se envía email (igual queda guardado en el catálogo del visor).")


if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description="Revisa resultados de adjudicación del catálogo.")
    argparser.add_argument("--sin-email", action="store_true", help="Actualiza el catálogo pero no manda email.")
    args = argparser.parse_args()
    main(enviar_email_flag=not args.sin_email)
