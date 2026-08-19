import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import historial
import monitor


class TestMonitorFechaRango(unittest.TestCase):
    """monitor._fecha_lic_a_iso() es la pieza nueva y testeable sin red:
    normaliza lic['fecha'] (que puede venir en ISO del feed OCDS, o en
    RFC822 crudo si se cayó al fallback RSS — ver obtener_licitaciones())
    a 'YYYY-MM-DD' para poder compararla contra el rango de
    --test-rango-fechas.
    """

    def test_fecha_iso_se_devuelve_truncada_a_10_caracteres(self):
        self.assertEqual(monitor._fecha_lic_a_iso("2026-08-13"), "2026-08-13")
        self.assertEqual(monitor._fecha_lic_a_iso("2026-08-13T14:30:00Z"), "2026-08-13")

    def test_fecha_rfc822_se_normaliza_a_iso(self):
        self.assertEqual(monitor._fecha_lic_a_iso("Wed, 13 Aug 2026 10:00:00 GMT"), "2026-08-13")

    def test_fecha_vacia_devuelve_none(self):
        self.assertIsNone(monitor._fecha_lic_a_iso(""))

    def test_fecha_no_parseable_devuelve_none(self):
        self.assertIsNone(monitor._fecha_lic_a_iso("no es una fecha"))


class TestAlquilerDeInmueble(unittest.TestCase):
    """Caso real reportado por el usuario 2026-08-17: Concurso de Precios
    12/2026, "Contratación de local apto para el dictado de clases
    curriculares de Educación Física para los alumnos del liceo N°60 de
    Montevideo". La auditoría en vivo (run #190) mostró que matcheó por
    'arcos de fútbol', encontrado en un formulario tipo checklist donde
    el organismo le pregunta a cada local candidato qué equipamiento YA
    TIENE instalado:

        "10 (diez) pelotas de fútbol Sí …. No ...... Arcos de fútbol
        Sí …. No..... Red de voleibol Sí..."
        "Piso: Madera: .......... Baldosa: ............ Hormigón: ..."

    Es decir: el organismo busca ALQUILAR un local ya construido, no
    comprar productos — el pliego menciona madera/baldosa/arcos de
    fútbol únicamente para preguntar qué tiene el local candidato, no
    para pedir que se los provean. Metropolitana no alquila inmuebles,
    así que este tipo de compra nunca es una oportunidad real sin
    importar qué término del rubro aparezca casualmente.
    """

    def test_es_alquiler_de_inmueble_detecta_el_titulo_real(self):
        titulo = (
            'concurso de precios n° 12/2026 "contratación de local apto para el '
            "dictado de clases curriculares de educación física para los alumnos "
            'del liceo n°60 de montevideo"'
        )
        self.assertTrue(monitor._es_alquiler_de_inmueble(titulo))

    def test_es_alquiler_de_inmueble_no_dispara_con_texto_normal_del_rubro(self):
        texto = "suministro e instalación de piso vinílico y zócalos en el local comercial de la intendencia"
        self.assertFalse(monitor._es_alquiler_de_inmueble(texto))

    def test_arcos_de_futbol_en_checklist_de_local_alquilado_no_marca_relevante(self):
        lic = {
            "titulo": (
                'Concurso de Precios N° 12/2026 "Contratación de local apto para el '
                "dictado de clases curriculares de Educación Física para los alumnos "
                'del liceo N°60 de Montevideo"'
            ),
            "descripcion": "Contratación de local apto para el dictado de clases curriculares de Educación Física.",
            "documentos": [],
            "url": "https://www.comprasestatales.gub.uy/ocds/release/test-concurso-12-2026",
        }
        relevante, kw, fuente, texto = monitor.es_relevante(lic)
        self.assertFalse(relevante, f"No debería ser relevante (alquiler de local), pero marcó: {kw!r} (fuente: {fuente})")

    def test_alquiler_de_inmueble_no_se_detecta_solo_por_la_palabra_local(self):
        # Guarda contra un filtro demasiado amplio: la palabra "local" sola
        # (ej. "gobierno local", "sucursal local") no debe activar el filtro,
        # solo la frase completa "contratación/alquiler/arrendamiento de local(es)".
        texto = "el proveedor deberá tener representación local en montevideo para el soporte técnico"
        self.assertFalse(monitor._es_alquiler_de_inmueble(texto))


class TestEsRelevantePorCodigoArticulo(unittest.TestCase):
    """Pedido explícito del usuario 2026-08-18: si un llamado nuevo pide un
    ítem con el mismo "Código de artículo" ARCE (classification.id de
    OCDS, ver monitor._codigos_articulo()) que uno que Metropolitana ya
    facturó antes (historial.productos_por_codigo_ya_adjudicado()), el
    llamado se marca relevante SÍ O SÍ — sin pasar por el filtro de
    alquiler de inmueble ni por el umbral de 2+ términos de
    _decidir_relevancia(), porque es un match exacto por código, no una
    coincidencia de texto.

    Caso real verificado 2026-08-18: Compra Directa 10176/2026 (MEC),
    ítem "TATAMI" con Cód. Artículo 63663 (ver
    https://www.comprasestatales.gub.uy/ocds/release/llamado-1364508).
    """

    def setUp(self):
        self._orig_path = historial.HISTORIAL_PATH

    def tearDown(self):
        historial.HISTORIAL_PATH = self._orig_path
        historial._cargar.cache_clear()
        historial._items_metropolitana_normalizados.cache_clear()
        historial._codigos_metropolitana.cache_clear()

    def _usar_historial_con_tatami(self, tmp_path):
        data = {
            "generado": "2026-08-14",
            "items_metropolitana": [
                {"producto": "TATAMI", "codigo": "63663"},
                {"producto": "MOQUETTE", "codigo": "2925"},
            ],
            "items_otros_proveedores": [],
        }
        ruta = tmp_path / "historial.json"
        ruta.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        historial.HISTORIAL_PATH = ruta
        historial._cargar.cache_clear()
        historial._items_metropolitana_normalizados.cache_clear()
        historial._codigos_metropolitana.cache_clear()

    def test_llamado_real_tatami_matchea_por_codigo_sin_leer_pliego(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._usar_historial_con_tatami(Path(tmp))
            lic = {
                "titulo": "Compra Directa 10176/2026",
                "descripcion": (
                    "El Ministerio de Educación y Cultura invita a empresas interesadas a "
                    "presentar cotización para la adquisición de 115 placas de piso de goma "
                    "EVA tipo tatami."
                ),
                "documentos": [],
                "url": "https://www.comprasestatales.gub.uy/ocds/release/llamado-1364508",
                "codigos_articulo": ["63663"],
            }
            relevante, kw, fuente, texto_pliego = monitor.es_relevante(lic)
            self.assertTrue(relevante)
            self.assertEqual(fuente, monitor.FUENTE_CODIGO_ARTICULO)
            self.assertIn("TATAMI", kw)
            # No hizo falta leer/descargar el pliego para decidir: el match
            # por código alcanza y es más confiable que el texto.
            self.assertEqual(texto_pliego, "")

    def test_codigo_sin_match_en_historial_sigue_el_flujo_normal_por_texto(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._usar_historial_con_tatami(Path(tmp))
            lic = {
                "titulo": "Compra Directa 999/2026 — adquisición de resmas de papel A4",
                "descripcion": "Adquisición de resmas de papel A4 para oficina.",
                "documentos": [],
                "url": "https://www.comprasestatales.gub.uy/ocds/release/llamado-9999999",
                "codigos_articulo": ["11111"],  # no está en el historial
            }
            relevante, kw, fuente, texto_pliego = monitor.es_relevante(lic)
            self.assertFalse(relevante)

    def test_filtro_de_alquiler_de_inmueble_pisa_al_match_por_codigo(self):
        # Orden de prioridad invertido respecto a una primera versión de
        # este código: el filtro de alquiler de inmueble es un VETO
        # ABSOLUTO, ni siquiera un match por código lo pisa. Motivo
        # (evidencia real 2026-08-18): el historial puede tener códigos
        # genéricos o casos borde (ver historial._CODIGOS_NO_ESPECIFICOS,
        # ej. "ARRENDAMIENTO DE PISO") — más vale un falso negativo
        # ocasional que reintroducir el tipo de falso positivo que ya
        # causó "siento que no estás leyendo los pliegos".
        with tempfile.TemporaryDirectory() as tmp:
            self._usar_historial_con_tatami(Path(tmp))
            lic = {
                "titulo": 'Concurso de Precios N° 12/2026 "Contratación de local apto para clases"',
                "descripcion": "Contratación de local apto para el dictado de clases.",
                "documentos": [],
                "url": "https://www.comprasestatales.gub.uy/ocds/release/test-alquiler-con-codigo",
                "codigos_articulo": ["63663"],
            }
            relevante, kw, fuente, texto_pliego = monitor.es_relevante(lic)
            self.assertFalse(relevante)

    def test_sin_codigos_articulo_no_rompe_el_flujo_normal(self):
        # lic sin la clave "codigos_articulo" (ej. viniendo de la rama OCDS
        # vieja, o de un test que no la setea) no debe romper — debe
        # comportarse como si la lista estuviera vacía.
        lic = {
            "titulo": "Compra Directa 1/2026 — insumos varios",
            "descripcion": "Insumos varios de oficina.",
            "documentos": [],
            "url": "https://www.comprasestatales.gub.uy/ocds/release/test-sin-codigos",
        }
        relevante, kw, fuente, texto_pliego = monitor.es_relevante(lic)
        self.assertFalse(relevante)


class _RespuestaFalsa:
    """Doble mínimo de requests.Response para mockear requests.get() sin red."""

    def __init__(self, status_code=200, content=b"", json_data=None, text=""):
        self.status_code = status_code
        self.content = content
        self._json_data = json_data
        self.text = text
        self.headers = {"content-type": "application/xml"}

    def json(self):
        return self._json_data


def _rss_mensual_xml(items_guid: list[str]) -> bytes:
    # Mismo shape que produce comprasestatales.gub.uy/ocds/rss/AAAA/MM:
    # <channel><item><guid>llamado-123</guid><link>...</link>
    # <pubDate>...</pubDate><title>...</title></item>...</channel>
    items_xml = "".join(
        f"<item><guid>{g}</guid><link>https://www.comprasestatales.gub.uy/ocds/release/{g}</link>"
        f"<pubDate>Wed, 13 Aug 2026 10:00:00 GMT</pubDate><title>{g}</title></item>"
        for g in items_guid
    )
    return f"<rss><channel>{items_xml}</channel></rss>".encode("utf-8")


class TestMesesARelevar(unittest.TestCase):
    """monitor._meses_a_relevar() decide qué feeds RSS mensuales
    (settings.RSS_URL + "/AAAA/MM") pedir: el mes en curso + el anterior,
    para no perder cobertura los primeros días de cada mes (ver
    conversación 2026-08-18, "faltan organismos y rubros").
    """

    def test_mes_en_curso_y_anterior_mismo_anio(self):
        self.assertEqual(
            monitor._meses_a_relevar(datetime(2026, 8, 18)),
            [(2026, 7), (2026, 8)],
        )

    def test_enero_retrocede_a_diciembre_del_anio_anterior(self):
        self.assertEqual(
            monitor._meses_a_relevar(datetime(2026, 1, 15)),
            [(2025, 12), (2026, 1)],
        )


class TestObtenerLicitacionesFeedMensual(unittest.TestCase):
    """obtener_licitaciones() (rama RSS) ahora pide el feed RSS MENSUAL
    (mes actual + anterior) en vez del feed plano de 500 ítems — y, si se
    le pasa `vistos`, omite el refetch de detalle de ítems ya vistos
    (optimización necesaria: sin esto, cada corrida re-descargaría el
    detalle de los ~1000+ llamados del mes en vez de solo los nuevos).
    """

    def _mockear_ocds_caido_y_rss_mensual(self, mock_get, guids_por_mes, detalle_por_guid=None):
        detalle_por_guid = detalle_por_guid or {}

        def side_effect(url, headers=None, timeout=None):
            if url == monitor.settings.OCDS_URL:
                return _RespuestaFalsa(status_code=404, text="not found")
            for (anio, mes), guids in guids_por_mes.items():
                if url == f"{monitor.settings.RSS_URL}/{anio}/{mes:02d}":
                    return _RespuestaFalsa(status_code=200, content=_rss_mensual_xml(guids))
            # Fetch de detalle de un release individual.
            for guid, detalle in detalle_por_guid.items():
                if url.endswith(guid):
                    return _RespuestaFalsa(status_code=200, json_data=detalle)
            return _RespuestaFalsa(status_code=404, text="not found")

        mock_get.side_effect = side_effect

    @patch("monitor.datetime")
    @patch("monitor.requests.get")
    def test_pide_feed_mensual_de_mes_actual_y_anterior(self, mock_get, mock_datetime):
        mock_datetime.now.return_value = datetime(2026, 8, 18)
        self._mockear_ocds_caido_y_rss_mensual(
            mock_get,
            {
                (2026, 7): ["llamado-1"],
                (2026, 8): ["llamado-2"],
            },
            detalle_por_guid={
                "llamado-1": {"releases": [{"tender": {"title": "Julio", "description": ""}}]},
                "llamado-2": {"releases": [{"tender": {"title": "Agosto", "description": ""}}]},
            },
        )
        licitaciones = monitor.obtener_licitaciones()
        titulos = sorted(lic["titulo"] for lic in licitaciones)
        self.assertEqual(titulos, ["Agosto", "Julio"])

    @patch("monitor.datetime")
    @patch("monitor.requests.get")
    def test_vistos_omite_refetch_de_detalle_de_items_ya_vistos(self, mock_get, mock_datetime):
        mock_datetime.now.return_value = datetime(2026, 8, 18)
        self._mockear_ocds_caido_y_rss_mensual(
            mock_get,
            {
                (2026, 7): [],
                (2026, 8): ["llamado-3", "llamado-4"],
            },
            detalle_por_guid={
                "llamado-3": {"releases": [{"tender": {"title": "Nuevo", "description": ""}}]},
                "llamado-4": {"releases": [{"tender": {"title": "Viejo", "description": ""}}]},
            },
        )
        uid_viejo = monitor.hashlib.md5(b"llamado-4").hexdigest()
        vistos = {uid_viejo: {"titulo": "Viejo", "hash": "x", "primera_deteccion": "", "notificaciones": 1}}

        licitaciones = monitor.obtener_licitaciones(vistos)

        # El ya visto no debe aparecer en el resultado (main() lo saltea
        # igual por vistos, así que no hace falta re-traer su detalle)...
        titulos = [lic["titulo"] for lic in licitaciones]
        self.assertEqual(titulos, ["Nuevo"])
        # ...y en particular, nunca se pidió su release individual.
        urls_pedidas = [c.args[0] if c.args else c.kwargs.get("url") for c in mock_get.call_args_list]
        self.assertFalse(any(u.endswith("llamado-4") for u in urls_pedidas))

    @patch("monitor.datetime")
    @patch("monitor.requests.get")
    def test_sin_vistos_pide_detalle_de_todos_los_items(self, mock_get, mock_datetime):
        # auditar() y enviar_email_de_prueba_rango_fechas() llaman a
        # obtener_licitaciones() sin vistos (de solo lectura, quieren ver
        # todo) — deben seguir trayendo el detalle completo de cada ítem.
        mock_datetime.now.return_value = datetime(2026, 8, 18)
        self._mockear_ocds_caido_y_rss_mensual(
            mock_get,
            {
                (2026, 7): [],
                (2026, 8): ["llamado-5", "llamado-6"],
            },
            detalle_por_guid={
                "llamado-5": {"releases": [{"tender": {"title": "A", "description": ""}}]},
                "llamado-6": {"releases": [{"tender": {"title": "B", "description": ""}}]},
            },
        )
        licitaciones = monitor.obtener_licitaciones()
        self.assertEqual(sorted(lic["titulo"] for lic in licitaciones), ["A", "B"])


class TestUrlFichaArce(unittest.TestCase):
    """Bug reportado 2026-08-18: el link "Ver ficha en ARCE" del visor
    abría el JSON del release OCDS (lic["url"], usado internamente por el
    pipeline) en vez de la página humana de ARCE. obtener_licitaciones()
    (rama RSS) debe poblar además lic["url_ficha"] con
    /consultas/detalle/id/{id numérico}, extraído del <guid> del feed
    ("llamado-1361110" -> "1361110").
    """

    def _mockear_ocds_caido_y_rss_mensual(self, mock_get, guids_por_mes, detalle_por_guid=None):
        detalle_por_guid = detalle_por_guid or {}

        def side_effect(url, headers=None, timeout=None):
            if url == monitor.settings.OCDS_URL:
                return _RespuestaFalsa(status_code=404, text="not found")
            for (anio, mes), guids in guids_por_mes.items():
                if url == f"{monitor.settings.RSS_URL}/{anio}/{mes:02d}":
                    return _RespuestaFalsa(status_code=200, content=_rss_mensual_xml(guids))
            for guid, detalle in detalle_por_guid.items():
                if url.endswith(guid):
                    return _RespuestaFalsa(status_code=200, json_data=detalle)
            return _RespuestaFalsa(status_code=404, text="not found")

        mock_get.side_effect = side_effect

    @patch("monitor.datetime")
    @patch("monitor.requests.get")
    def test_url_ficha_apunta_a_la_pagina_humana_no_al_json(self, mock_get, mock_datetime):
        mock_datetime.now.return_value = datetime(2026, 8, 18)
        self._mockear_ocds_caido_y_rss_mensual(
            mock_get,
            {(2026, 7): [], (2026, 8): ["llamado-1361110"]},
            detalle_por_guid={
                "llamado-1361110": {"releases": [{"tender": {"title": "Piso vinílico", "description": ""}}]},
            },
        )
        licitaciones = monitor.obtener_licitaciones()
        self.assertEqual(len(licitaciones), 1)
        lic = licitaciones[0]
        self.assertEqual(
            lic["url"],
            "https://www.comprasestatales.gub.uy/ocds/release/llamado-1361110",
        )
        self.assertEqual(
            lic["url_ficha"],
            "https://www.comprasestatales.gub.uy/consultas/detalle/id/1361110",
        )

    @patch("monitor.datetime")
    @patch("monitor.requests.get")
    def test_url_ficha_cae_al_link_del_json_si_el_guid_no_matchea_el_patron(self, mock_get, mock_datetime):
        # _url_ficha_arce() es interno a obtener_licitaciones() (no hay
        # función module-level que testear en aislamiento), así que este
        # caso borde también se ejercita a través de la función pública.
        # No debería pasar en la práctica (ya se filtró por
        # _tipo_release == "llamado", que exige guid "llamado-<dígitos>"),
        # pero si igual llegara un guid con otro formato no hay que romper
        # ni devolver un link roto — se cae al link del JSON.
        mock_datetime.now.return_value = datetime(2026, 8, 18)
        # Un guid que matchea _tipo_release() ("llamado-...") pero no el
        # patrón numérico estricto de _url_ficha_arce() ("llamado-\d+$").
        guid_raro = "llamado-1361110-bis"
        link = f"https://www.comprasestatales.gub.uy/ocds/release/{guid_raro}"

        def side_effect(url, headers=None, timeout=None):
            if url == monitor.settings.OCDS_URL:
                return _RespuestaFalsa(status_code=404, text="not found")
            if url == f"{monitor.settings.RSS_URL}/2026/08":
                items_xml = (
                    f"<item><guid>{guid_raro}</guid><link>{link}</link>"
                    f"<pubDate>Wed, 13 Aug 2026 10:00:00 GMT</pubDate><title>{guid_raro}</title></item>"
                )
                return _RespuestaFalsa(status_code=200, content=f"<rss><channel>{items_xml}</channel></rss>".encode())
            if url == f"{monitor.settings.RSS_URL}/2026/07":
                return _RespuestaFalsa(status_code=200, content=b"<rss><channel></channel></rss>")
            if url == link:
                return _RespuestaFalsa(
                    status_code=200,
                    json_data={"releases": [{"tender": {"title": "Raro", "description": ""}}]},
                )
            return _RespuestaFalsa(status_code=404, text="not found")

        mock_get.side_effect = side_effect
        licitaciones = monitor.obtener_licitaciones()
        self.assertEqual(len(licitaciones), 1)
        self.assertEqual(licitaciones[0]["url_ficha"], link)


class TestEsPublicacionReciente(unittest.TestCase):
    """Reportado 2026-08-19: un problema de concurrencia entre corridas
    (ver TestMainFiltraEmailPorFechaYTecho más abajo) hizo que main()
    mandara un email con ~450 tarjetas de una sola vez — nada útil para
    "acción rápida" (pedido explícito del usuario). _es_publicacion_reciente()
    es el filtro que evita que backlog viejo termine en el email del día.
    """

    @patch("monitor.datetime")
    def test_publicado_hoy_es_reciente(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2026, 8, 19, 12, 0)
        mock_datetime.strptime = datetime.strptime
        lic = {"fecha": "2026-08-19"}
        self.assertTrue(monitor._es_publicacion_reciente(lic))

    @patch("monitor.datetime")
    def test_publicado_dentro_del_margen_es_reciente(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2026, 8, 19, 12, 0)
        mock_datetime.strptime = datetime.strptime
        lic = {"fecha": "2026-08-17"}  # 2 días atrás, == DIAS_MAX_PARA_ALERTA_POR_MAIL
        self.assertTrue(monitor._es_publicacion_reciente(lic))

    @patch("monitor.datetime")
    def test_publicado_hace_semanas_no_es_reciente(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2026, 8, 19, 12, 0)
        mock_datetime.strptime = datetime.strptime
        lic = {"fecha": "2026-08-01"}  # backlog típico del feed mensual
        self.assertFalse(monitor._es_publicacion_reciente(lic))

    @patch("monitor.datetime")
    def test_sin_fecha_falla_abierto_se_considera_reciente(self, mock_datetime):
        # Fail-open: mejor una alerta de más que perder silenciosamente un
        # llamado nuevo real por un pubDate vacío o no parseable.
        mock_datetime.now.return_value = datetime(2026, 8, 19, 12, 0)
        mock_datetime.strptime = datetime.strptime
        self.assertTrue(monitor._es_publicacion_reciente({"fecha": ""}))
        self.assertTrue(monitor._es_publicacion_reciente({"fecha": "no es una fecha"}))


class TestMainFiltraEmailPorFechaYTecho(unittest.TestCase):
    """Caso real 2026-08-18/19: una corrida procesó de una sola vez el
    backlog completo del feed mensual nuevo (ver monitor.py,
    _meses_a_relevar()) y mandó un único email con ~450 tarjetas. main()
    ahora filtra qué entra al email (no qué entra al catálogo del visor,
    que sigue recibiendo todo) por dos vías: antigüedad de publicación
    (DIAS_MAX_PARA_ALERTA_POR_MAIL) y un techo defensivo
    (MAX_ALERTAS_POR_EMAIL, mandando primero lo de mayor score).
    """

    def _lic(self, id_, titulo, fecha, score):
        return {
            "id": id_,
            "titulo": titulo,
            "descripcion": "desc",
            "fecha": fecha,
            "url": f"https://example.com/{id_}",
            "url_ficha": f"https://example.com/{id_}",
            "documentos": [],
            "keyword": "piso vinílico",
            "fuente": "rubro",
            "_score": score,
        }

    def _informe_falso(self, score):
        informe = MagicMock()
        informe.markdown = "informe"
        informe.clasificacion = MagicMock(puntaje=score, nivel=3, simbolo="★★★", etiqueta="Media")
        informe.ya_adjudicados = []
        informe.cierre = None
        return informe

    @patch("monitor.datetime")
    @patch("monitor.enviar_email")
    @patch("monitor.catalogo")
    @patch("monitor.report_mod")
    @patch("monitor._leer_pliego")
    @patch("monitor.es_relevante")
    @patch("monitor.guardar_vistos")
    @patch("monitor.cargar_vistos")
    @patch("monitor.obtener_licitaciones")
    def test_backlog_viejo_no_entra_al_email_pero_si_al_catalogo(
        self, mock_obtener, mock_cargar_vistos, mock_guardar_vistos, mock_es_relevante,
        mock_leer_pliego, mock_report_mod, mock_catalogo, mock_enviar_email, mock_datetime,
    ):
        mock_datetime.now.return_value = datetime(2026, 8, 19, 12, 0)
        mock_datetime.strptime = datetime.strptime
        mock_leer_pliego.return_value = monitor.parser_mod.PliegoExtraido()

        licitaciones = [
            self._lic("nueva-hoy", "Publicada hoy", "2026-08-19", 60),
            self._lic("backlog-viejo", "Backlog de hace semanas", "2026-08-01", 90),
        ]
        mock_cargar_vistos.return_value = {}
        mock_obtener.return_value = licitaciones
        mock_es_relevante.return_value = (True, "piso vinílico", "rubro", "")
        mock_report_mod.analizar_licitacion.side_effect = (
            lambda titulo, url, texto, errores, codigos_articulo=None: self._informe_falso(
                60 if titulo == "Publicada hoy" else 90
            )
        )

        monitor.main()

        # Las DOS se registran en el catálogo del visor (sin filtrar)...
        self.assertEqual(mock_catalogo.registrar_llamado.call_count, 2)
        # ...pero al email solo entra la publicada hoy, aunque la del
        # backlog tenga mayor score.
        args, _ = mock_enviar_email.call_args
        nuevas_enviadas, modificadas_enviadas, omitidas = args
        self.assertEqual([lic["titulo"] for lic in nuevas_enviadas], ["Publicada hoy"])
        self.assertEqual(omitidas, 1)

    @patch("monitor.datetime")
    @patch("monitor.enviar_email")
    @patch("monitor.catalogo")
    @patch("monitor.report_mod")
    @patch("monitor._leer_pliego")
    @patch("monitor.es_relevante")
    @patch("monitor.guardar_vistos")
    @patch("monitor.cargar_vistos")
    @patch("monitor.obtener_licitaciones")
    def test_techo_manda_las_de_mayor_score_primero(
        self, mock_obtener, mock_cargar_vistos, mock_guardar_vistos, mock_es_relevante,
        mock_leer_pliego, mock_report_mod, mock_catalogo, mock_enviar_email, mock_datetime,
    ):
        mock_datetime.now.return_value = datetime(2026, 8, 19, 12, 0)
        mock_datetime.strptime = datetime.strptime
        mock_leer_pliego.return_value = monitor.parser_mod.PliegoExtraido()

        # MAX_ALERTAS_POR_EMAIL + 5 licitaciones, todas publicadas hoy
        # (todas pasan el filtro de fecha), con scores decrecientes salvo
        # la última, que tiene el score más alto — debe sobrevivir el
        # techo mientras que algunas de score bajo quedan afuera.
        n = monitor.MAX_ALERTAS_POR_EMAIL + 5
        licitaciones = [self._lic(f"id-{i}", f"Lic {i}", "2026-08-19", 50) for i in range(n)]
        licitaciones[-1]["titulo"] = "La de mayor score"

        mock_cargar_vistos.return_value = {}
        mock_obtener.return_value = licitaciones

        def _es_relevante(lic):
            return True, "piso vinílico", "rubro", ""

        mock_es_relevante.side_effect = _es_relevante

        def _analizar(titulo, url, texto, errores, codigos_articulo=None):
            score = 99 if titulo == "La de mayor score" else 50
            return self._informe_falso(score)

        mock_report_mod.analizar_licitacion.side_effect = _analizar

        monitor.main()

        args, _ = mock_enviar_email.call_args
        nuevas_enviadas, _modificadas, omitidas = args
        self.assertEqual(len(nuevas_enviadas), monitor.MAX_ALERTAS_POR_EMAIL)
        self.assertEqual(omitidas, 5)
        self.assertIn("La de mayor score", [lic["titulo"] for lic in nuevas_enviadas])

    @patch("monitor.datetime")
    @patch("monitor.enviar_email")
    @patch("monitor.catalogo")
    @patch("monitor.report_mod")
    @patch("monitor._leer_pliego")
    @patch("monitor.es_relevante")
    @patch("monitor.guardar_vistos")
    @patch("monitor.cargar_vistos")
    @patch("monitor.obtener_licitaciones")
    def test_checkpoint_guarda_vistos_periodicamente_no_solo_al_final(
        self, mock_obtener, mock_cargar_vistos, mock_guardar_vistos, mock_es_relevante,
        mock_leer_pliego, mock_report_mod, mock_catalogo, mock_enviar_email, mock_datetime,
    ):
        # Evidencia real 2026-08-19: la corrida #201 se canceló a mitad de
        # camino después de ~50 min de procesar backlog, sin haber
        # guardado nada (guardar_vistos() solo se llamaba una vez al
        # final del loop) — todo ese trabajo se perdió. Ahora debe haber
        # checkpoints periódicos, no un solo guardado al final.
        mock_datetime.now.return_value = datetime(2026, 8, 19, 12, 0)
        mock_datetime.strptime = datetime.strptime
        mock_leer_pliego.return_value = monitor.parser_mod.PliegoExtraido()

        n = 2 * monitor.CHECKPOINT_CADA_N_ITEMS + 1
        licitaciones = [self._lic(f"id-{i}", f"Lic {i}", "2026-08-19", 50) for i in range(n)]
        mock_cargar_vistos.return_value = {}
        mock_obtener.return_value = licitaciones
        mock_es_relevante.return_value = (True, "piso vinílico", "rubro", "")
        mock_report_mod.analizar_licitacion.side_effect = lambda *a, **k: self._informe_falso(50)

        monitor.main()

        # 2 checkpoints intermedios + 1 guardado final = 3.
        self.assertEqual(mock_guardar_vistos.call_count, 3)


if __name__ == "__main__":
    unittest.main()
