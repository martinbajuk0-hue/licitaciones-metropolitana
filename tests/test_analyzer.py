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

    def test_fecha_apertura_no_confunde_mencion_anterior_sin_fecha(self):
        # "a la fecha de apertura" aparece antes, sin fecha cerca; la fecha
        # real está en una mención posterior de "Fecha de apertura:".
        texto = (
            "Se requiere certificado unico de BPS vigente a la fecha de apertura.\n"
            "Fecha de apertura: 15 de agosto de 2026.\n"
        )
        campos = analyzer.extraer_campos_clave(texto)
        self.assertEqual(campos.fecha_apertura, "2026-08-15")

    def test_fecha_con_mes_en_mayuscula_no_rompe_el_parseo(self):
        # Bug real en producción (2026-07-13, run #71 de monitor.yml):
        # "13 de Julio de 2026" (mes con mayúscula inicial, común al
        # empezar una oración/título) hacía que _normalizar_fecha buscara
        # "Julio" en _MESES (claves en minúscula), no lo encontrara, y
        # cayera al branch numérico -> int("Julio") -> ValueError, tumbando
        # todo monitor.py a mitad de corrida.
        texto = "La fecha de apertura de ofertas será el día 13 de Julio de 2026 a las 10 horas."
        campos = analyzer.extraer_campos_clave(texto)
        self.assertEqual(campos.fecha_apertura, "2026-07-13")

    def test_plazo_entrega_relativo_no_toma_fecha_de_otro_campo(self):
        texto = (
            "Plazo de entrega: 30 dias corridos desde la notificacion de la orden de compra.\n"
            "Consultas hasta 20 de julio de 2026.\n"
        )
        campos = analyzer.extraer_campos_clave(texto)
        self.assertIsNotNone(campos.fecha_entrega)
        self.assertIn("30 dias", campos.fecha_entrega)
        self.assertNotIn("2026-07-20", campos.fecha_entrega)

    def test_garantia_fiel_cumplimiento_con_texto_intermedio(self):
        texto = "Garantía de fiel cumplimiento de contrato: 5% del monto adjudicado."
        campos = analyzer.extraer_campos_clave(texto)
        self.assertEqual(campos.garantia_fiel_cumplimiento, "5%")

    def test_criterios_evaluacion_no_mezcla_parrafo_siguiente(self):
        texto = (
            "Criterios de evaluación:\n"
            "1. Precio: 40 puntos.\n"
            "2. Antecedentes: 25 puntos.\n"
            "\n"
            "Se debera presentar muestra fisica de los materiales ofertados."
        )
        campos = analyzer.extraer_campos_clave(texto)
        self.assertEqual(len(campos.criterios_evaluacion), 2)
        self.assertTrue(all("muestra" not in c.lower() for c in campos.criterios_evaluacion))

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
