import json
import tempfile
import unittest
from pathlib import Path

import historial
import performance


class TestPerformanceCalcular(unittest.TestCase):
    """performance.calcular() agrega knowledge/historial_adjudicaciones_
    metropolitana.json (el mismo archivo que lee historial.py) para la
    pestaña "Performance" del visor. Cada test redirige historial.
    HISTORIAL_PATH a un JSON de prueba chico y controlado, igual que
    test_historial.py, para no depender de los 761 ítems reales.
    """

    def setUp(self):
        self._orig_path = historial.HISTORIAL_PATH

    def tearDown(self):
        historial.HISTORIAL_PATH = self._orig_path
        historial._cargar.cache_clear()
        historial._items_metropolitana_normalizados.cache_clear()
        historial._codigos_metropolitana.cache_clear()

    def _usar_datos(self, tmp_path, items_metropolitana, generado="2026-08-14"):
        data = {
            "generado": generado,
            "items_metropolitana": items_metropolitana,
            "items_otros_proveedores": [],
        }
        ruta = tmp_path / "historial.json"
        ruta.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        historial.HISTORIAL_PATH = ruta
        historial._cargar.cache_clear()
        historial._items_metropolitana_normalizados.cache_clear()
        historial._codigos_metropolitana.cache_clear()

    def test_totales_basicos(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._usar_datos(Path(tmp), [
                {"fecha": "16/06/2026", "organismo": "Poder Legislativo", "tipo": "Compra Directa",
                 "numero": "566/2026", "producto": "MOQUETTE", "codigo": "2925", "importe": 100.0},
                {"fecha": "16/06/2026", "organismo": "Poder Legislativo", "tipo": "Compra Directa",
                 "numero": "566/2026", "producto": "COLOCACION DE MOQUETTE", "codigo": "9", "importe": 50.0},
                {"fecha": "01/01/2025", "organismo": "UTE", "tipo": "Licitación Abreviada",
                 "numero": "1/2025", "producto": "PISO FLOTANTE", "codigo": "1", "importe": 200.0},
            ])
            r = performance.calcular()
            self.assertEqual(r["items_adjudicados"], 3)
            # Los dos primeros ítems son el mismo llamado (mismo organismo +
            # número) -> cuentan como 1 solo llamado, no 2.
            self.assertEqual(r["total_llamados"], 2)
            self.assertEqual(r["organismos_distintos"], 2)
            self.assertAlmostEqual(r["total_adjudicado"], 350.0)

    def test_evolucion_anual_agrupa_por_anio_de_fecha_dd_mm_aaaa(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._usar_datos(Path(tmp), [
                {"fecha": "16/06/2026", "organismo": "A", "tipo": "Compra Directa",
                 "numero": "1/2026", "producto": "X", "codigo": "1", "importe": 100.0},
                {"fecha": "01/01/2025", "organismo": "B", "tipo": "Compra Directa",
                 "numero": "2/2025", "producto": "Y", "codigo": "2", "importe": 200.0},
            ])
            r = performance.calcular()
            por_anio = {e["anio"]: e for e in r["evolucion_anual"]}
            self.assertEqual(por_anio["2026"]["importe"], 100.0)
            self.assertEqual(por_anio["2025"]["importe"], 200.0)
            self.assertEqual(por_anio["2026"]["llamados"], 1)

    def test_top_organismos_ordenado_por_importe_descendente(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._usar_datos(Path(tmp), [
                {"fecha": "01/01/2025", "organismo": "Chico", "tipo": "Compra Directa",
                 "numero": "1/2025", "producto": "X", "codigo": "1", "importe": 10.0},
                {"fecha": "01/01/2025", "organismo": "Grande", "tipo": "Compra Directa",
                 "numero": "2/2025", "producto": "Y", "codigo": "2", "importe": 1000.0},
            ])
            r = performance.calcular()
            self.assertEqual(r["top_organismos"][0]["organismo"], "Grande")

    def test_distribucion_tipo_cuenta_llamados_e_items_por_separado(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._usar_datos(Path(tmp), [
                {"fecha": "01/01/2025", "organismo": "A", "tipo": "Compra Directa",
                 "numero": "1/2025", "producto": "X", "codigo": "1", "importe": 10.0},
                {"fecha": "01/01/2025", "organismo": "A", "tipo": "Compra Directa",
                 "numero": "1/2025", "producto": "Y", "codigo": "2", "importe": 20.0},
            ])
            r = performance.calcular()
            fila = r["distribucion_tipo"][0]
            self.assertEqual(fila["tipo"], "Compra Directa")
            self.assertEqual(fila["items"], 2)
            self.assertEqual(fila["llamados"], 1)

    def test_articulos_mas_adjudicados_deduplica_organismos(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._usar_datos(Path(tmp), [
                {"fecha": "01/01/2025", "organismo": "A", "tipo": "Compra Directa",
                 "numero": "1/2025", "producto": "MOQUETTE", "codigo": "1", "importe": 10.0},
                {"fecha": "01/01/2025", "organismo": "A", "tipo": "Compra Directa",
                 "numero": "2/2025", "producto": "MOQUETTE", "codigo": "1", "importe": 20.0},
                {"fecha": "01/01/2025", "organismo": "B", "tipo": "Compra Directa",
                 "numero": "3/2025", "producto": "MOQUETTE", "codigo": "1", "importe": 5.0},
            ])
            r = performance.calcular()
            fila = next(a for a in r["articulos_mas_adjudicados"] if a["producto"] == "MOQUETTE")
            self.assertEqual(fila["veces"], 3)
            self.assertEqual(fila["organismos"], 2)
            self.assertAlmostEqual(fila["importe"], 35.0)

    def test_concentracion_de_clientes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._usar_datos(Path(tmp), [
                {"fecha": "01/01/2025", "organismo": "Grande", "tipo": "Compra Directa",
                 "numero": "1/2025", "producto": "X", "codigo": "1", "importe": 75.0},
                {"fecha": "01/01/2025", "organismo": "Chico", "tipo": "Compra Directa",
                 "numero": "2/2025", "producto": "Y", "codigo": "2", "importe": 25.0},
            ])
            r = performance.calcular()
            self.assertEqual(r["concentracion"]["organismo"], "Grande")
            self.assertEqual(r["concentracion"]["porcentaje"], 75.0)

    def test_sin_datos_no_rompe(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._usar_datos(Path(tmp), [])
            r = performance.calcular()
            self.assertEqual(r["items_adjudicados"], 0)
            self.assertEqual(r["total_llamados"], 0)
            self.assertEqual(r["total_adjudicado"], 0)
            self.assertEqual(r["concentracion"]["organismo"], None)
            self.assertEqual(r["concentracion"]["porcentaje"], 0)

    def test_generar_escribe_el_json_en_disco(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._usar_datos(Path(tmp), [
                {"fecha": "01/01/2025", "organismo": "A", "tipo": "Compra Directa",
                 "numero": "1/2025", "producto": "X", "codigo": "1", "importe": 10.0},
            ])
            with tempfile.TemporaryDirectory() as out_tmp:
                orig_perf_path = performance.PERFORMANCE_PATH
                try:
                    performance.PERFORMANCE_PATH = Path(out_tmp) / "performance.json"
                    performance.generar()
                    self.assertTrue(performance.PERFORMANCE_PATH.exists())
                    contenido = json.loads(performance.PERFORMANCE_PATH.read_text(encoding="utf-8"))
                    self.assertEqual(contenido["items_adjudicados"], 1)
                finally:
                    performance.PERFORMANCE_PATH = orig_perf_path


if __name__ == "__main__":
    unittest.main()
