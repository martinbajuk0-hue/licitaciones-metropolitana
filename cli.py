"""CLI para analizar UNA licitación puntual con el pipeline completo
(parser + analyzer + risk + checklist + report), sin esperar al cron
diario de monitor.py. Útil cuando alguien del equipo encuentra a mano una
licitación y quiere el análisis completo ya.

Uso:
    python cli.py analizar --url "https://www.comprasestatales.gub.uy/..." --titulo "Suministro de pisos ..."
    python cli.py analizar --archivo ./pliego.pdf --titulo "Suministro de pisos ..."
    python cli.py cotizar --items piso_spc:120 zocalo:40
"""
from __future__ import annotations

import argparse
from pathlib import Path

import parser as parser_mod
import pricing
import report as report_mod


def cmd_analizar(args: argparse.Namespace) -> None:
    documentos_con_error: list[str] = []

    if args.url:
        pliego = parser_mod.extraer_pliego(args.url, max_documentos=args.max_documentos)
        texto = pliego.texto_completo
        documentos_con_error = [d.nombre for d in pliego.documentos_con_error]
        url = args.url
    elif args.archivo:
        path = Path(args.archivo)
        doc = parser_mod.extraer_archivo_local(path)
        texto = doc.texto
        if doc.error:
            documentos_con_error = [doc.nombre]
        url = str(path)
    else:
        raise SystemExit("Especificá --url o --archivo")

    if not texto.strip():
        print("⚠️  No se pudo extraer texto del pliego. Revisá el archivo/URL o instalá las dependencias de parser.py.")

    informe = report_mod.generar_informe_markdown(args.titulo, url, texto, documentos_con_error)
    ruta = report_mod.guardar_informe(args.titulo, informe)
    print(f"Informe generado en: {ruta}")
    if args.stdout:
        print("\n" + informe)


def cmd_cotizar(args: argparse.Namespace) -> None:
    items = []
    for item in args.items:
        producto_id, cantidad = item.split(":")
        items.append((producto_id, float(cantidad)))
    resultado = pricing.cotizar(items, margen_porcentaje=args.margen)
    import json

    print(json.dumps(resultado, ensure_ascii=False, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="comando", required=True)

    ap_analizar = sub.add_parser("analizar", help="Corre el pipeline completo sobre una licitación puntual")
    ap_analizar.add_argument("--url", help="URL de la licitación en comprasestatales.gub.uy")
    ap_analizar.add_argument("--archivo", help="Ruta a un pliego local (PDF/Word/Excel/imagen)")
    ap_analizar.add_argument("--titulo", required=True, help="Título de la licitación (para el nombre del informe)")
    ap_analizar.add_argument("--max-documentos", type=int, default=10, dest="max_documentos")
    ap_analizar.add_argument("--stdout", action="store_true", help="Además de guardar, imprimir el informe completo")
    ap_analizar.set_defaults(func=cmd_analizar)

    ap_cotizar = sub.add_parser("cotizar", help="Arma una cotización a partir de knowledge/precios.yaml")
    ap_cotizar.add_argument("--items", nargs="+", required=True, help="Lista producto_id:cantidad, ej: piso_spc:120")
    ap_cotizar.add_argument("--margen", type=float, default=0.0, help="Margen comercial %% a aplicar")
    ap_cotizar.set_defaults(func=cmd_cotizar)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
