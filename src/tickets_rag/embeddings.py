"""Modelos locales. MPS y precisión se activan explícitamente, sin fallback de dispositivo.

Sin configuración se conserva CUDA si está disponible y CPU en otro caso, con los lotes anteriores.
En un Mac de memoria unificada limitada se puede solicitar TICKETS_DISPOSITIVO=mps,
TICKETS_PRECISION=float16 y lotes pequeños sin cambiar modelos, truncamiento ni puntuación.
TICKETS_PRECISION_RERANKER permite conservar float32 solo en el reranker; vacío hereda PRECISION.
"""

from __future__ import annotations

from functools import lru_cache
import gc
import os

from tickets_rag import config  # Carga .env también cuando este módulo se importa directamente.

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


def _dispositivo() -> str:
    solicitado = os.environ.get("TICKETS_DISPOSITIVO", "").strip().lower()
    if not solicitado:
        return "cuda" if torch.cuda.is_available() else "cpu"
    if solicitado not in {"cpu", "cuda", "mps"}:
        raise ValueError("TICKETS_DISPOSITIVO debe ser cpu, cuda o mps.")
    if solicitado == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("Se solicitó CUDA, pero no está disponible; no se cambió a CPU.")
    mps = getattr(torch.backends, "mps", None)
    if solicitado == "mps" and (mps is None or not mps.is_available()):
        raise RuntimeError("Se solicitó MPS, pero no está disponible; no se cambió a CPU.")
    return solicitado


def _precision(dispositivo: str, variable: str = "TICKETS_PRECISION", predeterminado: str | None = None) -> str:
    solicitado = os.environ.get(variable, "").strip().lower()
    valor = solicitado or predeterminado or ("float16" if dispositivo == "cuda" else "float32")
    if valor not in {"float32", "float16"}:
        raise ValueError(f"{variable} debe ser float32 o float16.")
    if dispositivo == "cpu" and valor == "float16":
        raise ValueError("float16 requiere solicitar CUDA o MPS; CPU conserva float32.")
    return valor


def _lote(variable: str, predeterminado: int) -> int:
    try:
        valor = int(os.environ.get(variable, "").strip() or str(predeterminado))
        if not 1 <= valor <= 128:
            raise ValueError
        return valor
    except ValueError:
        raise ValueError(f"{variable} debe ser un entero entre 1 y 128.") from None


def _booleano(variable: str) -> bool:
    valor = os.environ.get(variable, "").strip().lower()
    if valor not in {"", "true", "false"}:
        raise ValueError(f"{variable} debe ser true o false; vacío conserva false.")
    return valor == "true"


DISPOSITIVO = _dispositivo()
PRECISION = _precision(DISPOSITIVO)
PRECISION_RERANKER = _precision(DISPOSITIVO, "TICKETS_PRECISION_RERANKER", PRECISION)
_PRECISION_EXPLICITA = bool(os.environ.get("TICKETS_PRECISION", "").strip())
_PRECISION_RERANKER_EXPLICITA = bool(os.environ.get("TICKETS_PRECISION_RERANKER", "").strip()) or _PRECISION_EXPLICITA
LOTE_EMBEDDINGS = _lote("TICKETS_LOTE_EMBEDDINGS", 4 if DISPOSITIVO == "mps" else 16)
LOTE_RERANKER = _lote("TICKETS_LOTE_RERANKER", 4 if DISPOSITIVO == "mps" else 32)
VACIAR_CACHE_MPS = _booleano("TICKETS_VACIAR_CACHE_MPS")


def _opciones_carga(precision: str, explicita: bool) -> dict:
    # 6.2.0 acepta model_kwargs; Transformers 5.22 acepta dtype en from_pretrained.
    # Cargar MPS directamente en fp16 evita construir primero una copia completa en fp32.
    if DISPOSITIVO == "mps" or explicita:
        return {"model_kwargs": {"dtype": getattr(torch, precision)}}
    return {}


def _recolectar_tras_carga() -> None:
    if VACIAR_CACHE_MPS and DISPOSITIVO == "mps":
        gc.collect()
        # El modelo sigue vivo en la variable local del constructor; liberar solo staging sin uso.
        _vaciar_cache_mps()


def _vaciar_cache_mps() -> None:
    if VACIAR_CACHE_MPS and DISPOSITIVO == "mps":
        # Esperar todos los kernels antes de liberar SOLO reservas no ocupadas del allocator.
        # Los modelos siguen referenciados por lru_cache; no se descargan pesos ni cambia dtype.
        torch.mps.synchronize()
        torch.mps.empty_cache()


@lru_cache(maxsize=2)
def modelo_embeddings(nombre: str) -> SentenceTransformer:
    ruta, _, max_tokens = MODELOS[nombre]
    opciones = _opciones_carga(PRECISION, _PRECISION_EXPLICITA)
    modelo = SentenceTransformer(ruta, device=DISPOSITIVO, **opciones)
    modelo.max_seq_length = max_tokens
    if DISPOSITIVO == "cuda" and PRECISION == "float16" and not opciones:
        modelo.half()
    _recolectar_tras_carga()
    return modelo


def embeber(nombre: str, textos: list[str], lote: int | None = None) -> np.ndarray:
    """Vectores normalizados: la similitud coseno es el producto punto."""
    lote = LOTE_EMBEDDINGS if lote is None else lote
    if type(lote) is not int or not 1 <= lote <= 128:
        raise ValueError("El lote de embeddings debe ser un entero entre 1 y 128.")
    try:
        return modelo_embeddings(nombre).encode(
            textos, batch_size=lote, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        ).astype(np.float32)
    finally:
        # encode ya pidió numpy CPU y astype terminó antes de esta limpieza; también ante error.
        _vaciar_cache_mps()


@lru_cache(maxsize=1)
def reranker() -> CrossEncoder:
    opciones = _opciones_carga(PRECISION_RERANKER, _PRECISION_RERANKER_EXPLICITA)
    modelo = CrossEncoder(RERANKER, max_length=512, device=DISPOSITIVO, **opciones)
    if DISPOSITIVO == "cuda" and PRECISION_RERANKER == "float16" and not opciones:
        modelo.model.half()
    _recolectar_tras_carga()
    return modelo


def puntuar(consulta: str, textos: list[str]) -> np.ndarray:
    """Relevancia de cada texto para la consulta, normalizada entre 0 y 1 con una sigmoide."""
    if not textos:
        return np.array([], dtype=np.float32)
    # El lote es configurable por memoria; no cambia candidatos, logits ni la sigmoide posterior.
    try:
        logits = reranker().predict([(consulta, t) for t in textos], batch_size=LOTE_RERANKER, show_progress_bar=False,
                                    activation_fn=torch.nn.Identity(), convert_to_numpy=True)
        return (1 / (1 + np.exp(-np.asarray(logits, dtype=np.float64)))).astype(np.float32)
    finally:
        # predict entregó numpy CPU y la sigmoide conserva su cálculo float64→float32 anterior.
        _vaciar_cache_mps()
