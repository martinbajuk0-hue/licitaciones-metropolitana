import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import seguimiento
import seguimiento_issue


class TestSeguimientoIssue(unittest.TestCase):
    """seguimiento_issue.main() procesa el issue de GitHub que dispara
    .github/workflows/seguimiento.yml — cada test redirige
    seguimiento.SEGUIMIENTO_PATH y seguimiento_issue.COMENTARIO_PATH a
    archivos temporales (y los restaura al final) en vez de tocar
    docs/data/ ni escribir comentario_issue.txt en el repo real."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())
        self._orig_seg_path = seguimiento.SEGUIMIENTO_PATH
        self._orig_comentario_path = seguimiento_issue.COMENTARIO_PATH
        seguimiento.SEGUIMIENTO_PATH = self._tmp / "seguimiento.json"
        seguimiento_issue.COMENTARIO_PATH = self._tmp / "comentario_issue.txt"
        self._env_orig = dict(os.environ)

    def tearDown(self):
        seguimiento.SEGUIMIENTO_PATH = self._orig_seg_path
        seguimiento_issue.COMENTARIO_PATH = self._orig_comentario_path
        os.environ.clear()
        os.environ.update(self._env_orig)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _correr(self, titulo, cuerpo):
        with patch.dict(os.environ, {"ISSUE_TITLE": titulo, "ISSUE_BODY": cuerpo}, clear=False):
            os.environ.pop("GITHUB_OUTPUT", None)
            seguimiento_issue.main()
        return seguimiento.cargar(), seguimiento_issue.COMENTARIO_PATH.read_text(encoding="utf-8")

    def test_seguir_agrega_la_licitacion(self):
        cuerpo = "Título: Compra Directa 244/2026\nOrganismo: UTE\nFicha: https://www.comprasestatales.gub.uy/consultas/detalle/id/1370468"
        datos, comentario = self._correr("seguir: 1370468", cuerpo)

        self.assertIn("1370468", datos)
        self.assertEqual(datos["1370468"]["titulo"], "Compra Directa 244/2026")
        self.assertEqual(datos["1370468"]["organismo"], "UTE")
        self.assertEqual(datos["1370468"]["guids_notificados"], [])
        self.assertIn("Compra Directa 244/2026", comentario)

    def test_dejar_de_seguir_quita_la_licitacion(self):
        seguimiento.guardar({"1370468": {"titulo": "X", "organismo": "", "url_ficha": "", "guids_notificados": []}})

        datos, comentario = self._correr("dejar de seguir: 1370468", "")

        self.assertNotIn("1370468", datos)
        self.assertIn("Dejaste de seguir", comentario)

    def test_dejar_de_seguir_algo_no_seguido_no_rompe(self):
        datos, comentario = self._correr("dejar de seguir: 4242", "")
        self.assertEqual(datos, {})
        self.assertIn("no estaba en tu lista", comentario)

    def test_seguir_es_idempotente_conserva_guids_notificados(self):
        seguimiento.guardar({
            "1370468": {
                "titulo": "Vieja", "organismo": "", "url_ficha": "",
                "guids_notificados": ["aclar_llamado-1370468-0"], "marcado_en": "2026-01-01T00:00:00",
            }
        })
        cuerpo = "Título: Nueva\nOrganismo: \nFicha: "
        datos, _ = self._correr("seguir: 1370468", cuerpo)

        # Re-marcar no debe perder el historial de guids ya notificados
        # ni la fecha original de "marcado_en".
        self.assertEqual(datos["1370468"]["guids_notificados"], ["aclar_llamado-1370468-0"])
        self.assertEqual(datos["1370468"]["marcado_en"], "2026-01-01T00:00:00")
        self.assertEqual(datos["1370468"]["titulo"], "Nueva")

    def test_sin_id_detectable_no_modifica_nada_y_avisa(self):
        datos, comentario = self._correr("seguir esta licitación por favor", "")
        self.assertEqual(datos, {})
        self.assertIn("No pude identificar", comentario)

    def test_github_output_marca_cambio(self):
        output_path = self._tmp / "github_output.txt"
        cuerpo = "Título: X\nOrganismo: Y\nFicha: Z"
        with patch.dict(
            os.environ,
            {"ISSUE_TITLE": "seguir: 1370111", "ISSUE_BODY": cuerpo, "GITHUB_OUTPUT": str(output_path)},
        ):
            seguimiento_issue.main()
        self.assertEqual(output_path.read_text(encoding="utf-8").strip(), "cambio=true")


if __name__ == "__main__":
    unittest.main()
