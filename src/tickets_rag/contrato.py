"""Contrato de salida del sistema (sección 11 del enunciado), validado con Pydantic."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Fuente(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    page: int
    chunk_id: str


class Respuesta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    sources: list[Fuente]
    abstained: bool
    tool_used: str | None
    needs_human_review: bool
