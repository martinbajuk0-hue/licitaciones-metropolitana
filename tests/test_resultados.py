import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import resultados

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _leer_fixture(nombre: str) -> str:
    return (_FIXTURES / nombre).read_text(encoding="utf-8")


class TestUrlFichaHumana(unittest.TestCase):
    def test_normaliza_url_json_ocds_a_ficha_humana(self):
        # El id de compra es el mismo número en ambas URLs — ver fix de
        # "Ver ficha en ARCE" (2026-08-18, test_catalogo.py).
        url = resultados.url_ficha_humana(
            "https://www.comprasestatales.gub.uy/ocds/release/llamado-1358442"
        )
        self.assertEqual(
            url, "https://www.comprasestatales.gub.uy/consultas/detalle/id/1358442"
        )

    def test_deja_una_ficha_humana_como_esta(self):
        url = resultados.url_ficha_humana(
            "https://www.comprasestatales.gub.uy/consultas/detalle/id/1358442"
        )
        self.assertEqual(
            url, "https://www.comprasestatales.gub.uy/consultas/detalle/id/1358442"
        )

    def test_url_sin_numero_devuelve_none(self):
        self.assertIsNone(resultados.url_ficha_humana("https://www.comprasestatales.gub.uy/consultas/"))

    def test_url_vacia_devuelve_none(self):
        self.assertIsNone(resultados.url_ficha_humana(""))
        self.assertIsNone(resultados.url_ficha_humana(None))


class TestParsearFichaAdjudicadaTotal(unittest.TestCase):
    """Ficha real (LA 5/2026, Hospital de San Carlos) con 1 oferente y 1
    ítem adjudicado a ese mismo oferente — Metropolitana no participó."""

    def setUp(self):
        self.resultado = resultados.parsear_ficha(_leer_fixture("ficha_adjudicada_total.html"))

    def test_lee_los_campos_de_resolucion(self):
        self.assertEqual(self.resultado.resolucion, "Adjudicada totalmente")
        self.assertEqual(self.resultado.resolucion_nro, "221/2026")
        self.assertEqual(self.resultado.fecha_resolucion, "03/06/2026")
        self.assertEqual(self.resultado.monto_total, "$ 692.472,00")

    def test_lee_el_oferente_unico(self):
        self.assertEqual(self.resultado.oferentes, [("218832770014", "MEDFX SISTEMAS SAS")])

    def test_lee_el_item_adjudicado(self):
        self.assertEqual(
            self.resultado.ganadores_por_item,
            [("218832770014", "MEDFX SISTEMAS SAS")],
        )

    def test_metropolitana_no_participo(self):
        self.assertFalse(self.resultado.nos_presentamos)
        self.assertIsNone(self.resultado.ganamos)
        self.assertEqual(resultados.estado_resumen(self.resultado), "no_presentamos")


class TestParsearFichaAdjudicadaParcial(unittest.TestCase):
    """Ficha real (LA 14/2026, UTEC) con 6 oferentes y 9 renglones
    adjudicados repartidos entre 2 proveedores distintos."""

    def setUp(self):
        self.resultado = resultados.parsear_ficha(_leer_fixture("ficha_adjudicada_parcial.html"))

    def test_lee_los_seis_oferentes(self):
        self.assertEqual(len(self.resultado.oferentes), 6)
        ruts = [rut for rut, _ in self.resultado.oferentes]
        self.assertIn("211101590014", ruts)
        self.assertIn("210201390019", ruts)

    def test_cuenta_cada_renglon_adjudicado_por_separado(self):
        # 3 renglones a BLUM SA + 1 a PRONTOMETAL en este fixture (subset
        # representativo del caso real, que tenía 9 en total).
        self.assertEqual(len(self.resultado.ganadores_por_item), 4)
        ruts_ganadores = {rut for rut, _ in self.resultado.ganadores_por_item}
        self.assertEqual(ruts_ganadores, {"211101590014", "210201390019"})

    def test_metropolitana_no_participo(self):
        self.assertFalse(self.resultado.nos_presentamos)
        self.assertEqual(resultados.estado_resumen(self.resultado), "no_presentamos")


class TestEstadoPendiente(unittest.TestCase):
    def test_sin_resolucion_es_pendiente_aunque_haya_oferentes(self):
        resultado = resultados.parsear_ficha(_leer_fixture("ficha_pendiente.html"))
        self.assertFalse(resultado.tiene_resolucion)
        self.assertTrue(resultado.nos_presentamos)  # ya abrió, y Metropolitana ofertó...
        self.assertIsNone(resultado.ganamos)  # ...pero todavía no hay para saber si ganó
        self.assertEqual(resultados.estado_resumen(resultado), "pendiente")

    def test_sin_tabla_de_oferentes_no_rompe(self):
        resultado = resultados.parsear_ficha("<html><body><main>Sin nada todavía.</main></body></html>")
        self.assertEqual(resultado.oferentes, [])
        self.assertFalse(resultado.nos_presentamos)
        self.assertEqual(resultados.estado_resumen(resultado), "pendiente")


class TestMetropolitanaGanaOPierde(unittest.TestCase):
    def test_metropolitana_gana(self):
        resultado = resultados.parsear_ficha(_leer_fixture("ficha_metropolitana_gana.html"))
        self.assertTrue(resultado.nos_presentamos)
        self.assertTrue(resultado.ganamos)
        self.assertEqual(resultados.estado_resumen(resultado), "ganamos")

    def test_metropolitana_pierde(self):
        resultado = resultados.parsear_ficha(_leer_fixture("ficha_metropolitana_pierde.html"))
        self.assertTrue(resultado.nos_presentamos)
        self.assertFalse(resultado.ganamos)
        self.assertEqual(resultados.estado_resumen(resultado), "perdimos")


class TestObtenerResultado(unittest.TestCase):
    """obtener_resultado() es la única función con red — se mockea
    requests.get para no depender de la disponibilidad real de ARCE."""

    @patch("resultados.requests.get")
    def test_consulta_la_ficha_humana_no_el_json_ocds(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = _leer_fixture("ficha_adjudicada_total.html")
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        resultado = resultados.obtener_resultado(
            "https://www.comprasestatales.gub.uy/ocds/release/llamado-1334894"
        )

        mock_get.assert_called_once()
        url_llamada = mock_get.call_args[0][0]
        self.assertEqual(
            url_llamada, "https://www.comprasestatales.gub.uy/consultas/detalle/id/1334894"
        )
        self.assertEqual(resultado.resolucion, "Adjudicada totalmente")

    @patch("resultados.requests.get")
    def test_error_de_red_devuelve_none_sin_excepcion(self, mock_get):
        import requests

        mock_get.side_effect = requests.RequestException("timeout")
        resultado = resultados.obtener_resultado(
            "https://www.comprasestatales.gub.uy/consultas/detalle/id/123"
        )
        self.assertIsNone(resultado)

    def test_url_no_normalizable_devuelve_none_sin_llamar_a_la_red(self):
        with patch("resultados.requests.get") as mock_get:
            resultado = resultados.obtener_resultado("")
            self.assertIsNone(resultado)
            mock_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
