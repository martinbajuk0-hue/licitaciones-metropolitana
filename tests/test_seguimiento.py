import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import seguimiento
from tests.test_monitor import _RespuestaFalsa, _rss_mensual_xml


class TestCargarGuardar(unittest.TestCase):
    """cargar()/guardar() leen y escriben docs/data/seguimiento.json — cada
    test redirige seguimiento.SEGUIMIENTO_PATH a un archivo temporal (y lo
    restaura al final) en vez de tocar docs/data/ del repo real."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())
        self._orig_path = seguimiento.SEGUIMIENTO_PATH
        seguimiento.SEGUIMIENTO_PATH = self._tmp / "seguimiento.json"

    def tearDown(self):
        seguimiento.SEGUIMIENTO_PATH = self._orig_path
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_cargar_sin_archivo_devuelve_vacio(self):
        self.assertEqual(seguimiento.cargar(), {})

    def test_guardar_y_recargar_conserva_los_datos(self):
        datos = {"1370468": {"titulo": "Compra Directa 244/2026", "guids_notificados": []}}
        seguimiento.guardar(datos)
        self.assertEqual(seguimiento.cargar(), datos)


class TestEtiquetaTipo(unittest.TestCase):
    def test_tipo_conocido_usa_la_traduccion(self):
        self.assertEqual(seguimiento.etiqueta_tipo("aclar_llamado"), "Aclaración")
        self.assertEqual(seguimiento.etiqueta_tipo("ajuste_llamado"), "Ajuste / modificación")

    def test_tipo_desconocido_no_se_inventa_una_descripcion(self):
        # No hay evidencia confirmada de qué es "tipo_raro_xyz" — se
        # muestra el nombre crudo del feed formateado, nunca una
        # traducción inventada.
        self.assertEqual(seguimiento.etiqueta_tipo("tipo_raro_xyz"), "Tipo raro xyz")


class TestRevisar(unittest.TestCase):
    """revisar() escanea el feed RSS mensual buscando releases nuevos
    (tipo != "llamado") para los id_compra marcados en `seguimiento` —
    mismo shape de feed que monitor.obtener_licitaciones() (reutiliza los
    dobles de tests.test_monitor: _RespuestaFalsa, _rss_mensual_xml)."""

    def _mockear_rss(self, mock_get, guids_por_mes, detalle_por_guid=None):
        detalle_por_guid = detalle_por_guid or {}

        def side_effect(url, headers=None, timeout=None):
            for (anio, mes), guids in guids_por_mes.items():
                if url == f"{seguimiento.settings.RSS_URL}/{anio}/{mes:02d}":
                    return _RespuestaFalsa(status_code=200, content=_rss_mensual_xml(guids))
            for guid, detalle in detalle_por_guid.items():
                if url.endswith(guid):
                    return _RespuestaFalsa(status_code=200, json_data=detalle)
            return _RespuestaFalsa(status_code=404, text="not found")

        mock_get.side_effect = side_effect

    @patch("seguimiento.datetime")
    @patch("seguimiento.requests.get")
    def test_detecta_aclaracion_nueva_sobre_llamado_seguido(self, mock_get, mock_datetime):
        mock_datetime.now.return_value = datetime(2026, 8, 18)
        self._mockear_rss(
            mock_get,
            {
                (2026, 7): [],
                (2026, 8): ["llamado-1370468", "aclar_llamado-1370468-0"],
            },
            detalle_por_guid={
                "aclar_llamado-1370468-0": {"releases": [{"tender": {"description": "Se aclara el rubrado"}}]},
            },
        )
        seg = {"1370468": {"titulo": "Compra Directa 244/2026", "guids_notificados": []}}

        novedades = seguimiento.revisar(seg)

        self.assertEqual(len(novedades), 1)
        self.assertEqual(novedades[0]["tipo"], "aclar_llamado")
        self.assertEqual(novedades[0]["id_compra"], "1370468")
        self.assertEqual(novedades[0]["descripcion_release"], "Se aclara el rubrado")
        # El guid queda marcado como notificado in-place, para no repetir
        # el aviso en la próxima corrida.
        self.assertIn("aclar_llamado-1370468-0", seg["1370468"]["guids_notificados"])

    @patch("seguimiento.datetime")
    @patch("seguimiento.requests.get")
    def test_no_alerta_por_el_llamado_original(self, mock_get, mock_datetime):
        mock_datetime.now.return_value = datetime(2026, 8, 18)
        self._mockear_rss(mock_get, {(2026, 7): [], (2026, 8): ["llamado-1370468"]})
        seg = {"1370468": {"titulo": "X", "guids_notificados": []}}

        self.assertEqual(seguimiento.revisar(seg), [])

    @patch("seguimiento.datetime")
    @patch("seguimiento.requests.get")
    def test_no_repite_un_guid_ya_notificado(self, mock_get, mock_datetime):
        mock_datetime.now.return_value = datetime(2026, 8, 18)
        self._mockear_rss(
            mock_get,
            {(2026, 7): [], (2026, 8): ["aclar_llamado-1370468-0"]},
            detalle_por_guid={"aclar_llamado-1370468-0": {"releases": [{"tender": {}}]}},
        )
        seg = {"1370468": {"titulo": "X", "guids_notificados": ["aclar_llamado-1370468-0"]}}

        self.assertEqual(seguimiento.revisar(seg), [])

    @patch("seguimiento.datetime")
    @patch("seguimiento.requests.get")
    def test_ignora_releases_de_ids_no_seguidos(self, mock_get, mock_datetime):
        mock_datetime.now.return_value = datetime(2026, 8, 18)
        self._mockear_rss(
            mock_get,
            {(2026, 7): [], (2026, 8): ["aclar_llamado-999-0"]},
            detalle_por_guid={"aclar_llamado-999-0": {"releases": [{"tender": {}}]}},
        )
        seg = {"1370468": {"titulo": "X", "guids_notificados": []}}

        self.assertEqual(seguimiento.revisar(seg), [])

    def test_sin_nada_seguido_no_pide_red(self):
        with patch("seguimiento.requests.get") as mock_get:
            self.assertEqual(seguimiento.revisar({}), [])
            mock_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
