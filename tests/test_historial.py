import json
import unittest
from pathlib import Path

import historial


class TestHistorial(unittest.TestCase):
    """historial._cargar() y _items_metropolitana_normalizados() usan
    functools.lru_cache — cada test redirige historial.HISTORIAL_PATH a un
    JSON de prueba y limpia la cache antes/después, igual que
    test_catalogo.py redirige las rutas de catalogo.py, para no depender
    del knowledge/historial_adjudicaciones_metropolitana.json real ni
    filtrar estado entre tests.
    """

    def setUp(self):
        self._orig_path = historial.HISTORIAL_PATH

    def tearDown(self):
        historial.HISTORIAL_PATH = self._orig_path
        historial._cargar.cache_clear()
        historial._items_metropolitana_normalizados.cache_clear()

    def _usar_datos(self, tmp_path, items_metropolitana):
        data = {
            "generado": "2026-08-14",
            "items_metropolitana": items_metropolitana,
            "items_otros_proveedores": [],
        }
        ruta = tmp_path / "historial.json"
        ruta.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        historial.HISTORIAL_PATH = ruta
        historial._cargar.cache_clear()
        historial._items_metropolitana_normalizados.cache_clear()

    def test_sin_archivo_devuelve_lista_vacia(self):
        historial.HISTORIAL_PATH = Path("/tmp/no_existe_historial_de_prueba.json")
        historial._cargar.cache_clear()
        historial._items_metropolitana_normalizados.cache_clear()
        self.assertEqual(historial.productos_ya_adjudicados(["piso vinílico"]), [])

    def test_matchea_termino_dentro_del_nombre_del_producto(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._usar_datos(Path(tmp), [
                {"producto": "COLOCACION DE VINILICOS", "codigo": "12345"},
                {"producto": "MOQUETTE PARA OFICINA", "codigo": "67890"},
            ])
            resultado = historial.productos_ya_adjudicados(["vinilico"])
            self.assertEqual(resultado, ["COLOCACION DE VINILICOS"])

    def test_matchea_ignorando_acentos_y_mayusculas(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._usar_datos(Path(tmp), [
                {"producto": "PISO DE GOMA", "codigo": "111"},
            ])
            resultado = historial.productos_ya_adjudicados(["Goma"])
            self.assertEqual(resultado, ["PISO DE GOMA"])

    def test_sin_match_devuelve_lista_vacia(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._usar_datos(Path(tmp), [
                {"producto": "CESPED SINTETICO", "codigo": "222"},
            ])
            resultado = historial.productos_ya_adjudicados(["moquette"])
            self.assertEqual(resultado, [])

    def test_terminos_vacios_devuelve_lista_vacia_sin_leer_archivo(self):
        self.assertEqual(historial.productos_ya_adjudicados([]), [])

    def test_deduplica_productos_repetidos_en_el_historial(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._usar_datos(Path(tmp), [
                {"producto": "PISO FLOTANTE", "codigo": "1"},
                {"producto": "PISO FLOTANTE", "codigo": "2"},
            ])
            resultado = historial.productos_ya_adjudicados(["piso flotante"])
            self.assertEqual(resultado, ["PISO FLOTANTE"])


if __name__ == "__main__":
    unittest.main()
