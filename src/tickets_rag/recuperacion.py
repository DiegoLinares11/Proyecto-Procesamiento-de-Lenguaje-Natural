"""Recuperación híbrida: BM25 + vectores, fusionados con Reciprocal Rank Fusion, y reranking.

1. BM25 (léxico) y pgvector (semántico) traen 50 candidatos cada uno, con el mismo filtro de
   rol, vigencia y tipo de documento.
2. RRF los fusiona por posición: score = sum(peso / (k + posición)), con k = 60. No compara los
   scores crudos, que están en escalas distintas.
3. El reranker lee consulta y fragmento juntos y reordena los 20 mejores. Su score, entre 0 y 1,
   es el que decide la abstención con el umbral τ.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import psycopg

from tickets_rag import config, vectores
from tickets_rag.embeddings import embeber, puntuar
from tickets_rag.lexico import IndiceBM25, Resultado


@dataclass
class Configuracion:
    modelo: str = "bge-m3"          # modelo de embeddings
    usar_bm25: bool = True
    usar_vectores: bool = True
    usar_reranker: bool = True
    peso_bm25: float = 0.5
    peso_vectores: float = 0.5
    k_rrf: int = 60
    candidatos: int = 50
    a_reordenar: int = 20
    tipos: list[str] | None = field(default=None)  # None = todos los tipos de documento

    def nombre(self) -> str:
        partes = [p for p, activo in (("bm25", self.usar_bm25), (self.modelo, self.usar_vectores)) if activo]
        nombre = "+".join(partes)
        if self.usar_bm25 and self.usar_vectores:
            nombre = f"rrf({nombre}, {self.peso_bm25:g}/{self.peso_vectores:g})"
        if self.usar_reranker:
            nombre += "+reranker"
        if self.tipos:
            nombre += f" [{','.join(self.tipos)}]"
        return nombre


class RecuperadorHibrido:
    def __init__(self, chunks: list[dict], configuracion: Configuracion,
                 conexion: psycopg.Connection | None = None, bm25: IndiceBM25 | None = None) -> None:
        self.cfg = configuracion
        self.por_id = {c["chunk_id"]: c for c in chunks}
        self.bm25 = bm25 or IndiceBM25(chunks)
        self.conexion = conexion if conexion is not None or not configuracion.usar_vectores else vectores.conectar()

    def candidatos_bm25(self, consulta: str, rol: str, version: str | None) -> list[str]:
        return [r.chunk["chunk_id"] for r in
                self.bm25.buscar(consulta, rol, version, top_k=self.cfg.candidatos, tipos=self.cfg.tipos)]

    def candidatos_vectores(self, consulta: str, rol: str, version: str | None) -> list[str]:
        vector = embeber(self.cfg.modelo, [consulta])[0]
        return [cid for cid, _ in vectores.buscar(self.conexion, self.cfg.modelo, vector, rol, version,
                                                  self.cfg.tipos, k=self.cfg.candidatos)]

    def buscar(self, consulta: str, rol: str, version: str | None = None,
               top_k: int = config.TOP_K) -> list[Resultado]:
        listas = []
        if self.cfg.usar_bm25:
            listas.append((self.cfg.peso_bm25, self.candidatos_bm25(consulta, rol, version)))
        if self.cfg.usar_vectores:
            listas.append((self.cfg.peso_vectores, self.candidatos_vectores(consulta, rol, version)))

        fusion: dict[str, float] = {}
        for peso, ids in listas:
            for posicion, cid in enumerate(ids, start=1):
                fusion[cid] = fusion.get(cid, 0.0) + peso / (self.cfg.k_rrf + posicion)
        ordenados = sorted(fusion, key=lambda cid: -fusion[cid])
        if not ordenados:
            return []

        if not self.cfg.usar_reranker:
            return [Resultado(self.por_id[cid], fusion[cid], n) for n, cid in enumerate(ordenados[:top_k], start=1)]

        a_reordenar = ordenados[: self.cfg.a_reordenar]
        scores = puntuar(consulta, [self.por_id[cid]["text"] for cid in a_reordenar])
        reordenados = sorted(zip(a_reordenar, scores), key=lambda x: -x[1])[:top_k]
        return [Resultado(self.por_id[cid], float(s), n) for n, (cid, s) in enumerate(reordenados, start=1)]
