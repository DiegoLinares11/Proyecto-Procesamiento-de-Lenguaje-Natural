"""Modelos de embeddings y reranker, ejecutados localmente (GPU si hay, si no CPU)."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import torch
from sentence_transformers import CrossEncoder, SentenceTransformer

# nombre corto: (modelo en Hugging Face, dimensiones, tokens máximos por texto)
MODELOS = {
    "bge-m3": ("BAAI/bge-m3", 1024, 512),
    # Su límite de fábrica es 128 tokens: los chunks más largos se truncan. Es parte de la comparación.
    "minilm": ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", 384, 128),
}
RERANKER = "BAAI/bge-reranker-v2-m3"
DISPOSITIVO = "cuda" if torch.cuda.is_available() else "cpu"


@lru_cache(maxsize=2)
def modelo_embeddings(nombre: str) -> SentenceTransformer:
    ruta, _, max_tokens = MODELOS[nombre]
    modelo = SentenceTransformer(ruta, device=DISPOSITIVO)
    modelo.max_seq_length = max_tokens
    if DISPOSITIVO == "cuda":
        modelo.half()
    return modelo


def embeber(nombre: str, textos: list[str], lote: int = 16) -> np.ndarray:
    """Vectores normalizados: la similitud coseno es el producto punto."""
    return modelo_embeddings(nombre).encode(
        textos, batch_size=lote, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
    ).astype(np.float32)


@lru_cache(maxsize=1)
def reranker() -> CrossEncoder:
    modelo = CrossEncoder(RERANKER, max_length=512, device=DISPOSITIVO)
    if DISPOSITIVO == "cuda":
        modelo.model.half()
    return modelo


def puntuar(consulta: str, textos: list[str]) -> np.ndarray:
    """Relevancia de cada texto para la consulta, normalizada entre 0 y 1 con una sigmoide."""
    if not textos:
        return np.array([], dtype=np.float32)
    # Un solo lote para los 20 candidatos: en la GPU, dos lotes tardan casi el triple.
    logits = reranker().predict([(consulta, t) for t in textos], batch_size=32, show_progress_bar=False,
                                activation_fn=torch.nn.Identity())
    return (1 / (1 + np.exp(-np.asarray(logits, dtype=np.float64)))).astype(np.float32)
