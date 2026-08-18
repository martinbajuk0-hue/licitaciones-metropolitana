import unittest

import monitor


class TestMonitorFechaRango(unittest.TestCase):
    """monitor._fecha_lic_a_iso() es la pieza nueva y testeable sin red:
    normaliza lic['fecha'] (que puede venir en ISO del feed OCDS, o en
    RFC822 crudo si se cayó al fallback RSS — ver obtener_licitaciones())
    a 'YYYY-MM-DD' para poder compararla contra el rango de
    --test-rango-fechas.
    """

    def test_fecha_iso_se_devuelve_truncada_a_10_caracteres(self):
        self.assertEqual(monitor._fecha_lic_a_iso("2026-08-13"), "2026-08-13")
        self.assertEqual(monitor._fecha_lic_a_iso("2026-08-13T14:30:00Z"), "2026-08-13")

    def test_fecha_rfc822_se_normaliza_a_iso(self):
        self.assertEqual(monitor._fecha_lic_a_iso("Wed, 13 Aug 2026 10:00:00 GMT"), "2026-08-13")

    def test_fecha_vacia_devuelve_none(self):
        self.assertIsNone(monitor._fecha_lic_a_iso(""))

    def test_fecha_no_parseable_devuelve_none(self):
        self.assertIsNone(monitor._fecha_lic_a_iso("no es una fecha"))


class TestAlquilerDeInmueble(unittest.TestCase):
    """Caso real reportado por el usuario 2026-08-17: Concurso de Precios
    12/2026, "Contratación de local apto para el dictado de clases
    curriculares de Educación Física para los alumnos del liceo N°60 de
    Montevideo". La auditoría en vivo (run #190) mostró que matcheó por
    'arcos de fútbol', encontrado en un formulario tipo checklist donde
    el organismo le pregunta a cada local candidato qué equipamiento YA
    TIENE instalado:

        "10 (diez) pelotas de fútbol Sí …. No ...... Arcos de fútbol
        Sí …. No..... Red de voleibol Sí..."
        "Piso: Madera: .......... Baldosa: ............ Hormigón: ..."

    Es decir: el organismo busca ALQUILAR un local ya construido, no
    comprar productos — el pliego menciona madera/baldosa/arcos de
    fútbol únicamente para preguntar qué tiene el local candidato, no
    para pedir que se los provean. Metropolitana no alquila inmuebles,
    así que este tipo de compra nunca es una oportunidad real sin
    importar qué término del rubro aparezca casualmente.
    """

    def test_es_alquiler_de_inmueble_detecta_el_titulo_real(self):
        titulo = (
            'concurso de precios n° 12/2026 "contratación de local apto para el '
            "dictado de clases curriculares de educación física para los alumnos "
            'del liceo n°60 de montevideo"'
        )
        self.assertTrue(monitor._es_alquiler_de_inmueble(titulo))

    def test_es_alquiler_de_inmueble_no_dispara_con_texto_normal_del_rubro(self):
        texto = "suministro e instalación de piso vinílico y zócalos en el local comercial de la intendencia"
        self.assertFalse(monitor._es_alquiler_de_inmueble(texto))

    def test_arcos_de_futbol_en_checklist_de_local_alquilado_no_marca_relevante(self):
        lic = {
            "titulo": (
                'Concurso de Precios N° 12/2026 "Contratación de local apto para el '
                "dictado de clases curriculares de Educación Física para los alumnos "
                'del liceo N°60 de Montevideo"'
            ),
            "descripcion": "Contratación de local apto para el dictado de clases curriculares de Educación Física.",
            "documentos": [],
            "url": "https://www.comprasestatales.gub.uy/ocds/release/test-concurso-12-2026",
        }
        relevante, kw, fuente, texto = monitor.es_relevante(lic)
        self.assertFalse(relevante, f"No debería ser relevante (alquiler de local), pero marcó: {kw!r} (fuente: {fuente})")

    def test_alquiler_de_inmueble_no_se_detecta_solo_por_la_palabra_local(self):
        # Guarda contra un filtro demasiado amplio: la palabra "local" sola
        # (ej. "gobierno local", "sucursal local") no debe activar el filtro,
        # solo la frase completa "contratación/alquiler/arrendamiento de local(es)".
        texto = "el proveedor deberá tener representación local en montevideo para el soporte técnico"
        self.assertFalse(monitor._es_alquiler_de_inmueble(texto))


if __name__ == "__main__":
    unittest.main()
