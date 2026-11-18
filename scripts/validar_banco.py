"""Comprueba el banco oficial congelado sin ejecutar modelos ni PostgreSQL."""

import argparse
import json
from pathlib import Path

from tickets_rag.banco import BANCO_OFICIAL
from tickets_rag.banco_revision import validar_oficial


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--banco", type=Path, default=BANCO_OFICIAL)
    parser.add_argument("--salida", type=Path, help="guardar también el resumen técnico en JSON")
    args = parser.parse_args()
    try:
        resumen = validar_oficial(args.banco)
    except (OSError, ValueError, KeyError, TypeError):
        print("Banco no válido: revise congelación, composición, duplicados, fuentes, roles y páginas.")
        return 1
    if args.salida:
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_text(json.dumps(resumen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(resumen, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
