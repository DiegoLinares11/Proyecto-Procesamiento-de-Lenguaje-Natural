"""Actualiza en el README el diagrama del grafo, generado directamente desde el código.

Uso:
    uv run python scripts/dibujar_grafo.py

LangGraph dibuja los nodos y aristas que existen de verdad (las punteadas son condicionales).
GitHub muestra el bloque Mermaid como diagrama. No necesita la base ni la API.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from tickets_rag import config
from tickets_rag.grafo import construir_grafo

README = config.RAIZ / "README.md"
INICIO, FIN = "<!-- grafo:inicio -->", "<!-- grafo:fin -->"


def main() -> None:
    grafo = construir_grafo(recursos=SimpleNamespace(chunks=[]), cliente=None, checkpointer=None)
    mermaid = grafo.get_graph().draw_mermaid()
    mermaid = re.sub(r"^---.*?---\s*", "", mermaid, flags=re.S)  # quita la cabecera de configuración
    bloque = f"{INICIO}\n```mermaid\n{mermaid.strip()}\n```\n{FIN}"
    texto = README.read_text(encoding="utf-8")
    if INICIO not in texto:
        raise SystemExit(f"El README no tiene los marcadores {INICIO} y {FIN}.")
    texto = re.sub(re.escape(INICIO) + r".*?" + re.escape(FIN), lambda _: bloque, texto, flags=re.S)
    README.write_text(texto, encoding="utf-8")
    print("Diagrama del grafo actualizado en el README")


if __name__ == "__main__":
    main()
