"""Índice vectorial en PostgreSQL con pgvector (sección 10 del anteproyecto).

Una tabla por modelo de embeddings, con índice HNSW (m = 16, ef_construction = 64) y distancia
coseno. El filtro por rol, vigencia y tipo de documento va en el WHERE de la misma consulta:
pgvector lo aplica después de recorrer el índice, y con hnsw.iterative_scan sigue buscando hasta
juntar los k resultados, así que ningún fragmento no permitido sale de la base de datos.
"""

from __future__ import annotations

import os

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

from tickets_rag import config


def url_bd() -> str:
    config.cargar_entorno()
    faltan = [v for v in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB") if not os.environ.get(v)]
    if faltan:
        raise RuntimeError(f"Faltan variables en el .env: {', '.join(faltan)}")
    return (f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
            f"@{os.environ.get('POSTGRES_HOST', '127.0.0.1')}:{os.environ.get('POSTGRES_PORT', '5433')}"
            f"/{os.environ['POSTGRES_DB']}")


def conectar() -> psycopg.Connection:
    conexion = psycopg.connect(url_bd(), autocommit=True)
    conexion.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conexion)
    return conexion


def tabla(modelo: str) -> str:
    return "chunks_" + modelo.replace("-", "_")


def crear_tabla(conexion: psycopg.Connection, modelo: str, dimensiones: int) -> None:
    t = tabla(modelo)
    conexion.execute(f"DROP TABLE IF EXISTS {t}")
    conexion.execute(f"""
        CREATE TABLE {t} (
            chunk_id text PRIMARY KEY,
            doc_id text NOT NULL,
            doc_type text NOT NULL,
            unidad text NOT NULL,
            version text NOT NULL,
            vigente boolean NOT NULL,
            roles_permitidos text[] NOT NULL,
            metadatos jsonb NOT NULL,
            embedding vector({dimensiones}) NOT NULL
        )""")


def cargar(conexion: psycopg.Connection, modelo: str, chunks: list[dict], vectores: np.ndarray) -> None:
    t = tabla(modelo)
    with conexion.cursor() as cur:
        cur.executemany(
            f"INSERT INTO {t} (chunk_id, doc_id, doc_type, unidad, version, vigente, roles_permitidos, metadatos, embedding)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [(c["chunk_id"], c["doc_id"], c["doc_type"], c["unidad"], c["version"], c["vigente"],
              c["roles_permitidos"], Jsonb(c), v) for c, v in zip(chunks, vectores)],
        )
    # El índice se crea después de cargar: es más rápido y queda mejor construido.
    conexion.execute(f"CREATE INDEX ON {t} USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)")
    conexion.execute(f"ANALYZE {t}")


def buscar(conexion: psycopg.Connection, modelo: str, vector: np.ndarray, rol: str,
           version: str | None = None, tipos: list[str] | None = None, k: int = 50) -> list[tuple[str, float]]:
    """Devuelve (chunk_id, similitud coseno) de los k más cercanos permitidos para el rol."""
    filtro_version = "version = %(version)s" if version else "vigente"
    filtro_tipo = "AND doc_type = ANY(%(tipos)s)" if tipos else ""
    with conexion.transaction():
        conexion.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        conexion.execute("SET LOCAL hnsw.ef_search = 100")
        filas = conexion.execute(
            f"""SELECT chunk_id, 1 - (embedding <=> %(v)s) AS similitud
                FROM {tabla(modelo)}
                WHERE %(rol)s = ANY(roles_permitidos) AND {filtro_version} {filtro_tipo}
                ORDER BY embedding <=> %(v)s
                LIMIT %(k)s""",
            {"v": vector, "rol": rol, "version": version, "tipos": tipos, "k": k},
        ).fetchall()
    # relaxed_order puede devolver el orden casi exacto; se ordena por similitud al final.
    return sorted(((cid, float(s)) for cid, s in filas), key=lambda x: -x[1])
