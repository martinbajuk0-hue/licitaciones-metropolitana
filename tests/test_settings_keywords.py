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

    def test_una_sola_palabra_generica_en_titulo_no_alcanza(self):
        # Caso real de la auditoría 2026-07-10: "aluminio" solo, en un
        # contexto ajeno (esponja de limpieza), no debe marcar relevante.
        lic = {
            "titulo": "Compra de esponjas de aluminio para limpieza de oficinas",
            "descripcion": "",
            "url": "",
            "documentos": [],
        }
        relevante, kw, fuente, _ = monitor.es_relevante(lic)
        self.assertFalse(relevante)

    def test_dos_palabras_genericas_distintas_si_marcan_relevante(self):
        # Caso real: "pvc" + "mdf" + "zócalo" juntos sí fueron pisos reales
        # (Compra Directa 75426/2026 y similares). Acá con dos alcanza.
        lic = {
            "titulo": "Retiro de zócalos y postigones de pvc en edificio municipal",
            "descripcion": "",
            "url": "",
            "documentos": [],
        }
        relevante, kw, fuente, _ = monitor.es_relevante(lic)
        self.assertTrue(relevante)

    def test_termino_multipalabra_alcanza_solo_bajo_la_nueva_regla(self):
        lic = {
            "titulo": "Provisión e instalación de piso vinílico para el liceo",
            "descripcion": "",
            "url": "",
            "documentos": [],
        }
        relevante, kw, fuente, _ = monitor.es_relevante(lic)
        self.assertTrue(relevante)

    def test_decidir_relevancia_una_palabra_sola_no_alcanza(self):
        self.assertEqual(monitor._decidir_relevancia(["aluminio"]), (False, None))

    def test_decidir_relevancia_dos_palabras_distintas_alcanzan(self):
        relevante, kw = monitor._decidir_relevancia(["aluminio", "goma"])
        self.assertTrue(relevante)

    def test_decidir_relevancia_multipalabra_sola_alcanza(self):
        relevante, kw = monitor._decidir_relevancia(["piso vinílico"])
        self.assertTrue(relevante)
        self.assertEqual(kw, "piso vinílico")

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

    def test_espeso_no_matchea_dentro_de_espesor(self):
        # "espeso" (removida de errores_comunes) era substring de
        # "espesor" (grosor) — palabra genérica de cualquier ficha técnica
        # (muebles, vidrios, chapas), no solo de pisos. Evidencia real:
        # Compra Directa 139/2026, "Espesor de placa. 25 mm." (mesa de
        # oficina, no piso). Mismo patrón que "terminaciones"/"determinaciones".
        fuertes = {k.lower() for k in settings.todas_las_palabras_clave()}
        self.assertNotIn("espeso", fuertes)

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

    def test_abs_y_concreto_sueltos_no_marcan_relevante_compra_de_motos(self):
        # Caso real reportado por el usuario 2026-08-17: "Licitación
        # Abreviada 13/2026" — adquisición de motocicletas 0km para la
        # Intendencia de Rocha — llegó por email marcada relevante con
        # "Coincidencia: abs + concreto". "abs" matcheaba por los frenos
        # ABS de las motos (nada que ver con zócalos/perfiles ABS) y
        # "concreto" por el uso genérico del adjetivo español ("en forma
        # concreta"), no por hormigón/contrapiso. Ambos términos sueltos
        # eran demasiado ambiguos para ser señal fuerte por sí solos — se
        # sacó "abs" de materiales/abreviaturas (quedan las variantes
        # "abs plastico"/"abs plástico", que sí son específicas) y
        # "concreto" se reemplazó por "concreto pulido" (el acabado de
        # piso real, no el adjetivo suelto).
        texto = (
            "adquisición de hasta 15 motocicletas 0 km, 150cc a 200cc, con sistema de frenos abs de serie. "
            "en forma concreta, el oferente deberá detallar las especificaciones técnicas del vehículo."
        )
        fuertes = settings.todas_las_palabras_clave()
        matches = [kw for kw in fuertes if settings.coincide_palabra_clave(texto, kw)]
        self.assertEqual(matches, [], f"No debería matchear ningún término fuerte, matcheó: {matches}")

    def test_contenedores_habitables_garitas_y_banos_modulares_son_relevantes(self):
        # Caso real 2026-08-17: "Compra Directa 6/2026" (adquisición de dos
        # contenedores/módulos habitacionales para AFE Tacuarembó) es un
        # producto real de Metropolitana (ver config/empresa.yaml), pero
        # antes de agregar la categoría contenedores_modulares solo
        # matcheaba de casualidad por "piso vinílico" si el pliego
        # mencionaba el piso interior del módulo — si no lo mencionaba, el
        # llamado pasaba completamente desapercibido.
        textos_relacionados = [
            "Adquisición de dos contenedores habitables con destino a la Estación de AFE en Tacuarembó.",
            "Provisión de módulo habitacional container para obrador de la Intendencia.",
            "Contratación de garita de seguridad prefabricada para el acceso al predio municipal.",
            "Adquisición de baño modular para el balneario municipal.",
        ]
        fuertes = settings.todas_las_palabras_clave()
        for texto in textos_relacionados:
            texto_lower = texto.lower()
            matches = [kw for kw in fuertes if settings.coincide_palabra_clave(texto_lower, kw)]
            self.assertTrue(matches, f"No se detectó ningún término en: {texto!r}")

    def test_categoria_contenedores_modulares_tiene_etiqueta_legible(self):
        self.assertEqual(
            settings.etiqueta_categoria("contenedores_modulares"),
            "Contenedores habitables, garitas y módulos",
        )

    def test_pavimento_y_norma_de_accesibilidad_sueltos_no_marcan_relevante_alcantarilla(self):
        # Caso real reportado por el usuario 2026-08-17: "Licitación
        # Abreviada 44/2026" — construcción de una alcantarilla (obra vial
        # de drenaje, hormigón armado) para la DNV — llegó por email
        # marcada relevante con "Coincidencia: norma de accesibilidad", y
        # con un "Ya adjudicaste antes: REPARACION DE PAVIMENTO,
        # MANTENIMIENTO DE PAVIMENTO" que no tiene nada que ver con la
        # obra (esos adjudicaciones reales de Metropolitana eran de
        # pavimento deportivo/interior, no de vialidad). Dos términos
        # demasiado genéricos causaban esto:
        #   - "norma de accesibilidad"/"norma unit accesibilidad"/"norma
        #     unit": la normativa de accesibilidad y las normas UNIT son
        #     un requisito legal de CUALQUIER obra pública en Uruguay
        #     (rutas, puentes, alcantarillas, edificios), no una señal de
        #     que se necesite un producto de Metropolitana.
        #   - "pavimento"/"pavimentación" solos: es el término genérico
        #     para pavimento VIAL (de ruta/calle) en cualquier pliego de
        #     la DNV o una Intendencia, tanto como para un piso de
        #     edificio. Se reemplazaron por variantes específicas del
        #     rubro real de Metropolitana ("pavimento industrial",
        #     "pavimento deportivo", etc. — ver config/empresa.yaml
        #     "Pisos deportivos, industriales, comerciales, hospitalarios,
        #     educativos"), y se sacaron "cambio de pavimento"/"recambio
        #     de pavimento"/"renovación de pavimento" (repavimentación de
        #     calles, un trabajo real y frecuente de Intendencias que no
        #     es rubro de Metropolitana).
        # Este mismo test, al escribir un fragmento realista de pliego vial
        # para probarlo, encontró un TERCER término igual de genérico que
        # no había sido reportado todavía: "hormigón"/"hormigon" solo
        # (materiales) — el hormigón armado es el material de CUALQUIER
        # obra vial/estructural (rutas, puentes, alcantarillas), no una
        # señal de piso. Mismo arreglo que ya se había hecho con
        # "concreto": se reemplazó por "hormigón pulido"/"hormigon
        # pulido" (el piso de hormigón pulido sí es un producto real del
        # rubro, con el término que efectivamente se usa en Uruguay).
        texto = (
            "los trabajos comprenden la construcción de una alcantarilla en el cruce de la continuación "
            "de ruta 89 sobre la cañada s/n, en el departamento de san josé. la alcantarilla a construir "
            "será de 5 bocas de 1,5 m de luz, de acuerdo a las láminas tipo de la dnv. para el acceso a la "
            "obra se prevé una rampa según la norma de accesibilidad vigente, y se procederá al cambio de "
            "pavimento en la zona afectada una vez finalizados los trabajos de hormigón armado."
        )
        fuertes = settings.todas_las_palabras_clave()
        matches = [kw for kw in fuertes if settings.coincide_palabra_clave(texto, kw)]
        self.assertEqual(matches, [], f"No debería matchear ningún término fuerte, matcheó: {matches}")

    def test_pavimento_especifico_del_rubro_sigue_marcando_relevante(self):
        # Los reemplazos específicos ("pavimento industrial", etc.) no
        # deben perder cobertura real: Metropolitana sí vende pisos
        # deportivos/industriales/comerciales/hospitalarios/educativos
        # (ver config/empresa.yaml).
        textos_relacionados = [
            "Provisión de pavimento deportivo para el polideportivo municipal.",
            "Recambio de pavimento industrial en planta de UTE.",
            "Colocación de pavimento hospitalario en el Hospital Pasteur.",
        ]
        fuertes = settings.todas_las_palabras_clave()
        for texto in textos_relacionados:
            texto_lower = texto.lower()
            matches = [kw for kw in fuertes if settings.coincide_palabra_clave(texto_lower, kw)]
            self.assertTrue(matches, f"No se detectó ningún término en: {texto!r}")


if __name__ == "__main__":
    unittest.main()
