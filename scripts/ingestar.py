"""Corre la ingesta completa y deja los chunks en indices/.

Uso:
    uv run python scripts/ingestar.py                      # verifica hashes e ingesta
    uv run python scripts/ingestar.py --actualizar-hashes  # registra los hashes actuales
"""

from __future__ import annotations

import argparse
import json

from tickets_rag import config
from tickets_rag.ingesta import ingestar, sha256


def actualizar_hashes() -> None:
    datos = json.loads(config.MANIFIESTO.read_text(encoding="utf-8"))
    for doc in datos["documentos"]:
        ruta = config.RAIZ / doc["ruta"]
        doc["sha256"] = sha256(ruta) if ruta.exists() else None
        print(f"{doc['id']}: {doc['sha256'] or 'pendiente'}")
    config.MANIFIESTO.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--actualizar-hashes", action="store_true", help="escribe en el manifiesto los hashes actuales")
    args = parser.parse_args()
    if args.actualizar_hashes:
        actualizar_hashes()
        return
    resumen = ingestar()
    for doc_id, r in resumen.items():
        if "tickets_indexados" in r:
            print(
                f"{doc_id}: {r['tickets_indexados']} tickets, {r['no_vigentes']} no vigentes "
                f"(procedimientos que cambiaron: {', '.join(r['secciones_modificadas'])}), "
                f"máx {r['tokens_max']} tokens, PII {r['pii_enmascarada'] or 'ninguna'}"
            )
            continue
        print(
            f"{doc_id}: {r['paginas']} páginas, {r['secciones']} secciones "
            f"({len(r['secciones_restringidas'])} solo N2), {r['chunks']} chunks, "
            f"máx {r['tokens_max']} tokens, PII {r['pii_enmascarada'] or 'ninguna'}"
        )
    print(f"Chunks en {config.CHUNKS.relative_to(config.RAIZ)}")


if __name__ == "__main__":
    main()
