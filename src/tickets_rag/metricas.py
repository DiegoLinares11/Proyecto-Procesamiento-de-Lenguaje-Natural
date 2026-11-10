"""Métricas de recuperación (sección 12 del anteproyecto). Devuelven None si no aplica."""

from __future__ import annotations

from statistics import mean


def recall_at_k(recuperados: list[str], relevantes: set[str], k: int) -> float | None:
    """Relevantes en el top k / total de relevantes."""
    if not relevantes:
        return None
    return len(set(recuperados[:k]) & relevantes) / len(relevantes)


def precision_at_k(recuperados: list[str], relevantes: set[str], k: int) -> float | None:
    """Relevantes en el top k / k. Con pocos relevantes por caso, su máximo es bajo."""
    if not relevantes:
        return None
    return len(set(recuperados[:k]) & relevantes) / k


def reciprocal_rank(recuperados: list[str], relevantes: set[str]) -> float | None:
    """1 / posición del primer relevante; 0 si no aparece."""
    if not relevantes:
        return None
    for posicion, chunk_id in enumerate(recuperados, start=1):
        if chunk_id in relevantes:
            return 1 / posicion
    return 0.0


def promedio(valores: list[float | None]) -> float | None:
    utiles = [v for v in valores if v is not None]
    return round(mean(utiles), 3) if utiles else None
