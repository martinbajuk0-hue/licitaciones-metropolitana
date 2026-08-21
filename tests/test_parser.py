"""Tests de parser.py, con foco en el timeout duro de extracción de
documentos (agregado tras la corrida #206 de monitor.yml: un PDF con una
fuente de codificación problemática colgó pypdf.extract_text() durante
5h59m hasta que GitHub mató el job entero por el límite de 6 horas —
ver TIMEOUT_EXTRACCION_SEGUNDOS en parser.py).
"""
import time
import unittest
from pathlib import Path

import parser as parser_mod


# Funciones de módulo (no closures/lambdas): multiprocessing bajo contexto
# "spawn" necesita poder importarlas por nombre en el subproceso.
def _dormir_para_siempre(segundos):
    time.sleep(segundos)
    return "no deberia llegar aca"


def _rapido(x):
    return x * 2


def _explota(mensaje):
    raise ValueError(mensaje)


class TestEjecutarConTimeoutDuro(unittest.TestCase):
    """El mecanismo genérico (independiente de PDFs/pypdf): confirma que un
    subproceso colgado se mata de verdad dentro del timeout, y que el caso
    normal (sin cuelgue) sigue devolviendo el resultado real.
    """

    def test_mata_proceso_colgado_dentro_del_timeout(self):
        t0 = time.time()
        resultado, se_agoto = parser_mod.ejecutar_con_timeout_duro(
            _dormir_para_siempre, (9999,), timeout_segundos=2,
            timeout_exitcode_a=lambda exitcode: f"TIMEOUT(exitcode={exitcode})",
        )
        elapsed = time.time() - t0

        self.assertTrue(se_agoto)
        self.assertEqual(resultado, "TIMEOUT(exitcode=None)")
        # Con margen generoso para no ser flaky en un runner cargado, pero
        # acotado: si esto no mata el proceso, tardaría >9999s, no unos pocos.
        self.assertLess(elapsed, 15)

    def test_caso_normal_sin_cuelgue_devuelve_resultado_real(self):
        resultado, se_agoto = parser_mod.ejecutar_con_timeout_duro(
            _rapido, (21,), timeout_segundos=10,
            timeout_exitcode_a=lambda exitcode: "no deberia dispararse",
        )
        self.assertFalse(se_agoto)
        self.assertEqual(resultado, 42)

    def test_excepcion_en_el_subproceso_no_cuelga_al_padre(self):
        # func() que levanta una excepción en vez de colgarse: el
        # subproceso termina (con traceback en stderr) pero sin poner
        # nada en la queue — el padre debe reportarlo como "sin
        # resultado", no quedarse esperando.
        resultado, se_agoto = parser_mod.ejecutar_con_timeout_duro(
            _explota, ("boom",), timeout_segundos=10,
            timeout_exitcode_a=lambda exitcode: f"SIN_RESULTADO(exitcode={exitcode})",
        )
        self.assertFalse(se_agoto)
        self.assertTrue(str(resultado).startswith("SIN_RESULTADO"))


class TestExtraerArchivoLocalConTimeout(unittest.TestCase):
    """Integración con extraer_archivo_local(): confirma que el documento
    extraído real (dataclass DocumentoExtraido) viaja bien a través del
    subproceso (pickling incluido), y que un timeout se traduce en un
    DocumentoExtraido con error en vez de colgar todo el pipeline.
    """

    def test_pdf_valido_se_extrae_normalmente(self):
        from pypdf import PdfWriter

        pdf_path = Path(self._tmp_pdf())
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with open(pdf_path, "wb") as f:
            writer.write(f)

        doc = parser_mod.extraer_archivo_local_con_timeout(
            pdf_path, nombre="pliego.pdf", url="https://x/pliego.pdf", timeout_segundos=30,
        )

        self.assertIsNone(doc.error)
        self.assertEqual(doc.nombre, "pliego.pdf")
        self.assertEqual(doc.tipo, ".pdf")
        self.assertEqual(doc.paginas_leidas, 1)

    def test_extension_no_soportada_devuelve_error_sin_colgar(self):
        path = Path(self._tmp_pdf(suffix=".zip"))
        path.write_bytes(b"contenido irrelevante")

        doc = parser_mod.extraer_archivo_local_con_timeout(
            path, nombre="anexo.zip", url="https://x/anexo.zip", timeout_segundos=10,
        )

        self.assertIsNotNone(doc.error)
        self.assertIn("no soportada", doc.error)

    def test_timeout_devuelve_documento_con_error_explicativo(self):
        # No podemos fabricar un PDF que realmente cuelgue pypdf de forma
        # determinística en un test — en cambio, forzamos un timeout
        # absurdamente corto (0s) contra un PDF real y válido, que alcanza
        # para que el subproceso no llegue a terminar antes de que el
        # padre lo mate. Lo que importa es el CONTRATO: se devuelve un
        # DocumentoExtraido con error, no una excepción ni un cuelgue.
        from pypdf import PdfWriter

        pdf_path = Path(self._tmp_pdf())
        writer = PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=200, height=200)
        with open(pdf_path, "wb") as f:
            writer.write(f)

        doc = parser_mod.extraer_archivo_local_con_timeout(
            pdf_path, nombre="pliego.pdf", url="https://x/pliego.pdf", timeout_segundos=0,
        )

        self.assertIsNotNone(doc.error)
        self.assertIn("timeout", doc.error.lower())
        self.assertEqual(doc.nombre, "pliego.pdf")

    _tmp_files: list[str] = []

    def _tmp_pdf(self, suffix=".pdf"):
        import tempfile

        fd, path = tempfile.mkstemp(suffix=suffix)
        import os

        os.close(fd)
        self._tmp_files.append(path)
        self.addCleanup(lambda: Path(path).unlink(missing_ok=True))
        return path


if __name__ == "__main__":
    unittest.main()
