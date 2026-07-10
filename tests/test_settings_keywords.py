import unittest

import config.settings as settings
import analyzer
import monitor


class TestKeywordsAmpliado(unittest.TestCase):
    def test_todas_las_palabras_clave_no_incluye_grupos_de_contexto(self):
        fuertes = {k.lower() for k in settings.todas_las_palabras_clave()}
        contexto = settings.palabras_clave_contexto()
        # "escuela" y "interior" son términos típicos de lugares_uso/aplicaciones:
        # no deben aparecer como señal fuerte (romperían el filtro).
        self.assertIn("escuela", [t.lower() for t in contexto["lugares_uso"]])
        self.assertNotIn("escuela", fuertes)
        self.assertIn("interior", [t.lower() for t in contexto["aplicaciones"]])
        self.assertNotIn("interior", fuertes)

    def test_categoria_fuerte_si_esta_en_todas_las_palabras_clave(self):
        fuertes = {k.lower() for k in settings.todas_las_palabras_clave()}
        self.assertIn("piso vinílico", fuertes)
        self.assertIn("césped sintético", fuertes)

    def test_lugar_de_uso_solo_no_marca_relevante(self):
        lic = {
            "titulo": "Compra Directa 1/2026",
            "descripcion": "Compra de sillas para la escuela y el hospital de la intendencia.",
            "url": "",
            "documentos": [],
        }
        relevante, kw, fuente, _ = monitor.es_relevante(lic)
        # No hay ningún término de producto Metropolitana en título/descripción,
        # solo lugares_uso — no debe considerarse relevante en esta etapa
        # (y como no hay documentos, tampoco puede leer el pliego).
        self.assertFalse(relevante)

    def test_producto_real_si_marca_relevante_por_titulo(self):
        lic = {
            "titulo": "Compra de piso vinílico para escuela",
            "descripcion": "",
            "url": "",
            "documentos": [],
        }
        relevante, kw, fuente, _ = monitor.es_relevante(lic)
        self.assertTrue(relevante)
        self.assertEqual(fuente, "título/descripción")

    def test_coincide_palabra_clave_respeta_limite_de_palabra_en_termino_corto(self):
        # "pu" (poliuretano) no debe matchear dentro de "publico"
        self.assertFalse(settings.coincide_palabra_clave("edificio publico", "pu"))
        self.assertTrue(settings.coincide_palabra_clave("piso de pu brillante", "pu"))

    def test_coincide_palabra_clave_termino_largo_sigue_usando_substring(self):
        self.assertTrue(settings.coincide_palabra_clave("se solicita piso vinílico símil madera", "piso vinílico"))

    def test_identificar_contexto_no_es_relevancia(self):
        # identificar_contexto por sí solo no decide nada — solo reporta.
        texto = "Licitación para compra de mobiliario para escuela y oficina, uso interior."
        contexto = analyzer.identificar_contexto(texto)
        self.assertIn("lugares_uso", contexto)
        productos = analyzer.identificar_productos(texto)
        self.assertEqual(productos, [])  # sin términos de producto real

    def test_palabras_clave_por_categoria_incluye_grupos_nuevos(self):
        categorias = settings.palabras_clave_por_categoria()
        for grupo in ["materiales", "marcas", "abreviaturas", "errores_comunes", "normativas"]:
            self.assertIn(grupo, categorias)
        self.assertNotIn("lugares_uso", categorias)
        self.assertNotIn("aplicaciones", categorias)

    def test_no_falsos_positivos_en_licitaciones_no_relacionadas(self):
        # Guarda de regresión: ya cazó 2 bugs reales (vocabulario
        # administrativo genérico y siglas de organismos metidos por error
        # en listas de señal fuerte). Cualquier término nuevo que se agregue
        # a knowledge/keywords.yaml debe seguir pasando este chequeo.
        textos_no_relacionados = [
            "Compra Directa 45/2026: Adquisición de computadoras portátiles para la Intendencia de Montevideo.",
            "Licitación Abreviada 12/2026: Provisión de insumos médicos y medicamentos para el Hospital Pasteur.",
            "Concurso de Precios 8/2026: Contratación de servicio de catering para eventos institucionales del Ministerio.",
            "Compra de neumáticos y repuestos para la flota de vehículos de UTE.",
            "Adquisición de resmas de papel, tóner y artículos de librería para oficinas de ANEP.",
            "Contratación de servicio de seguridad y vigilancia para edificios de la Intendencia de Canelones.",
            "Provisión de uniformes y equipamiento de protección personal para Bomberos.",
            "Compra de software de gestión administrativa para el Ministerio de Economía y Finanzas.",
            "Servicio de mantenimiento de ascensores en edificios públicos de OSE.",
            "Adquisición de vacunas y material descartable para el Ministerio de Salud Pública.",
            "Compra directa de combustible para flota vehicular de la Intendencia de Salto.",
            "Contratación de servicio de limpieza para oficinas del BPS.",
            "Provisión de mobiliario de oficina (escritorios y sillas) para ASSE.",
            "Adquisición de equipos de aire acondicionado para el Poder Judicial.",
            "Servicio de fumigación y control de plagas para dependencias municipales.",
        ]
        fuertes = settings.todas_las_palabras_clave()
        for texto in textos_no_relacionados:
            texto_lower = texto.lower()
            matches = [kw for kw in fuertes if settings.coincide_palabra_clave(texto_lower, kw)]
            self.assertEqual(matches, [], f"Falso positivo en: {texto!r}")

    def test_no_falsos_positivos_por_bureaucracia_generica_de_pliego(self):
        # Guarda de regresión: auditoría real contra ARCE del 2026-07-10
        # (monitor.py --auditoria, run #66) encontró que "tocaf",
        # "certificado de origen", "iso 9001", "unit", "especificaciones
        # técnicas", "pliego de condiciones particulares", "planilla de
        # rubrado", "suministro de materiales" y la familia genérica de
        # "acondicionamiento de <espacio>" están en CUALQUIER pliego público
        # uruguayo sin importar el rubro — no aportan señal de producto y se
        # removieron de las listas de señal fuerte. Estos fragmentos son
        # textuales de pliegos reales que dispararon esos falsos positivos.
        fragmentos_reales = [
            "Artículo 46 del TOCAF, excluyente. Toda Declaración Jurada a presentarse",
            "Quien resulte adjudicatario, deberá presentar el Certificado de Origen respectivo",
            "Certificación ISO 9001:2015 Sistema de Gestión de Calidad",
            "determinadas mediante ensayo de tamizado según normas UNIT vigentes",
            "En caso de que se requieran especificaciones técnicas y/o habilitaciones",
            "las disposiciones del Pliego de Condiciones Particulares del llamado",
            "A los efectos de la cotización deberán llenar la planilla de rubrado",
            "el suministro de materiales y toda la mano de obra necesaria",
            "Acondicionamiento térmico acorde a los materiales, herramientas y productos",
        ]
        fuertes = settings.todas_las_palabras_clave()
        for texto in fragmentos_reales:
            texto_lower = texto.lower()
            matches = [kw for kw in fuertes if settings.coincide_palabra_clave(texto_lower, kw)]
            self.assertEqual(matches, [], f"Falso positivo (bureaucracia genérica) en: {texto!r} -> {matches}")

    def test_terminaciones_no_matchea_dentro_de_determinaciones(self):
        # "terminaciones" (removida de terminologia_pliegos) era substring de
        # "determinaciones" (cantidad de análisis de laboratorio en pliegos
        # médicos) — evidencia real: Compra Directa 1223/2026 (kit x 10
        # DETERMINACIONES). Ya no está en las listas fuertes; este test
        # bloquea que alguien la reagregue sin notar la colisión.
        fuertes = {k.lower() for k in settings.todas_las_palabras_clave()}
        self.assertNotIn("terminaciones", fuertes)

    def test_abreviatura_pe_removida_por_colision_con_rango_militar(self):
        # "pe" (ex materiales/abreviaturas) matcheaba dentro de "(PE)" —
        # evidencia real: Concurso de Precios 78/2026, "Sub. Of.Mayor
        # (PE)(CP)" (rango, no polietileno). El límite de palabra de
        # coincide_palabra_clave no protege acá porque "(" y ")" no son
        # caracteres alfanuméricos, así que el lookaround igual matchea —
        # demasiado corta/ambigua para señal fuerte. Se removió del YAML;
        # este test prueba la colisión real y bloquea que se reagregue.
        self.assertTrue(settings.coincide_palabra_clave("sub. of.mayor (pe)(cp)", "pe"))
        fuertes = {k.lower() for k in settings.todas_las_palabras_clave()}
        self.assertNotIn("pe", fuertes)

    def test_detecta_licitaciones_realmente_relacionadas(self):
        textos_relacionados = [
            "Licitación Abreviada: Provisión e instalación de piso vinílico para el Liceo N°5.",
            "Compra Directa: Adquisición de césped sintético para cancha de fútbol 7 del club deportivo.",
            "Concurso de Precios: Recambio de moquette en salas del Palacio Legislativo.",
            "Provisión de zócalos y perfiles de aluminio para obra de remodelación.",
            "Contratación de servicio de instalación de deck WPC en área de piscina.",
            "Compra de piedrafina para revestimiento de fachada del edificio municipal.",
        ]
        fuertes = settings.todas_las_palabras_clave()
        for texto in textos_relacionados:
            texto_lower = texto.lower()
            matches = [kw for kw in fuertes if settings.coincide_palabra_clave(texto_lower, kw)]
            self.assertTrue(matches, f"No se detectó ningún término en: {texto!r}")

    def test_total_de_keywords_supera_las_3000(self):
        kw = settings.keywords()
        total = sum(len(c["keywords"]) for c in kw["categorias"].values())
        for grupo in ["terminologia_pliegos", "materiales", "aplicaciones", "lugares_uso", "normativas", "marcas", "errores_comunes", "abreviaturas"]:
            total += len(kw[grupo])
        self.assertGreater(total, 3000)


if __name__ == "__main__":
    unittest.main()
