"""Atiende un ticket con el sistema completo. Sirve para la demostración en vivo.

Uso:
    docker compose up -d
    uv run python scripts/atender_ticket.py "Outlook se queda en Procesando" --rol N1
    uv run python scripts/atender_ticket.py "Perdí el teléfono, necesito que restablezcan mi MFA" --aprobar
    uv run python scripts/atender_ticket.py "..." --rechazar

Si el sistema pide aprobar una acción y no se pasa --aprobar ni --rechazar, pregunta en la terminal.
"""

from __future__ import annotations

import argparse
import json
import time

from tickets_rag.grafo import atender, reanudar, resumen_costo, sistema


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("texto")
    parser.add_argument("--rol", choices=["N1", "N2"], default="N1")
    parser.add_argument("--ticket", default="TCK-2026-09999")
    decision = parser.add_mutually_exclusive_group()
    decision.add_argument("--aprobar", action="store_true")
    decision.add_argument("--rechazar", action="store_true")
    args = parser.parse_args()

    with sistema() as grafo:
        inicio = time.perf_counter()
        estado, cfg = atender(grafo, args.ticket, args.rol, args.texto)
        while "__interrupt__" in estado:
            pausa = estado["__interrupt__"][0].value
            print(f"\n[Aprobación N2] {pausa['pregunta']}")
            aprobada = args.aprobar or (not args.rechazar and input("¿Aprobar? (s/n): ").strip().lower() == "s")
            estado = reanudar(grafo, cfg, aprobada=aprobada, aprobador="Técnico N2 (demo)", rol="N2")
        print(json.dumps(estado["respuesta"], ensure_ascii=False, indent=2))
        print(f"\nruta: {estado.get('ruta')} | revisión: {estado.get('revision')} | "
              f"{time.perf_counter() - inicio:.1f} s | US${resumen_costo(estado)}")


if __name__ == "__main__":
    main()
