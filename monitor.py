"""Paso 1-4 del flujo: revisar diariamente nuevos llamados en Compras
Estatales (ARCE), detectar aclaraciones/modificaciones sobre licitaciones
ya vistas, descargar la documentación y correr el pipeline completo
(analyzer + risk + checklist + report) sobre las que resulten relevantes.

Uso:
    python monitor.py              # corrida normal (usada por el cron de GitHub Actions)
    python monitor.py --sin-email  # corre el pipeline pero no envía email (debug local)
    python monitor.py --test-rango-fechas 2026-08-13:2026-08-14  # email de prueba con licitaciones reales de ese rango
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

import requests

import analyzer
import catalogo
import config.settings as settings
import historial as historial_mod
import parser as parser_mod
import report as report_mod

MAX_DOCUMENTOS_POR_LICITACION = 5

# Reportado 2026-08-18/19: al pasar al feed RSS mensual (ver
# _meses_a_relevar()), un problema de concurrencia entre corridas (dos
# Cada cuántos llamados procesados en main() se hace un checkpoint de
# guardar_vistos() (en vez de solo una vez al final del loop). Con el
# feed mensual, una corrida que procesa varios cientos de llamados nuevos
# puede tardar más de una hora (cada uno implica 1-2 requests HTTP con
# timeout) — si esa corrida se cancela o se cae a mitad de camino, sin
# checkpoints se pierde TODO lo procesado hasta ese punto y la próxima
# corrida vuelve a arrancar de cero (evidencia real 2026-08-19: la
# corrida #201 se canceló a mitad de camino después de ~50 min).
CHECKPOINT_CADA_N_ITEMS = 25

# corridas del workflow procesando el mismo backlog de ~1000 llamados en
# simultáneo — ver .github/workflows/monitor.yml, "concurrency"; y cada
# corrida perdía TODO su progreso si no llegaba a terminar, porque
# guardar_vistos() solo se llamaba una vez al final del loop — ver
# CHECKPOINT_CADA_N_ITEMS más abajo) hizo que main() mandara UN email con
# ~450 tarjetas ("novedades") de una sola vez.
# Un email así no sirve para "acción rápida" (pedido explícito del
# usuario) — así que además de arreglar la concurrencia, se pone un techo
# defensivo acá: si alguna vez una corrida encuentra de golpe muchas más
# licitaciones relevantes de las que puede haber publicado ARCE en un
# día real (backlog, glitch del feed, etc.), el email NO las vuelca todas
# — manda las más relevantes (mayor score) y avisa cuántas quedaron
# afuera, visibles igual en el catálogo del visor (catalogo.registrar_llamado()
# se sigue llamando para TODAS, esto solo filtra qué entra al mail).
MAX_ALERTAS_POR_EMAIL = 30

# Idem: solo se manda por mail lo publicado "hace poco" — un llamado
# encontrado relevante pero publicado hace semanas (típicamente backlog
# de una corrida que recién ahora lo procesa, no una novedad real de
# hoy) tampoco es una "alerta del día". Se admiten 2 días de margen (no
# 1) para no perder de vista algo publicado a última hora de la tarde
# antes de la corrida de las 7am, o durante un fin de semana sin
# corridas. El catálogo del visor sigue mostrando todo, sin este filtro.
DIAS_MAX_PARA_ALERTA_POR_MAIL = 2


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


def _codigos_articulo(tender: dict) -> list[str]:
    """tender.items[].classification.id — el "Código de artículo" que ARCE
    le asigna a cada ítem pedido en el llamado (confirmado 2026-08-18
    contra el release real de la Compra Directa 10176/2026: el JSON trae
    "items": [{"classification": {"id": "63663", "description": "TATAMI"}, ...}],
    el mismo "Cód. Artículo 63663" que se ve en la ficha HTML del llamado).

    Es el mismo clasificador que usa knowledge/historial_adjudicaciones_
    metropolitana.json (campo "codigo") para cada ítem ya adjudicado a
    Metropolitana — por eso sirve para matchear EXACTO por código en vez
    de por texto (ver historial.productos_por_codigo_ya_adjudicado()).
    """
    items = tender.get("items", []) if isinstance(tender, dict) else []
    codigos = []
    for it in items:
        if not isinstance(it, dict):
            continue
        clasif = it.get("classification")
        if isinstance(clasif, dict) and clasif.get("id"):
            codigos.append(str(clasif["id"]))
    return codigos


# ─── Fetch de licitaciones (OCDS / RSS) ───────────────────────────────────

def _meses_a_relevar(ahora: datetime) -> list[tuple[int, int]]:
    """Mes actual + el anterior.

    settings.RSS_URL + "/AAAA/MM" es el feed RSS MENSUAL de ARCE — a
    diferencia de settings.RSS_URL a secas ("últimos 500 releases",
    mezclando TODOS los tipos de release de TODOS los organismos del
    país), este no tiene tope de 500 (confirmado 2026-08-18 contra la
    documentación oficial de ARCE y empíricamente: 7098 ítems para
    agosto/2026 a la fecha, de los cuales 1014 son de tipo "llamado",
    contra apenas 77 "llamado" visibles en esa misma ventana vía el feed
    plano de 500). Se pide también el mes anterior para no perder
    cobertura los primeros días de cada mes, cuando el feed del mes en
    curso todavía tiene pocos ítems publicados.
    """
    anio, mes = ahora.year, ahora.month
    anio_ant, mes_ant = (anio - 1, 12) if mes == 1 else (anio, mes - 1)
    return [(anio_ant, mes_ant), (anio, mes)]


def obtener_licitaciones(vistos: dict | None = None) -> list[dict]:
    """Intenta OCDS releases; si falla, usa el RSS mensual (mes actual +
    anterior), con fallback final al RSS plano de "últimos 500".

    Evidencia recogida corriendo esto en producción (ver commits de este
    branch): el feed RSS de comprasestatales.gub.uy NO trae texto de
    negocio en el <item> — solo un identificador interno como <title>
    (ej. "id_compra:1354587,release_id:adjudicacion-1354587"), <category>
    y <link> al release individual en JSON. Por eso acá se sigue el link
    de cada item category=="llamado" (nuevos llamados — lo que pide el
    paso 1 del flujo) para obtener el título/descripción reales.

    vistos: si se pasa (ver cargar_vistos()), los ítems "llamado" cuyo id
    ya está en vistos se omiten ANTES de pedir el detalle del release —
    evita re-descargar el JSON de ~1000+ llamados del mes en cada corrida
    (antes eran ~77/corrida bajo el feed plano de 500). Se pasa solo desde
    main() (la corrida real de producción); auditar() y
    enviar_email_de_prueba_rango_fechas() siguen pidiendo el detalle de
    TODOS los ítems (vistos=None) porque son de solo lectura y quieren
    ver todo, no solo lo nuevo.

    Trade-off aceptado (2026-08-18, ver "faltan organismos y rubros"): al
    omitir el refetch de ítems ya vistos, se deja de detectar si el
    release ORIGINAL de un llamado ya visto cambió de texto sin publicar
    un release separado (el hash-diff de enviar_email() para eso deja de
    dispararse en esos casos). No es una regresión de un caso ya
    manejado de punta a punta: aclar_llamado/ajuste_llamado (el mecanismo
    real de ARCE para modificaciones) siguen sin procesarse — ver
    PENDIENTE abajo — así que esto no elimina cobertura real, solo un
    caso borde ya fuera de alcance.

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
                licitaciones.append({
                    "id": ocid, "titulo": title, "descripcion": desc, "fecha": date, "url": url,
                    # Acá "url" YA es la ficha humana (ver arriba) — se
                    # duplica en "url_ficha" para que el resto del código
                    # (catalogo.py, enviar_email(), report.analizar_licitacion())
                    # pueda usar siempre lic.get("url_ficha") sin importar
                    # de qué rama (OCDS/RSS) vino el llamado.
                    "url_ficha": url,
                    "codigos_articulo": _codigos_articulo(tender),
                })
            if licitaciones:
                return licitaciones
    except Exception as e:  # noqa: BLE001
        print(f"OCDS JSON falló: {e}")

    try:
        import xml.etree.ElementTree as ET

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        todos_los_items = []
        for anio, mes in _meses_a_relevar(datetime.now()):
            url_mes = f"{settings.RSS_URL}/{anio}/{mes:02d}"
            r = requests.get(url_mes, headers=parser_mod.HEADERS, timeout=60)
            print(f"  RSS {anio}-{mes:02d}: status={r.status_code} content-type={r.headers.get('content-type')} body[:200]={r.text[:200]!r}")
            if r.status_code != 200:
                continue
            try:
                root_mes = ET.fromstring(r.content)
            except ET.ParseError as e:
                print(f"  RSS {anio}-{mes:02d}: XML inválido: {e}")
                continue
            channel_mes = root_mes.find("channel")
            if channel_mes is None:
                continue
            items_mes = channel_mes.findall("item")
            print(f"  RSS {anio}-{mes:02d}: {len(items_mes)} item(s)")
            todos_los_items.extend(items_mes)

        if not todos_los_items:
            # Red de seguridad: si el feed mensual no devolvió nada para
            # ninguno de los dos meses (ej. ambos pedidos fallaron), usar
            # el feed plano de "últimos 500" — mejor cobertura parcial que
            # ninguna, es el comportamiento que ya había antes de este fix.
            r = requests.get(settings.RSS_URL, headers=parser_mod.HEADERS, timeout=30)
            print(f"  RSS (fallback plano, sin tope mensual disponible): status={r.status_code} content-type={r.headers.get('content-type')} body[:300]={r.text[:300]!r}")
            root = ET.fromstring(r.content)
            channel = root.find("channel")
            if channel is None:
                for entry in root.findall("atom:entry", ns):
                    title = entry.findtext("atom:title", default="", namespaces=ns)
                    link = entry.findtext("atom:id", default="", namespaces=ns)
                    date = (entry.findtext("atom:updated", default="", namespaces=ns) or "")[:10]
                    uid = hashlib.md5(link.encode()).hexdigest()
                    licitaciones.append({"id": uid, "titulo": title, "descripcion": "", "fecha": date, "url": link, "url_ficha": link})
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

        def _url_ficha_arce(guid: str, link: str) -> str:
            # lic["url"] (== link, el <link> del feed) apunta al JSON del
            # release OCDS (ej. ".../ocds/release/llamado-1361110") — sirve
            # para que el pipeline lea título/descripción/documentos, pero
            # si una persona lo abre en el navegador ve JSON crudo, no la
            # ficha de ARCE (reportado 2026-08-18: el link "Ver ficha en
            # ARCE" del visor mostraba el JSON en vez de la página). ARCE
            # sí tiene una página humana para el mismo llamado en
            # /consultas/detalle/id/{id numérico} — el mismo patrón que ya
            # se usa arriba para la rama OCDS (ocid.split('-')[-1]). El id
            # numérico de un guid "llamado-1361110" es la parte después del
            # último guion; si el guid no matchea ese formato exacto (no
            # debería pasar, ya se filtró por _tipo_release == "llamado"),
            # se cae al link del JSON antes que a un link roto.
            m = re.match(r"^llamado-(\d+)$", guid)
            if m:
                return f"https://www.comprasestatales.gub.uy/consultas/detalle/id/{m.group(1)}"
            return link

        items_llamado = [it for it in todos_los_items if _tipo_release(it) == "llamado"]
        tipos_vistos = sorted({_tipo_release(it) for it in todos_los_items})
        print(f"  RSS: {len(todos_los_items)} item(s) totales, {len(items_llamado)} de tipo 'llamado'. Tipos vistos: {tipos_vistos}")

        primer_release_impreso = False
        omitidos_por_vistos = 0
        for item in items_llamado:
            link = item.findtext("link", default="")
            guid = item.findtext("guid", default="") or link
            date = item.findtext("pubDate", default="")
            uid = hashlib.md5(guid.encode()).hexdigest()

            if vistos is not None and uid in vistos:
                omitidos_por_vistos += 1
                continue

            titulo, desc, documentos, codigos_articulo = "", "", [], []
            try:
                rr = requests.get(link, headers=parser_mod.HEADERS, timeout=15)
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
                    # Estándar OCDS: los documentos del pliego van en
                    # tender.documents[].url — NO en un HTML para scrapear.
                    # lic["url"] apunta al JSON del release (no a una página
                    # HTML), así que parser.extraer_pliego() no podría
                    # encontrarlos ahí buscando <a href="...pdf">.
                    documentos = [
                        d.get("url") for d in tender.get("documents", []) if isinstance(d, dict) and d.get("url")
                    ]
                    codigos_articulo = _codigos_articulo(tender)
                if not primer_release_impreso:
                    print(
                        f"  RSS->release: status={rr.status_code} título={titulo!r} "
                        f"tender.keys={sorted(tender.keys()) if titulo or desc else 'N/A'} "
                        f"documentos={documentos} codigos_articulo={codigos_articulo}"
                    )
                    primer_release_impreso = True
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
                "url_ficha": _url_ficha_arce(guid, link),
                "documentos": documentos,
                "codigos_articulo": codigos_articulo,
            })

        if vistos is not None:
            print(f"  RSS: {omitidos_por_vistos} ítem(s) 'llamado' ya vistos en corridas anteriores — se omitió el refetch de detalle.")
    except Exception as e:  # noqa: BLE001
        print(f"RSS también falló: {e}")

    return licitaciones


# ─── Filtro por palabras clave ─────────────────────────────────────────────

def _leer_pliego(lic: dict) -> "parser_mod.PliegoExtraido":
    """Descarga y extrae los documentos reales del pliego.

    Preferimos tender.documents[].url (URLs directas a PDF/Word/Excel,
    vienen en el JSON del release — campo estándar OCDS) sobre
    parser.extraer_pliego(lic['url']), que scrapea <a href="...pdf"> de
    una página HTML: lic['url'] apunta al JSON del release, no a una
    página HTML, así que ese scrape nunca encontraría nada ahí.
    """
    urls = lic.get("documentos") or []
    if urls:
        pliego = parser_mod.PliegoExtraido()
        for doc_url in urls[:MAX_DOCUMENTOS_POR_LICITACION]:
            pliego.documentos.append(parser_mod.descargar_y_extraer(doc_url))
        return pliego
    return parser_mod.extraer_pliego(lic["url"], max_documentos=MAX_DOCUMENTOS_POR_LICITACION)


def _matches_en_texto(texto_lower: str) -> list[str]:
    return [kw for kw in settings.todas_las_palabras_clave() if settings.coincide_palabra_clave(texto_lower, kw)]


_PATRONES_ALQUILER_INMUEBLE = [
    "contratación de local",
    "contratacion de local",
    "contratación de locales",
    "contratacion de locales",
    "alquiler de local",
    "alquiler de locales",
    "arrendamiento de local",
    "arrendamiento de locales",
    "alquiler de inmueble",
    "alquiler de inmuebles",
    "arrendamiento de inmueble",
    "arrendamiento de inmuebles",
    "locación de inmueble",
    "locacion de inmueble",
    "comodato de local",
    "comodato de inmueble",
]


def _es_alquiler_de_inmueble(texto_lower: str) -> bool:
    """True si el objeto de la compra es arrendar/alquilar un local o
    inmueble YA CONSTRUIDO (ej. auditoría real 2026-08-17, Concurso de
    Precios 12/2026: 'Contratación de local apto para el dictado de
    clases curriculares de Educación Física...') — Metropolitana vende e
    instala pisos/revestimientos/césped sintético/contenedores, no es
    propietaria de inmuebles para alquilar, así que este tipo de compra
    nunca es una oportunidad real sin importar qué términos matcheen.

    Este caso concreto matcheó por 'arcos de fútbol': el pliego es un
    formulario donde el organismo le pregunta a cada local candidato qué
    equipamiento YA TIENE instalado ("Piso: Madera:.... Baldosa:....
    Hormigón:...." / "Arcos de fútbol Sí .... No ....") — son casillas de
    verificación sobre infraestructura existente, no una compra de
    producto. Por eso este chequeo va ANTES de _decidir_relevancia(): un
    término multi-palabra específico del rubro no alcanza para salvar
    estos casos, hace falta descartarlos por el tipo de objeto.
    """
    return any(patron in texto_lower for patron in _PATRONES_ALQUILER_INMUEBLE)


def _decidir_relevancia(matches: list[str]) -> tuple[bool, str | None]:
    """Regla anti-falsos-positivos SIN IA (ver conversación 2026-07-13):
    una sola coincidencia de un término de UNA palabra (ej. "aluminio",
    "goma", "pvc") no alcanza para marcar relevante — la auditoría real
    contra ARCE mostró que esos términos sueltos matchean tan seguido en
    contextos ajenos al rubro (esponja de aluminio, ruedas de goma,
    conducto PVC) como en pliegos reales de pisos. Exigimos:
      - cualquier término de 2+ palabras (ya específico por construcción,
        ej. "piso vinílico", "césped sintético"), O
      - 2+ términos de una palabra DISTINTOS en el mismo texto (la señal
        real de un pliego de pisos es que aparecen varios juntos: pvc +
        zócalo + baldosa, no uno solo aislado).
    No reemplaza una verificación semántica real — sigue habiendo margen
    de falsos positivos (ej. "pvc" + "carpeta" en una compra de
    útiles de oficina), pero reduce el ruido sin costo ni dependencias.
    """
    multipalabra = [kw for kw in matches if settings.es_termino_multipalabra(kw)]
    if multipalabra:
        return True, multipalabra[0]
    distintos = sorted({kw.lower() for kw in matches})
    if len(distintos) >= 2:
        return True, " + ".join(distintos[:3])
    return False, None


FUENTE_CODIGO_ARTICULO = "código de artículo ARCE (ya adjudicado)"


def es_relevante(lic: dict) -> tuple[bool, str | None, str | None, str]:
    """Devuelve (relevante, keyword, fuente, texto_pliego_si_se_leyo).

    El match por código de artículo (lic["codigos_articulo"], ver
    _codigos_articulo()) se chequea ANTES que el umbral de 2+ términos de
    _decidir_relevancia() (que existe para compensar la debilidad del
    match por texto — algo que un código exacto no tiene): si hay match,
    el llamado se manda por mail sí o sí. Pedido explícito del usuario
    2026-08-18.

    PERO el filtro de alquiler de inmueble se chequea PRIMERO que el
    código, como veto absoluto — no al revés. Motivo (evidencia real
    2026-08-18, ver historial._CODIGOS_NO_ESPECIFICOS): el historial tiene
    códigos genéricos/administrativos (ej. 35420 "CONTRATACION DE
    SERVICIOS PROFESIONALES", que disparó en la auditoría en vivo contra
    un llamado de Intendencia de Montevideo sin relación con pisos) que
    ya se filtran en historial._codigos_metropolitana(), pero un código
    específico también podría coincidir por casualidad con una compra que
    en realidad es un alquiler de local (ej. si algún día apareciera
    "ARRENDAMIENTO DE PISO" sin excluir) — así que ninguna señal, ni
    siquiera el código, debe pisar ese veto.
    """
    texto_base = (lic["titulo"] + " " + lic["descripcion"]).lower()
    if _es_alquiler_de_inmueble(texto_base):
        return False, None, None, ""

    codigos = lic.get("codigos_articulo") or []
    if codigos:
        productos_por_codigo = historial_mod.productos_por_codigo_ya_adjudicado(codigos)
        if productos_por_codigo:
            return (
                True,
                f"código ya adjudicado: {', '.join(productos_por_codigo)}",
                FUENTE_CODIGO_ARTICULO,
                "",
            )

    relevante, kw = _decidir_relevancia(_matches_en_texto(texto_base))
    if relevante:
        return True, kw, "título/descripción", ""

    print(f"  Leyendo pliego de: {lic['titulo'][:60]}... ({len(lic.get('documentos') or [])} documento(s))")
    pliego = _leer_pliego(lic)
    texto_pliego = pliego.texto_completo
    texto_lower = texto_pliego.lower()
    if _es_alquiler_de_inmueble(texto_lower):
        return False, None, None, texto_pliego
    relevante, kw = _decidir_relevancia(_matches_en_texto(texto_lower))
    if relevante:
        return True, kw, "pliego (PDF/Word/Excel)", texto_pliego

    return False, None, None, texto_pliego


# ─── Email ──────────────────────────────────────────────────────────────────

def enviar_email(nuevas: list[dict], modificadas: list[dict], omitidas_del_visor: int = 0) -> None:
    """omitidas_del_visor: cuántos llamados relevantes adicionales quedaron
    afuera de este email (por antigüedad o por el techo de
    MAX_ALERTAS_POR_EMAIL — ver main()) pero siguen visibles en el
    catálogo del visor. Es solo informativo: no cambia qué se manda, solo
    agrega una línea al pie para que quede claro que el email no es
    necesariamente "todo lo relevante", así no se lea como que faltó
    algo sin avisar.
    """
    gmail_user = settings.gmail_user()
    gmail_pass = settings.gmail_app_password()
    dest = settings.email_destino()

    if not gmail_user or not gmail_pass:
        print("  GMAIL_USER/GMAIL_APP_PASSWORD no configurados: se omite el envío de email.")
        return

    # Diagnóstico sin exponer los secrets: GitHub enmascara cualquier
    # coincidencia exacta de un secret en el log, pero el dominio del
    # destinatario no lo es, y alcanza para saber si EMAIL_DESTINO está
    # configurado o si el mail termina cayendo en la propia cuenta de envío.
    dominio_dest = dest.split("@")[-1] if dest and "@" in dest else "(dirección inválida o vacía)"
    print(
        f"  Email: EMAIL_DESTINO seteado como variable de entorno={'EMAIL_DESTINO' in os.environ} "
        f"destino_es_igual_a_gmail_user={dest == gmail_user} dominio_destino={dominio_dest!r}"
    )

    total = len(nuevas) + len(modificadas)
    subject = f"🏗️ {total} novedad(es) de licitaciones para Metropolitana — {datetime.today().strftime('%d/%m/%Y')}"

    def _tarjeta(lic: dict, etiqueta: str, color: str) -> str:
        # Resumen corto ("qué es esta licitación", ver analyzer.extraer_
        # que_es()) — pedido del usuario 2026-08-24: poder entender de qué
        # se trata cada llamado sin tener que abrir el pliego. Va primero,
        # antes de cualquier otro dato, porque es lo primero que hace
        # falta leer para decidir si seguir mirando la tarjeta.
        que_es_html = (
            f'<p style="margin:0 0 6px;font-size:13px;color:#333;">📝 {lic["que_es"]}</p>'
            if lic.get("que_es") else ""
        )
        clasif = lic.get("clasificacion")
        clasif_html = (
            f'<p style="margin:0 0 4px;font-size:13px;color:#555;">⭐ {clasif.simbolo} — {clasif.etiqueta} (score {clasif.puntaje}/100)</p>'
            if clasif else ""
        )
        # "Ya adjudicaste antes" + "Cierra en N días": el mismo par de datos
        # que un servicio de avisos como Simple Compras Públicas muestra
        # primero en su email (ver Ejemplo_Alerta_Email_Metropolitana.png,
        # reunión del 14/08/2026) — permite decidir en un vistazo si vale
        # la pena abrir el informe completo, sin leer el pliego.
        ya_adjudicados = lic.get("ya_adjudicados") or []
        ya_adjudicados_html = (
            f'<p style="margin:0 0 4px;font-size:13px;color:#1e8e3e;font-weight:600;">✅ Ya adjudicaste antes: {", ".join(ya_adjudicados[:5])}'
            f'{" ..." if len(ya_adjudicados) > 5 else ""}</p>'
            if ya_adjudicados else ""
        )
        cierre_html = (
            f'<p style="margin:0 0 4px;font-size:13px;color:#555;">⏱️ {lic["cierre"]}</p>'
            if lic.get("cierre") else ""
        )
        # lic["url"] es el JSON del release OCDS (metadata para el pipeline,
        # no algo legible para una persona). Lo que hay que abrir es el PDF
        # real del pliego, que viene en lic["documentos"]
        # (tender.documents[].url — ver monitor.obtener_licitaciones()).
        documentos = lic.get("documentos") or []
        if documentos:
            links_html = "".join(
                f'<a href="{doc_url}" style="display:inline-block;margin-top:8px;margin-right:16px;font-size:13px;color:#1a73e8;">📄 Ver pliego {i + 1} →</a>'
                for i, doc_url in enumerate(documentos[:3])
            )
        else:
            links_html = f'<a href="{lic.get("url_ficha") or lic["url"]}" style="display:inline-block;margin-top:8px;font-size:13px;color:#1a73e8;">Ver ficha de la licitación (sin PDF adjunto) →</a>'
        return f"""
        <div style="border-left:4px solid {color};padding:12px 16px;margin-bottom:16px;background:#f8f9fa;border-radius:0 6px 6px 0;">
            <p style="margin:0 0 4px;font-size:11px;font-weight:700;color:{color};text-transform:uppercase;">{etiqueta}</p>
            <p style="margin:0 0 6px;font-size:15px;font-weight:600;color:#1a1a1a;">{lic['titulo']}</p>
            {que_es_html}
            <p style="margin:0 0 4px;font-size:13px;color:#555;">📅 {lic['fecha']} &nbsp;|&nbsp; 🔑 Coincidencia: <strong>{lic.get('keyword','')}</strong> &nbsp;|&nbsp; 📄 Encontrado en: <em>{lic.get('fuente','título')}</em></p>
            {clasif_html}
            {ya_adjudicados_html}
            {cierre_html}
            {links_html}
        </div>
        """

    html_items = "".join(_tarjeta(lic, "Nueva licitación", "#1a73e8") for lic in nuevas)
    html_items += "".join(_tarjeta(lic, "Aclaración / modificación detectada", "#e8711a") for lic in modificadas)

    omitidas_html = (
        f'<p style="font-size:12px;color:#888;margin:0 0 16px;">ℹ️ {omitidas_del_visor} llamado(s) relevante(s) '
        "más (backlog más antiguo, o por encima del techo de este email) no incluido(s) acá — "
        'ver el catálogo completo en el visor.</p>'
        if omitidas_del_visor else ""
    )

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#1a1a1a;">
        <h2 style="color:#1a73e8;margin-bottom:4px;">🔔 Novedades de licitaciones</h2>
        <p style="color:#666;font-size:13px;margin-top:0;">Detectadas automáticamente para <strong>Metropolitana Pisos</strong></p>
        <hr style="border:none;border-top:1px solid #e0e0e0;margin:16px 0;">
        {omitidas_html}
        {html_items}
        <p style="font-size:11px;color:#aaa;margin-top:24px;">Monitoreo automático vía ARCE · comprasestatales.gub.uy · Informes completos en la carpeta reports/ del repositorio.</p>
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

    # smtp 250 OK acá solo confirma que Gmail ACEPTÓ el mensaje para
    # entregarlo — no garantiza que llegue a la bandeja de entrada (puede
    # caer en spam/cuarentena del servidor destino sin que Gmail se entere).
    print(f"✅ Email aceptado por Gmail para entrega ({len(nuevas)} nuevas, {len(modificadas)} modificadas) — revisar spam si no aparece en la bandeja principal.")


# ─── Main ──────────────────────────────────────────────────────────────────

def main(enviar_email_flag: bool = True) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Consultando ARCE...")

    vistos = cargar_vistos()
    licitaciones = obtener_licitaciones(vistos)
    print(f"  Total obtenidas: {len(licitaciones)}")

    nuevas: list[dict] = []
    modificadas: list[dict] = []

    for idx, lic in enumerate(licitaciones, start=1):
        # Checkpoint periódico: guarda el progreso acumulado hasta ahora
        # ANTES de procesar el siguiente ítem, así una corrida larga que
        # se cancela o se cae a mitad de camino no pierde todo lo ya
        # procesado (ver CHECKPOINT_CADA_N_ITEMS arriba).
        if idx > 1 and (idx - 1) % CHECKPOINT_CADA_N_ITEMS == 0:
            guardar_vistos(vistos)

        hash_actual = _hash_contenido(lic)
        previo = vistos.get(lic["id"])

        if previo is not None:
            if previo.get("hash") and previo["hash"] != hash_actual:
                lic["keyword"] = "(título/descripción cambió desde la última revisión)"
                lic["fuente"] = "cambio detectado"
                modificadas.append(lic)
                catalogo.registrar_modificacion(lic)
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
            pliego = _leer_pliego(lic)
            texto_pliego = pliego.texto_completo
            errores = [d.nombre for d in pliego.documentos_con_error]
        else:
            errores = []

        texto_para_informe = texto_pliego or (lic["titulo"] + "\n" + lic["descripcion"])
        informe = report_mod.analizar_licitacion(
            lic["titulo"], lic.get("url_ficha") or lic["url"], texto_para_informe, errores,
            codigos_articulo=lic.get("codigos_articulo"),
        )
        ruta_informe = report_mod.guardar_informe(lic["titulo"], informe.markdown)
        print(f"  Informe generado: {ruta_informe} ({informe.clasificacion.simbolo} score {informe.clasificacion.puntaje})")

        # Se registra en el catálogo del visor web SIEMPRE que el llamado
        # pasó el filtro de relevancia, sin importar el score — el filtro de
        # score mínimo (más abajo) decide qué llega por mail, no qué aparece
        # en el visor. Ver docstring de catalogo.registrar_llamado().
        catalogo.registrar_llamado(lic, informe)

        # Misma clasificación, historial y cierre que quedan en el informe
        # guardado — nunca se recalculan por separado con menos datos
        # (evita que el email muestre una estrella, o un "ya adjudicaste
        # antes", distinto al del informe real).
        lic["clasificacion"] = informe.clasificacion
        lic["ya_adjudicados"] = informe.ya_adjudicados
        lic["cierre"] = informe.cierre
        lic["que_es"] = informe.que_es
        # Filtro por score mínimo (configurable vía secret SCORE_MINIMO_EMAIL)
        # — salvo que el match haya sido por código de artículo ya
        # adjudicado: ahí se manda sí o sí, pedido explícito del usuario
        # 2026-08-18 (ver es_relevante()).
        score_minimo = int(os.environ.get("SCORE_MINIMO_EMAIL", 0))
        if informe.clasificacion.puntaje < score_minimo and fuente != FUENTE_CODIGO_ARTICULO:
            print(f"  Score {informe.clasificacion.puntaje} < mínimo {score_minimo}, omitiendo del email.")
            continue

        nuevas.append(lic)

    guardar_vistos(vistos)
    print(f"  Nuevas relevantes: {len(nuevas)} · Modificadas: {len(modificadas)}")

    # El email es para "acción rápida" (pedido explícito del usuario
    # 2026-08-19) — no un volcado de todo lo relevante que haya en
    # vistos. Dos filtros antes de armar el mail (el catálogo del visor
    # NO pasa por ninguno de los dos, sigue mostrando todo):
    #   1. Solo lo publicado hace poco (DIAS_MAX_PARA_ALERTA_POR_MAIL) —
    #      backlog viejo que recién se termina de procesar ahora no es
    #      una "novedad del día".
    #   2. Techo defensivo (MAX_ALERTAS_POR_EMAIL) — si aun así quedan
    #      demasiadas, se manda solo las de mayor score y se avisa cuántas
    #      quedaron afuera (siguen en el catálogo del visor).
    nuevas_para_mail = [lic for lic in nuevas if _es_publicacion_reciente(lic)]
    omitidas_por_antiguedad = len(nuevas) - len(nuevas_para_mail)
    if omitidas_por_antiguedad:
        print(
            f"  {omitidas_por_antiguedad} relevante(s) publicada(s) hace más de "
            f"{DIAS_MAX_PARA_ALERTA_POR_MAIL} día(s) — quedan en el catálogo del visor "
            "pero no se incluyen en el email del día."
        )

    omitidas_por_techo = 0
    if len(nuevas_para_mail) > MAX_ALERTAS_POR_EMAIL:
        nuevas_para_mail.sort(key=lambda lic: lic["clasificacion"].puntaje, reverse=True)
        omitidas_por_techo = len(nuevas_para_mail) - MAX_ALERTAS_POR_EMAIL
        nuevas_para_mail = nuevas_para_mail[:MAX_ALERTAS_POR_EMAIL]
        print(
            f"  {omitidas_por_techo} relevante(s) más publicada(s) recientemente, pero por "
            f"encima del techo de {MAX_ALERTAS_POR_EMAIL}/email — se mandan las de mayor "
            "score, el resto queda en el catálogo del visor."
        )

    if (nuevas_para_mail or modificadas) and enviar_email_flag:
        enviar_email(nuevas_para_mail, modificadas, omitidas_por_techo + omitidas_por_antiguedad)
    elif not nuevas_para_mail and not modificadas:
        print("  Sin novedades para el email del día.")


def auditar() -> None:
    """Modo de solo lectura para verificar CON EVIDENCIA que cada
    licitación marcada relevante realmente menciona un producto de
    Metropolitana — no confiar solo en el score.

    A diferencia de main(), no toca data/licitaciones_vistas.json (evalúa
    TODAS las licitaciones del feed, no solo las nuevas) ni envía email:
    solo imprime, para cada una marcada relevante, el término que la
    disparó y el fragmento real de texto donde aparece — para que una
    persona pueda confirmar de un vistazo si es un producto real o un
    falso positivo del filtro amplio (ver knowledge/keywords.yaml).

    Uso: python monitor.py --auditoria
    """
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Auditoría de relevancia (solo lectura, no modifica estado ni envía email)...")

    licitaciones = obtener_licitaciones()
    print(f"  Total obtenidas: {len(licitaciones)}")

    relevantes = 0
    for lic in licitaciones:
        relevante, kw, fuente, texto_pliego = es_relevante(lic)
        if not relevante:
            continue
        relevantes += 1

        if not texto_pliego:
            # Matcheó por título/descripción: igual leemos el pliego para
            # poder mostrar los fragmentos de producto, si los hay.
            texto_pliego = _leer_pliego(lic).texto_completo

        print(f"\n=== {lic['titulo']} ===")
        print(f"  Coincidencia inicial: {kw!r} (fuente: {fuente})")

        productos = analyzer.identificar_productos(texto_pliego) if texto_pliego else []
        if not productos:
            if fuente == FUENTE_CODIGO_ARTICULO:
                # No hace falta texto del pliego para confiar en este match:
                # el código de artículo del ítem pedido coincide EXACTO con
                # uno que Metropolitana ya facturó (ver kw, con los nombres
                # de producto del historial).
                print("  ✓ Match por código de artículo — no requiere confirmación por texto del pliego.")
                continue
            print("  ⚠️  Sin productos identificables en el texto del pliego (matcheó por título/descripción "
                  "o el pliego no se pudo leer) — VERIFICAR MANUALMENTE antes de confiar en este match.")
            continue

        for p in productos[:10]:
            etiqueta = settings.etiqueta_categoria(p.categoria)
            print(f"  ✓ [{etiqueta}] \"{p.termino_encontrado}\" — ...{p.fragmento}...")
        if len(productos) > 10:
            print(f"  ... y {len(productos) - 10} coincidencia(s) más de producto.")

    print(f"\n  Total evaluadas: {len(licitaciones)} · Marcadas relevantes: {relevantes}")


def enviar_email_de_prueba() -> None:
    """Manda un mail de prueba sin depender de encontrar una licitación
    real — para verificar GMAIL_USER/GMAIL_APP_PASSWORD/EMAIL_DESTINO
    (`python monitor.py --test-email`).
    """
    lic_prueba = {
        "titulo": "[PRUEBA] Verificación de configuración de email",
        "descripcion": "Este mail no corresponde a una licitación real. Se generó manualmente para confirmar que GMAIL_USER/GMAIL_APP_PASSWORD/EMAIL_DESTINO están bien configurados, y que el link va al PDF del pliego (no al JSON crudo).",
        "fecha": datetime.now().strftime("%Y-%m-%d"),
        "url": "https://www.comprasestatales.gub.uy",
        "keyword": "(prueba manual, no es una coincidencia real)",
        "fuente": "prueba",
        "documentos": ["https://www.comprasestatales.gub.uy/Pliegos/pedido_1354522.pdf"],
        "que_es": "Esto es un mail de prueba — no corresponde a una licitación real.",
    }
    enviar_email([lic_prueba], [])


def _fecha_lic_a_iso(fecha_cruda: str) -> str | None:
    """lic['fecha'] sale de obtener_licitaciones() ya normalizada a
    'YYYY-MM-DD' cuando el feed OCDS responde (rel['date'][:10]), pero si
    se cayó al fallback RSS es un pubDate RFC822 crudo (ej. 'Wed, 13 Aug
    2026 10:00:00 GMT') que nunca se normalizó en obtener_licitaciones()
    porque esa función solo lo usa para mostrarlo tal cual en el email.
    Acá sí hace falta compararlo contra un rango/fecha de hoy, así que se
    intentan ambos formatos en vez de asumir uno. Usado tanto por
    --test-rango-fechas como por main() (ver _es_publicacion_reciente(),
    filtro de qué entra al email del día).
    """
    if not fecha_cruda:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", fecha_cruda):
        return fecha_cruda[:10]
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(fecha_cruda).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _es_publicacion_reciente(lic: dict, max_dias: int = DIAS_MAX_PARA_ALERTA_POR_MAIL) -> bool:
    """True si lic['fecha'] cae dentro de los últimos `max_dias` días (o si
    no se pudo parsear la fecha — fail-open: mejor una alerta de más que
    perder silenciosamente un llamado nuevo real por un pubDate raro).

    Usado en main() para decidir qué llamados relevantes entran al email
    del día — ver MAX_ALERTAS_POR_EMAIL y DIAS_MAX_PARA_ALERTA_POR_MAIL
    arriba. El catálogo del visor (catalogo.registrar_llamado()) NO pasa
    por este filtro: se sigue registrando todo lo relevante, esto solo
    decide qué es urgente para el email.
    """
    fecha_iso = _fecha_lic_a_iso(lic.get("fecha", ""))
    if not fecha_iso:
        return True
    try:
        fecha_pub = datetime.strptime(fecha_iso, "%Y-%m-%d")
    except ValueError:
        return True
    return (datetime.now() - fecha_pub).days <= max_dias


def enviar_email_de_prueba_rango_fechas(desde: str, hasta: str) -> None:
    """Corre el pipeline real (fetch a ARCE + filtro de relevancia +
    lectura de pliego + análisis) pero restringido a licitaciones cuya
    fecha de publicación cae en [desde, hasta] (inclusive, 'YYYY-MM-DD'),
    y manda el resultado por email — para revisar con datos reales cómo
    se ve el mail (incluye "Ya adjudicaste antes" / "Cierra en N días")
    sin esperar a que aparezca un llamado nuevo hoy.

    A diferencia de main(): es de solo lectura. No toca
    data/licitaciones_vistas.json ni docs/data/llamados.json/docs/informes
    — así no interfiere con el estado real ("ya visto") que usa el cron
    de producción, y no hace falta limpiarlo después de probar.

    Uso: python monitor.py --test-rango-fechas 2026-08-13:2026-08-14
    """
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Test con licitaciones publicadas entre {desde} y {hasta} (solo lectura, no modifica estado ni el catálogo del visor)...")

    licitaciones = obtener_licitaciones()
    print(f"  Total obtenidas: {len(licitaciones)}")

    en_rango = [lic for lic in licitaciones if (_fecha_lic_a_iso(lic.get("fecha", "")) or "") and desde <= _fecha_lic_a_iso(lic["fecha"]) <= hasta]
    print(f"  Publicadas entre {desde} y {hasta}: {len(en_rango)}")

    score_minimo = int(os.environ.get("SCORE_MINIMO_EMAIL", 0))
    nuevas: list[dict] = []
    for lic in en_rango:
        relevante, kw, fuente, texto_pliego = es_relevante(lic)
        if not relevante:
            continue
        lic["keyword"] = kw
        lic["fuente"] = fuente

        if not texto_pliego:
            pliego = _leer_pliego(lic)
            texto_pliego = pliego.texto_completo
            errores = [d.nombre for d in pliego.documentos_con_error]
        else:
            errores = []

        texto_para_informe = texto_pliego or (lic["titulo"] + "\n" + lic["descripcion"])
        informe = report_mod.analizar_licitacion(
            lic["titulo"], lic.get("url_ficha") or lic["url"], texto_para_informe, errores,
            codigos_articulo=lic.get("codigos_articulo"),
        )
        print(f"  Relevante: {lic['titulo'][:70]!r} — {informe.clasificacion.simbolo} score {informe.clasificacion.puntaje}")

        lic["clasificacion"] = informe.clasificacion
        lic["ya_adjudicados"] = informe.ya_adjudicados
        lic["cierre"] = informe.cierre
        lic["que_es"] = informe.que_es

        if informe.clasificacion.puntaje < score_minimo and fuente != FUENTE_CODIGO_ARTICULO:
            print(f"    Score {informe.clasificacion.puntaje} < mínimo {score_minimo}, omitiendo del email (igual que en producción).")
            continue
        nuevas.append(lic)

    print(f"  Relevantes que entrarían al email: {len(nuevas)}")
    if not nuevas:
        print("  Ninguna licitación relevante en ese rango de fechas — no se manda email (para no mandar uno vacío).")
        return
    enviar_email(nuevas, [])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sin-email", action="store_true", help="No enviar email (para debug local)")
    ap.add_argument("--test-email", action="store_true", help="Mandar un email de prueba y salir, sin correr el monitoreo")
    ap.add_argument(
        "--auditoria", action="store_true",
        help="Solo lectura: evalúa todo el feed actual y muestra el término + fragmento que dispara "
        "cada match, sin tocar data/licitaciones_vistas.json ni enviar email (ver monitor.auditar()).",
    )
    ap.add_argument(
        "--test-rango-fechas", metavar="DESDE:HASTA",
        help="Solo lectura: manda un email con las licitaciones relevantes publicadas entre DESDE y HASTA "
        "(inclusive, formato YYYY-MM-DD:YYYY-MM-DD), sin tocar data/licitaciones_vistas.json ni el catálogo "
        "del visor (ver monitor.enviar_email_de_prueba_rango_fechas()). Ej.: --test-rango-fechas 2026-08-13:2026-08-14",
    )
    args = ap.parse_args()
    if args.test_email:
        enviar_email_de_prueba()
    elif args.auditoria:
        auditar()
    elif args.test_rango_fechas:
        try:
            desde, hasta = args.test_rango_fechas.split(":", 1)
        except ValueError:
            ap.error("--test-rango-fechas espera el formato YYYY-MM-DD:YYYY-MM-DD, ej. 2026-08-13:2026-08-14")
        else:
            enviar_email_de_prueba_rango_fechas(desde, hasta)
    else:
        main(enviar_email_flag=not args.sin_email)
