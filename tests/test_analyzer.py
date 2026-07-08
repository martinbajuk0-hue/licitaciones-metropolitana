import unittest

import analyzer


class TestAnalyzer(unittest.TestCase):
    def test_identifica_producto_por_categoria(self):
        texto = "Se requiere la provisión e instalación de piso vinílico click para oficinas."
        productos = analyzer.identificar_productos(texto)
        categorias = {p.categoria for p in productos}
        self.assertIn("pisos_vinilicos", categorias)

    def test_nunca_descarta_por_terminologia_generica(self):
        texto = "Llamado a licitación para la pavimentación y solado del salón comunal."
        productos = analyzer.identificar_productos(texto)
        self.assertTrue(len(productos) > 0)

    def test_extraccion_de_organismo_ute(self):
        texto = "UTE llama a licitación abreviada 123/2026 para el suministro de piso antideslizante."
        campos = analyzer.extraer_campos_clave(texto)
        self.assertIsNotNone(campos.organismo)

    def test_faltantes_declarados_cuando_no_hay_dato(self):
        texto = "Documento sin ninguna estructura reconocible de pliego."
        campos = analyzer.extraer_campos_clave(texto)
        self.assertTrue(len(campos.faltantes) > 0)

    def test_probabilidad_exito_baja_sin_productos(self):
        campos = analyzer.CamposClave()
        resultado = analyzer.estimar_probabilidad_exito(campos, [], 0, 0, 0)
        self.assertEqual(resultado["score"], 0)

    def test_resumen_extractivo_sin_api_key(self):
        texto = "UTE llama a licitación para piso vinílico."
        campos = analyzer.extraer_campos_clave(texto)
        productos = analyzer.identificar_productos(texto)
        resumen = analyzer.generar_resumen_ejecutivo(texto, campos, productos)
        self.assertIn("Organismo", resumen)


if __name__ == "__main__":
    unittest.main()
