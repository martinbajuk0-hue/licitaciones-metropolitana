import json
import shutil
import tempfile
import unittest
from email import message_from_string
from pathlib import Path
from unittest.mock import patch

import catalogo
import resultados as resultados_mod
import revisar_resultados


def _cuerpo_html(mensaje_raw: str) -> str:
    """Ver la misma función en tests/test_monitor.py: el mensaje MIME
    serializado va en base64 cuando hay acentos, así que hay que
    decodificarlo en vez de buscar directamente en el string crudo."""
    mensaje = message_from_string(mensaje_raw)
    parte_html = next(p for p in mensaje.walk() if p.get_content_type() == "text/html")
    return parte_html.get_payload(decode=True).decode("utf-8")


class TestRevisarPendientes(unittest.TestCase):
    """Igual que test_catalogo.py: redirige catalogo.CATALOGO_* a un
    directorio temporal en vez de tocar docs/ real."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())
        self._orig_dir = catalogo.CATALOGO_DIR
        self._orig_path = catalogo.CATALOGO_PATH
        catalogo.CATALOGO_DIR = self._tmp / "data"
        catalogo.CATALOGO_PATH = catalogo.CATALOGO_DIR / "llamados.json"

    def tearDown(self):
        catalogo.CATALOGO_DIR = self._orig_dir
        catalogo.CATALOGO_PATH = self._orig_path
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _sembrar_catalogo(self, entradas: dict) -> None:
        catalogo.CATALOGO_DIR.mkdir(parents=True, exist_ok=True)
        with open(catalogo.CATALOGO_PATH, "w", encoding="utf-8") as f:
            json.dump(entradas, f)

    def _resultado(self, estado: str, ganamos: bool | None = None) -> resultados_mod.ResultadoAdjudicacion:
        r = resultados_mod.ResultadoAdjudicacion()
        if estado == "ganamos":
            r.resolucion = "Adjudicada totalmente"
            r.oferentes = [(resultados_mod.RUT_METROPOLITANA, "METROPOLITANA S A")]
            r.ganadores_por_item = [(resultados_mod.RUT_METROPOLITANA, "METROPOLITANA S A")]
        elif estado == "perdimos":
            r.resolucion = "Adjudicada totalmente"
            r.oferentes = [(resultados_mod.RUT_METROPOLITANA, "METROPOLITANA S A"), ("999", "OTRO")]
            r.ganadores_por_item = [("999", "OTRO")]
        elif estado == "no_presentamos":
            r.resolucion = "Adjudicada totalmente"
            r.oferentes = [("999", "OTRO")]
            r.ganadores_por_item = [("999", "OTRO")]
        elif estado == "pendiente":
            pass
        return r

    def test_solo_revisa_llamados_sin_resultado_conocido(self):
        self._sembrar_catalogo({
            "id-1": {"id": "id-1", "url_ficha": "https://x/consultas/detalle/id/1"},
            "id-2": {
                "id": "id-2",
                "url_ficha": "https://x/consultas/detalle/id/2",
                "resultado": {"estado": "ganamos"},
            },
        })
        with patch("revisar_resultados.resultados_mod.obtener_resultado") as mock_obtener:
            mock_obtener.return_value = self._resultado("perdimos")
            transiciones, revisados = revisar_resultados.revisar_pendientes()

        # id-2 ya tenía resultado -> no se vuelve a consultar.
        mock_obtener.assert_called_once_with("https://x/consultas/detalle/id/1")
        self.assertEqual(revisados, 1)
        self.assertEqual(len(transiciones), 1)
        self.assertEqual(transiciones[0]["id"], "id-1")

    def test_llamado_sin_url_ficha_se_ignora(self):
        self._sembrar_catalogo({"id-1": {"id": "id-1"}})
        with patch("revisar_resultados.resultados_mod.obtener_resultado") as mock_obtener:
            transiciones, revisados = revisar_resultados.revisar_pendientes()
        mock_obtener.assert_not_called()
        self.assertEqual(revisados, 0)
        self.assertEqual(transiciones, [])

    def test_resultado_pendiente_no_cuenta_como_transicion(self):
        self._sembrar_catalogo({
            "id-1": {"id": "id-1", "url_ficha": "https://x/consultas/detalle/id/1"},
        })
        with patch("revisar_resultados.resultados_mod.obtener_resultado") as mock_obtener:
            mock_obtener.return_value = self._resultado("pendiente")
            transiciones, revisados = revisar_resultados.revisar_pendientes()
        self.assertEqual(revisados, 1)
        self.assertEqual(transiciones, [])
        # Igual queda guardado en el catálogo, con estado "pendiente".
        data = json.loads(catalogo.CATALOGO_PATH.read_text(encoding="utf-8"))
        self.assertEqual(data["id-1"]["resultado"]["estado"], "pendiente")

    def test_error_de_red_no_actualiza_ni_rompe(self):
        self._sembrar_catalogo({
            "id-1": {"id": "id-1", "url_ficha": "https://x/consultas/detalle/id/1"},
        })
        with patch("revisar_resultados.resultados_mod.obtener_resultado") as mock_obtener:
            mock_obtener.return_value = None
            transiciones, revisados = revisar_resultados.revisar_pendientes()
        self.assertEqual(revisados, 1)
        self.assertEqual(transiciones, [])
        data = json.loads(catalogo.CATALOGO_PATH.read_text(encoding="utf-8"))
        self.assertNotIn("resultado", data["id-1"])  # se reintenta en la próxima corrida

    def test_ganamos_y_perdimos_y_no_presentamos_se_clasifican_bien(self):
        self._sembrar_catalogo({
            "id-1": {"id": "id-1", "url_ficha": "https://x/consultas/detalle/id/1"},
            "id-2": {"id": "id-2", "url_ficha": "https://x/consultas/detalle/id/2"},
            "id-3": {"id": "id-3", "url_ficha": "https://x/consultas/detalle/id/3"},
        })
        resultados_por_id = {
            "https://x/consultas/detalle/id/1": self._resultado("ganamos"),
            "https://x/consultas/detalle/id/2": self._resultado("perdimos"),
            "https://x/consultas/detalle/id/3": self._resultado("no_presentamos"),
        }
        with patch("revisar_resultados.resultados_mod.obtener_resultado") as mock_obtener:
            mock_obtener.side_effect = lambda url: resultados_por_id[url]
            transiciones, _ = revisar_resultados.revisar_pendientes()

        estados = {t["id"]: t["resultado"]["estado"] for t in transiciones}
        self.assertEqual(estados, {"id-1": "ganamos", "id-2": "perdimos", "id-3": "no_presentamos"})


class TestEnviarEmailResultados(unittest.TestCase):
    def _entrada(self, estado: str) -> dict:
        return {
            "id": "x",
            "titulo": "Licitación de prueba",
            "organismo": "Organismo X",
            "url_ficha": "https://example.com/ficha",
            "resultado": {
                "estado": estado,
                "resolucion": "Adjudicada totalmente",
                "resolucion_nro": "1/2026",
                "fecha_resolucion": "01/01/2026",
                "monto_total": "$ 1.000,00",
            },
        }

    @patch("revisar_resultados.settings.gmail_user", return_value=None)
    def test_sin_credenciales_no_intenta_enviar(self, _mock):
        with patch("revisar_resultados.smtplib.SMTP_SSL") as mock_smtp:
            revisar_resultados.enviar_email_resultados([self._entrada("ganamos")])
            mock_smtp.assert_not_called()

    def test_solo_no_presentamos_no_manda_email(self):
        with patch("revisar_resultados.smtplib.SMTP_SSL") as mock_smtp:
            revisar_resultados.enviar_email_resultados([self._entrada("no_presentamos")])
            mock_smtp.assert_not_called()

    @patch("revisar_resultados.settings.email_destino", return_value="dest@example.com")
    @patch("revisar_resultados.settings.gmail_app_password", return_value="app-pass")
    @patch("revisar_resultados.settings.gmail_user", return_value="user@gmail.com")
    def test_ganamos_o_perdimos_si_manda_email(self, _u, _p, _d):
        with patch("revisar_resultados.smtplib.SMTP_SSL") as mock_smtp:
            server = mock_smtp.return_value.__enter__.return_value
            revisar_resultados.enviar_email_resultados([self._entrada("ganamos"), self._entrada("perdimos")])
            server.login.assert_called_once()
            server.sendmail.assert_called_once()

    @patch("revisar_resultados.settings.email_destino", return_value="dest@example.com")
    @patch("revisar_resultados.settings.gmail_app_password", return_value="app-pass")
    @patch("revisar_resultados.settings.gmail_user", return_value="user@gmail.com")
    def test_que_es_reusado_del_catalogo_aparece_en_el_email(self, _u, _p, _d):
        # Pedido del usuario 2026-08-24: el resumen corto también debe
        # aparecer en el email de resultados (ganamos/perdimos), reusando
        # el campo guardado en el catálogo por catalogo.registrar_llamado()
        # — acá no se vuelve a leer el pliego.
        entrada = self._entrada("ganamos")
        entrada["que_es"] = "Suministro e instalación de piso vinílico para ASSE."
        with patch("revisar_resultados.smtplib.SMTP_SSL") as mock_smtp:
            server = mock_smtp.return_value.__enter__.return_value
            revisar_resultados.enviar_email_resultados([entrada])
            cuerpo = _cuerpo_html(server.sendmail.call_args[0][2])
        self.assertIn("Suministro e instalación de piso vinílico para ASSE.", cuerpo)

    @patch("revisar_resultados.settings.email_destino", return_value="dest@example.com")
    @patch("revisar_resultados.settings.gmail_app_password", return_value="app-pass")
    @patch("revisar_resultados.settings.gmail_user", return_value="user@gmail.com")
    def test_sin_que_es_no_rompe_el_email(self, _u, _p, _d):
        entrada = self._entrada("ganamos")
        self.assertNotIn("que_es", entrada)
        with patch("revisar_resultados.smtplib.SMTP_SSL") as mock_smtp:
            server = mock_smtp.return_value.__enter__.return_value
            revisar_resultados.enviar_email_resultados([entrada])
            server.sendmail.assert_called_once()


if __name__ == "__main__":
    unittest.main()
