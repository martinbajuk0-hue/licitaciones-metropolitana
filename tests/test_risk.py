import unittest

import risk


class TestRisk(unittest.TestCase):
    def test_detecta_multa_porcentual(self):
        texto = "El oferente incumplidor abonará una multa de hasta 10% del monto del contrato."
        riesgos = risk.detectar_multas_y_penalidades(texto)
        self.assertTrue(any("Multa porcentual" in r.descripcion for r in riesgos))

    def test_detecta_certificacion_iso(self):
        texto = "Se exige certificación ISO 9001 vigente del fabricante."
        riesgos = risk.detectar_certificaciones_especiales(texto)
        self.assertTrue(any("ISO" in r.descripcion for r in riesgos))

    def test_detecta_contradiccion_de_plazos(self):
        texto = (
            "El plazo de entrega: 30 dias sera de cumplimiento estricto. "
            "En el anexo se establece que el plazo de entrega: 45 dias corridos."
        )
        riesgos = risk.detectar_contradicciones(texto)
        self.assertTrue(any(r.categoria == "contradicciones" for r in riesgos))

    def test_sin_riesgos_en_texto_neutro(self):
        texto = "Se solicita cotización de pisos vinílicos para oficina."
        riesgos = risk.analizar_riesgos(texto)
        self.assertEqual([r for r in riesgos if r.categoria == "multas_penalidades"], [])

    def test_detecta_garantia_fiel_cumplimiento_con_texto_intermedio(self):
        texto = "Garantía de fiel cumplimiento de contrato: 5% del monto adjudicado."
        riesgos = risk.detectar_garantias_exigentes(texto)
        self.assertTrue(any("fiel cumplimiento" in r.descripcion for r in riesgos))

    def test_plazo_de_entrega_normal_no_se_marca_como_ajustado(self):
        texto = "Plazo de entrega: 30 dias corridos desde la notificacion de la orden de compra."
        riesgos = risk.detectar_plazos_ajustados(texto)
        self.assertEqual(riesgos, [])

    def test_plazo_de_entrega_corto_si_se_marca_como_ajustado(self):
        texto = "Plazo de entrega: 5 dias corridos desde la notificacion de la orden de compra."
        riesgos = risk.detectar_plazos_ajustados(texto)
        self.assertTrue(any("ajustado" in r.descripcion for r in riesgos))

    def test_orden_por_severidad(self):
        texto = (
            "multa de hasta 5% del contrato. certificacion iso 14001 requerida."
        )
        riesgos = risk.analizar_riesgos(texto)
        severidades = [r.severidad for r in riesgos]
        self.assertEqual(severidades, sorted(severidades, key=lambda s: {"alta": 0, "media": 1, "baja": 2}[s.value]))


if __name__ == "__main__":
    unittest.main()
