"""Calcula los embeddings de los chunks y los carga en pgvector, una tabla por modelo.

Uso:
    docker compose up -d
    uv run python scripts/indexar_vectores.py            # BGE-M3 y MiniLM
    uv run python scripts/indexar_vectores.py bge-m3     # solo un modelo

Corre después de scripts/ingestar.py.
"""

from __future__ import annotations

import sys
import time

from tickets_rag import vectores
from tickets_rag.embeddings import DISPOSITIVO, MODELOS, embeber
from tickets_rag.ingesta import cargar_chunks


def main() -> None:
    modelos = sys.argv[1:] or list(MODELOS)
    chunks = cargar_chunks()
    conexion = vectores.conectar()
    for modelo in modelos:
        inicio = time.perf_counter()
        vectores_chunks = embeber(modelo, [c["text"] for c in chunks])
        segundos_embeddings = time.perf_counter() - inicio
        vectores.crear_tabla(conexion, modelo, MODELOS[modelo][1])
        vectores.cargar(conexion, modelo, chunks, vectores_chunks)
        total = conexion.execute(f"SELECT count(*) FROM {vectores.tabla(modelo)}").fetchone()[0]
        print(f"{modelo}: {total} chunks, {vectores_chunks.shape[1]} dimensiones, "
              f"embeddings en {segundos_embeddings:.1f} s ({DISPOSITIVO}), total {time.perf_counter() - inicio:.1f} s")


if __name__ == "__main__":
    main()
