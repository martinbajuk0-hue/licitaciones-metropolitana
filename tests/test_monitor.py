import unittest

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


if __name__ == "__main__":
    unittest.main()
