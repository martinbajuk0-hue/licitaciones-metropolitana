import unittest

import pricing


class TestPricing(unittest.TestCase):
    def test_item_sin_precio_cargado_no_inventa_numero(self):
        item = pricing.cotizar_item("piso_spc", 100)
        self.assertIsNone(item.precio_unitario)
        self.assertIsNone(item.subtotal)
        self.assertIn("SIN PRECIO CARGADO", item.nota)

    def test_cotizacion_incompleta_si_falta_algun_precio(self):
        resultado = pricing.cotizar([("piso_spc", 100), ("zocalo", 20)])
        self.assertFalse(resultado["cotizacion_completa"])
        self.assertIsNone(resultado["total"])


if __name__ == "__main__":
    unittest.main()
