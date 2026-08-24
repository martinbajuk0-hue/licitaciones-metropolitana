import json
import shutil
import tempfile
import unittest
from pathlib import Path

import catalogo
import report


class TestCatalogo(unittest.TestCase):
    """Los datos se escriben en docs/data y docs/informes del repo real, así
    que cada test redirige catalogo.CATALOGO_DIR/INFORMES_DIR/CATALOGO_PATH a
    un directorio temporal (y lo restaura al final) en vez de tocar docs/
    de verdad.
    """

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())
        self._orig_catalogo_dir = catalogo.CATALOGO_DIR
        self._orig_informes_dir = catalogo.INFORMES_DIR
        self._orig_catalogo_path = catalogo.CATALOGO_PATH
        catalogo.CATALOGO_DIR = self._tmp / "data"
        catalogo.INFORMES_DIR = self._tmp / "informes"
        catalogo.CATALOGO_PATH = catalogo.CATALOGO_DIR / "llamados.json"

    def tearDown(self):
        catalogo.CATALOGO_DIR = self._orig_catalogo_dir
        catalogo.INFORMES_DIR = self._orig_informes_dir
        catalogo.CATALOGO_PATH = self._orig_catalogo_path
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _lic(self, id_="ocid-123", titulo="UTE licita piso vinílico"):
        return {
            "id": id_,
            "titulo": titulo,
            "url": "https://www.comprasestatales.gub.uy/ocds/lic-123",
            "fecha": "2026-08-14",
            "keyword": "piso vinílico",
            "fuente": "rubro",
            "documentos": ["https://www.comprasestatales.gub.uy/Pliegos/pedido_123.pdf"],
        }

    def _informe(self, titulo="UTE licita piso vinílico"):
        texto = "UTE licitación abreviada 10/2026 para piso vinílico, plazo de entrega: 30 dias."
        return report.analizar_licitacion(titulo, "https://example.com", texto)

    def test_registrar_llamado_crea_catalogo_y_entrada(self):
        lic = self._lic()
        informe = self._informe()
        catalogo.registrar_llamado(lic, informe)

        self.assertTrue(catalogo.CATALOGO_PATH.exists())
        data = json.loads(catalogo.CATALOGO_PATH.read_text(encoding="utf-8"))
        self.assertIn("ocid-123", data)
        entrada = data["ocid-123"]
        self.assertEqual(entrada["titulo"], lic["titulo"])
        self.assertEqual(entrada["score"], informe.clasificacion.puntaje)
        self.assertEqual(entrada["simbolo"], informe.clasificacion.simbolo)
        self.assertFalse(entrada["cambio_detectado"])
        self.assertEqual(entrada["notificaciones"], 1)

    def test_registrar_llamado_guarda_el_informe_completo_en_markdown(self):
        lic = self._lic()
        informe = self._informe()
        catalogo.registrar_llamado(lic, informe)

        data = json.loads(catalogo.CATALOGO_PATH.read_text(encoding="utf-8"))
        ruta_relativa = data["ocid-123"]["informe"]
        ruta_absoluta = catalogo.INFORMES_DIR.parent / ruta_relativa
        self.assertTrue(ruta_absoluta.exists())
        self.assertEqual(ruta_absoluta.read_text(encoding="utf-8"), informe.markdown)

    def test_registrar_llamado_sanitiza_ids_con_caracteres_no_seguros_para_filename(self):
        lic = self._lic(id_="ocds-593ade:2026-XYZ/001")
        informe = self._informe()
        catalogo.registrar_llamado(lic, informe)

        data = json.loads(catalogo.CATALOGO_PATH.read_text(encoding="utf-8"))
        entrada = data["ocds-593ade:2026-XYZ/001"]
        # El slug usado como filename no debe contener ':' ni '/'.
        self.assertNotIn(":", entrada["informe"])
        self.assertNotIn("ocds-593ade:2026-XYZ/001", entrada["informe"])

    def test_registrar_llamado_dos_veces_conserva_primera_deteccion_y_suma_notificaciones(self):
        lic = self._lic()
        informe = self._informe()
        catalogo.registrar_llamado(lic, informe)
        primera = json.loads(catalogo.CATALOGO_PATH.read_text(encoding="utf-8"))["ocid-123"]["primera_deteccion"]

        catalogo.registrar_llamado(lic, informe)
        data = json.loads(catalogo.CATALOGO_PATH.read_text(encoding="utf-8"))
        entrada = data["ocid-123"]
        self.assertEqual(entrada["primera_deteccion"], primera)
        self.assertEqual(entrada["notificaciones"], 2)

    def test_registrar_modificacion_marca_cambio_en_entrada_existente(self):
        lic = self._lic()
        catalogo.registrar_llamado(lic, self._informe())

        catalogo.registrar_modificacion(lic)
        data = json.loads(catalogo.CATALOGO_PATH.read_text(encoding="utf-8"))
        entrada = data["ocid-123"]
        self.assertTrue(entrada["cambio_detectado"])
        self.assertEqual(entrada["notificaciones"], 2)

    def test_registrar_modificacion_sobre_llamado_nunca_registrado_no_crea_entrada_a_medias(self):
        lic = self._lic(id_="nunca-visto")
        catalogo.registrar_modificacion(lic)
        # No existe el catálogo (nunca se llamó a registrar_llamado antes).
        self.assertFalse(catalogo.CATALOGO_PATH.exists())

    def test_registrar_llamado_usa_url_ficha_en_vez_de_url_json_cruda(self):
        # Bug reportado 2026-08-18: el link "Ver ficha en ARCE" del visor
        # abría el JSON del release OCDS en vez de la página humana de
        # ARCE. lic["url"] sigue siendo el JSON (lo necesita el pipeline
        # para leer título/descripción/documentos) — lo que debe guardarse
        # en el catálogo (lo que lee docs/index.html) es lic["url_ficha"].
        lic = self._lic()
        lic["url"] = "https://www.comprasestatales.gub.uy/ocds/release/llamado-1361110"
        lic["url_ficha"] = "https://www.comprasestatales.gub.uy/consultas/detalle/id/1361110"
        catalogo.registrar_llamado(lic, self._informe())

        data = json.loads(catalogo.CATALOGO_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            data["ocid-123"]["url_ficha"],
            "https://www.comprasestatales.gub.uy/consultas/detalle/id/1361110",
        )

    def test_registrar_llamado_guarda_que_es(self):
        # Pedido del usuario 2026-08-24: revisar_resultados.py reusa este
        # campo desde el catálogo (no vuelve a leer el pliego) para el
        # email de ganamos/perdimos — ver test_revisar_resultados.py.
        lic = self._lic()
        informe = self._informe()
        catalogo.registrar_llamado(lic, informe)

        data = json.loads(catalogo.CATALOGO_PATH.read_text(encoding="utf-8"))
        self.assertEqual(data["ocid-123"]["que_es"], informe.que_es)
        self.assertTrue(data["ocid-123"]["que_es"])

    def test_registrar_llamado_sin_url_ficha_cae_a_url(self):
        # Compatibilidad con llamados viejos del catálogo (o de la rama
        # OCDS/atom, donde lic["url"] ya es humana) que no traigan
        # "url_ficha" — no debe romper ni guardar None si hay "url".
        lic = self._lic()
        self.assertNotIn("url_ficha", lic)
        catalogo.registrar_llamado(lic, self._informe())

        data = json.loads(catalogo.CATALOGO_PATH.read_text(encoding="utf-8"))
        self.assertEqual(data["ocid-123"]["url_ficha"], lic["url"])


if __name__ == "__main__":
    unittest.main()
