import unittest

import checklist


class TestChecklist(unittest.TestCase):
    def test_detecta_rupe_exigido(self):
        texto = "Los oferentes deben estar inscriptos en el RUPE en estado activo."
        items = checklist.generar_checklist(texto)
        rupe = next(i for i in items if i.id == "rupe")
        self.assertEqual(rupe.estado.value, "exigido_en_pliego")
        self.assertIn("RUPE", rupe.evidencia.upper())

    def test_item_no_mencionado_queda_pendiente(self):
        texto = "Se solicita el suministro de 200 m2 de piso vinílico."
        items = checklist.generar_checklist(texto)
        seguros = next(i for i in items if i.id == "seguros")
        self.assertEqual(seguros.estado.value, "estandar_no_mencionado_verificar")

    def test_items_pendientes_y_exigidos_particionan_la_lista(self):
        texto = "Certificado único de BPS vigente. Garantía de mantenimiento de oferta del 1%."
        items = checklist.generar_checklist(texto)
        exigidos = checklist.items_exigidos(items)
        pendientes = checklist.items_pendientes_de_verificar(items)
        self.assertEqual(len(exigidos) + len(pendientes), len(items))
        self.assertTrue(any(i.id == "bps" for i in exigidos))


if __name__ == "__main__":
    unittest.main()
