"""Rutas y parámetros compartidos. Las credenciales salen del .env, nunca del código."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Windows sin modo desarrollador no crea symlinks en la caché de Hugging Face; funciona igual.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

RAIZ = Path(__file__).resolve().parents[2]
DATOS = RAIZ / "datos"
INDICES = RAIZ / "indices"
RESULTADOS = RAIZ / "resultados"
EVALUACION = RAIZ / "evaluacion"

MANIFIESTO = DATOS / "manifiesto.json"
CHUNKS = INDICES / "chunks.jsonl"
RESUMEN_INGESTA = INDICES / "resumen_ingesta.json"

# Segmentación (sección 10 del anteproyecto)
TOKENIZER_EMBEDDINGS = "BAAI/bge-m3"
MAX_TOKENS_CHUNK = 450
SOLAPAMIENTO_TOKENS = 50

# Recuperación
TOP_K = 5
ROLES = ("N1", "N2")
# Umbral τ sobre el score del reranker, calibrado en la fase 3 (resultados/rag/reporte_rag.md)
UMBRAL_TAU = 0.0045

# Herramientas (sección 11 del anteproyecto)
TIMEOUT_HERRAMIENTA_S = 10
REINTENTOS_HERRAMIENTA = 1
MAX_LLAMADAS_HERRAMIENTAS = 5
CORRIDAS_CLASIFICADOR = 5
# Revisión humana si algún voto discrepa (confianza < 1). Con el 0.6 del anteproyecto ningún ticket
# llegaba a revisión; con esto, en los 40 de desarrollo se revisa el 28 % y se atrapan 5 de 8 errores.
CONFIANZA_MINIMA = 1.0

# Modelos (sección 9 del anteproyecto)
MODELO_GENERADOR = "claude-sonnet-5-5"
MODELO_CLASIFICADOR = "claude-haiku-5-5"

# Precios en US$ por millón de tokens (entrada, salida, escritura en caché de 5 min, lectura de caché),
# según platform.claude.com/docs/en/about-claude/pricing, consultado el 2026-11-08.
# El de Haiku 5.5 aplica a prompts de hasta 100 000 tokens.
PRECIOS = {
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
}


def costo_usd(modelo: str, tokens_entrada: int, tokens_salida: int,
              escritura_cache: int = 0, lectura_cache: int = 0) -> float:
    """`tokens_entrada` es solo la parte sin caché, como la reporta la API en usage.input_tokens."""
    entrada, salida, escritura, lectura = PRECIOS[modelo]
    return (tokens_entrada * entrada + tokens_salida * salida
            + escritura_cache * escritura + lectura_cache * lectura) / 1_000_000

# Buzones de rol: no son datos personales y no se enmascaran
CORREOS_INSTITUCIONALES = frozenset({"mesadeayuda@valcora.example"})


def cargar_entorno() -> None:
    """Carga el .env local si existe. No imprime ni devuelve valores."""
    load_dotenv(RAIZ / ".env")
