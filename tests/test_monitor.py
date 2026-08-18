import json
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
