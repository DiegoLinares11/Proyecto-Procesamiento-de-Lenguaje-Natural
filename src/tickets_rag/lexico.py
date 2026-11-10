"""Búsqueda léxica con BM25 (rank_bm25), la línea base de recuperación.

El tokenizador conserva códigos completos como 0x80070005 o ERP-401 y además agrega sus
partes, para que «error 401» también encuentre «ERP-401». No distingue tildes, porque los
usuarios suelen escribir «contrasena» o «sesion».

El filtro por rol y vigencia se aplica en la misma búsqueda: solo se puntúan los chunks
permitidos, así que un fragmento no permitido nunca sale de esta función.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi

RE_TOKEN = re.compile(r"[a-z0-9]+(?:[-_:./\\]+[a-z0-9]+)*")
RE_SEPARADOR = re.compile(r"[-_:./\\]+")

STOPWORDS = frozenset(
    """
    a al algo ante antes como con contra cual cuales cuando de del desde donde durante e el ella
    ellas ellos en entre era es esa esas ese eso esos esta estas este esto estos fue ha hace hacia
    han hasta hay la las le les lo los mas me mi mis muy ni no nos o os otra otras otro otros para
    pero por porque que se sea segun ser si sin sobre son su sus tambien te tiene tu tus un una
    uno unos y ya yo
    """.split()
)


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes."""
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def tokenizar(texto: str) -> list[str]:
    tokens: list[str] = []
    for token in RE_TOKEN.findall(normalizar(texto)):
        if token in STOPWORDS:
            continue
        tokens.append(token)
        partes = [p for p in RE_SEPARADOR.split(token) if p and p not in STOPWORDS]
        if len(partes) > 1:
            tokens.extend(partes)
    return tokens


@dataclass(frozen=True)
class Resultado:
    chunk: dict
    score: float
    posicion: int


class IndiceBM25:
    def __init__(self, chunks: list[dict]) -> None:
        if not chunks:
            raise ValueError("No hay chunks para indexar.")
        self.chunks = chunks
        self.bm25 = BM25Okapi([tokenizar(c["text"]) for c in chunks])

    def permitidos(self, rol: str, version: str | None) -> np.ndarray:
        """Máscara de chunks visibles para el rol: vigentes, o de la versión pedida."""
        mascara = np.zeros(len(self.chunks), dtype=bool)
        for i, c in enumerate(self.chunks):
            if rol not in c["roles_permitidos"]:
                continue
            mascara[i] = c["version"] == version if version else c["vigente"]
        return mascara

    def buscar(self, consulta: str, rol: str, version: str | None = None, top_k: int = 5) -> list[Resultado]:
        tokens = tokenizar(consulta)
        if not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        scores = np.where(self.permitidos(rol, version), scores, -np.inf)
        orden = np.argsort(-scores, kind="stable")[:top_k]
        # Score 0 significa que no comparte ningún término con la consulta: no es evidencia.
        return [
            Resultado(self.chunks[i], float(scores[i]), n + 1)
            for n, i in enumerate(orden)
            if scores[i] > 0
        ]
