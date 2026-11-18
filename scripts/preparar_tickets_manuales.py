"""Valida y congela veinte tickets humanos independientes, sin clasificar ni llamar modelos."""

import argparse
import json
from pathlib import Path

from tickets_rag.tickets_manuales import CARPETA, MANUALES, ErrorTicketsManuales, preparar_manuales


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", type=Path, default=CARPETA / "plantilla.csv")
    p.add_argument("--autoria", type=Path, default=CARPETA / "autoria.pendiente.json")
    p.add_argument("--salida", type=Path, default=MANUALES.parent)
    p.add_argument("--solo-validar", action="store_true", help="comprueba sin crear el conjunto congelado")
    args = p.parse_args()
    try:
        resumen = preparar_manuales(args.csv, args.autoria, salida=None if args.solo_validar else args.salida)
    except ErrorTicketsManuales as error:
        print(str(error))  # Solo números de fila y causas fijas, nunca el texto o el autor.
        return 2
    print(json.dumps(resumen, ensure_ascii=False))
    if not args.solo_validar:
        print(f"Conjunto reservado: {args.salida / 'tickets.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
