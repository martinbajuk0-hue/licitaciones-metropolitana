import unittest
from datetime import date

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


if __name__ == "__main__":
    unittest.main()
