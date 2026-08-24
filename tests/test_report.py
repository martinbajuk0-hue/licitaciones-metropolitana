import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import historial
import report


class TestReport(unittest.TestCase):
    def test_clasificacion_no_presentarse_con_score_bajo(self):
        clasif = report.clasificar_oportunidad(0)
        self.assertEqual(clasif.nivel, 1)
        self.assertEqual(clasif.etiqueta, "No presentarse")

    def test_clasificacion_excelente_con_score_alto(self):
        clasif = report.clasificar_oportunidad(90)
        self.assertEqual(clasif.nivel, 5)
        self.assertEqual(clasif.etiqueta, "Excelente")

    def test_generar_informe_markdown_no_rompe_con_texto_minimo(self):
        texto = "UTE licitación abreviada 10/2026 para piso vinílico, plazo de entrega: 30 dias."
        md = report.generar_informe_markdown("Prueba", "https://example.com", texto)
        self.assertIn("# Informe de licitación", md)
        self.assertIn("Clasificación", md)

    def test_analizar_licitacion_expone_la_misma_clasificacion_que_el_markdown(self):
        # Regresión: monitor.py llegó a recalcular la clasificación del
        # email por separado, con riesgos/checklist en 0, mostrando una
        # estrella distinta a la del informe real. analizar_licitacion()
        # debe ser la única fuente de verdad para ambos.
        texto = "UTE licitación abreviada 10/2026 para piso vinílico, plazo de entrega: 30 dias."
        informe = report.analizar_licitacion("Prueba", "https://example.com", texto)
        self.assertIn(f"score {informe.clasificacion.puntaje}/100", informe.markdown)
        self.assertEqual(report.generar_informe_markdown("Prueba", "https://example.com", texto), informe.markdown)

    def test_riesgos_detectados_bajan_el_score_de_clasificacion(self):
        texto_base = "UTE licita piso vinílico para oficinas."
        texto_riesgoso = texto_base + " Multa de hasta 20% del contrato. Rescision del contrato ante incumplimiento."
        score_base = report.analizar_licitacion("A", "", texto_base).clasificacion.puntaje
        score_riesgoso = report.analizar_licitacion("B", "", texto_riesgoso).clasificacion.puntaje
        self.assertLess(score_riesgoso, score_base)

    def test_texto_cierre_sin_fecha_identificada(self):
        self.assertEqual(
            report.texto_cierre(None),
            "Fecha de cierre no identificada — verificar manualmente",
        )

    def test_texto_cierre_hoy(self):
        hoy = date(2026, 8, 17)
        self.assertEqual(report.texto_cierre("2026-08-17", hoy=hoy), "Cierra hoy")

    def test_texto_cierre_manana(self):
        hoy = date(2026, 8, 17)
        self.assertEqual(report.texto_cierre("2026-08-18", hoy=hoy), "Cierra mañana")

    def test_texto_cierre_en_n_dias(self):
        hoy = date(2026, 8, 17)
        self.assertEqual(report.texto_cierre("2026-08-27", hoy=hoy), "Cierra en 10 días")

    def test_texto_cierre_ya_paso(self):
        hoy = date(2026, 8, 17)
        self.assertEqual(
            report.texto_cierre("2026-08-10", hoy=hoy),
            "Cierre 2026-08-10 (ya pasó — verificar si sigue vigente)",
        )

    def test_analizar_licitacion_expone_ya_adjudicados_y_cierre(self):
        # Regresión: InformeLicitacion sumó ya_adjudicados/cierre — deben
        # quedar poblados (no None) para que monitor.py y catalogo.py los
        # puedan usar sin chequeos adicionales.
        texto = "UTE licitación abreviada 10/2026 para piso vinílico, plazo de entrega: 30 dias."
        informe = report.analizar_licitacion("Prueba", "https://example.com", texto)
        self.assertIsInstance(informe.ya_adjudicados, list)
        self.assertIsInstance(informe.cierre, str)
        self.assertTrue(informe.cierre)

    def test_analizar_licitacion_expone_que_es_y_lo_incluye_en_el_markdown(self):
        # Pedido del usuario 2026-08-24: resumen corto de "qué es esta
        # licitación" disponible como campo propio (para monitor.py/
        # catalogo.py, sin tener que re-parsear el resumen ejecutivo
        # completo) y también visible en el informe Markdown.
        texto = "UTE licitación abreviada 10/2026 para piso vinílico, plazo de entrega: 30 dias."
        informe = report.analizar_licitacion("Prueba", "https://example.com", texto)
        self.assertIsInstance(informe.que_es, str)
        self.assertTrue(informe.que_es)
        self.assertIn(f"**Qué es:** {informe.que_es}", informe.markdown)


class TestCodigoArticuloEnInforme(unittest.TestCase):
    """codigos_articulo (classification.id de OCDS) suma un bonus fuerte al
    score y aparece primero en "Ya adjudicaste antes" — pedido explícito
    del usuario 2026-08-18: es la señal más confiable posible (código
    exacto, no coincidencia de texto)."""

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
            "items_metropolitana": [{"producto": "TATAMI", "codigo": "63663"}],
            "items_otros_proveedores": [],
        }
        ruta = tmp_path / "historial.json"
        ruta.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        historial.HISTORIAL_PATH = ruta
        historial._cargar.cache_clear()
        historial._items_metropolitana_normalizados.cache_clear()
        historial._codigos_metropolitana.cache_clear()

    def test_codigo_matcheado_sube_el_score_y_aparece_en_ya_adjudicados(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._usar_historial_con_tatami(Path(tmp))
            texto = "Adquisición de 115 placas de piso de goma EVA tipo tatami."

            sin_codigo = report.analizar_licitacion("A", "", texto)
            con_codigo = report.analizar_licitacion("B", "", texto, codigos_articulo=["63663"])

            self.assertGreater(con_codigo.clasificacion.puntaje, sin_codigo.clasificacion.puntaje)
            self.assertIn("TATAMI", con_codigo.ya_adjudicados)
            self.assertTrue(
                any("código de artículo ARCE ya adjudicado" in r for r in con_codigo.probabilidad["razones"])
            )

    def test_codigo_sin_match_no_altera_el_score(self):
        # Texto neutro que no menciona "tatami" en ningún lado — así el
        # único canal posible para "Ya adjudicaste antes" es el código, y
        # un código que no está en el historial no debe sumar bonus ni
        # aparecer en ya_adjudicados.
        with tempfile.TemporaryDirectory() as tmp:
            self._usar_historial_con_tatami(Path(tmp))
            texto = "Adquisición de resmas de papel A4 para oficina."

            sin_codigos = report.analizar_licitacion("A", "", texto)
            codigo_ajeno = report.analizar_licitacion("B", "", texto, codigos_articulo=["00000"])

            self.assertEqual(sin_codigos.clasificacion.puntaje, codigo_ajeno.clasificacion.puntaje)
            self.assertNotIn("TATAMI", codigo_ajeno.ya_adjudicados)


if __name__ == "__main__":
    unittest.main()
