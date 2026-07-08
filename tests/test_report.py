import unittest

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


if __name__ == "__main__":
    unittest.main()
