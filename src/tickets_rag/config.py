"""Rutas y parámetros compartidos. Las credenciales salen del .env, nunca del código."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Windows sin modo desarrollador no crea symlinks en la caché de Hugging Face; funciona igual.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

RAIZ = Path(__file__).resolve().parents[2]
# Los modelos configurables deben leerse después del .env. Ninguna clave de API se transmite a Codex.
load_dotenv(RAIZ / ".env")
DATOS = RAIZ / "datos"
INDICES = RAIZ / "indices"
RESULTADOS = RAIZ / "resultados"
RESULTADOS_SUSCRIPCION = RESULTADOS / "codex_suscripcion"
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
# Cada proceso de inferencia tiene timeout; no hay reintentos ni cambio de proveedor ante fallo.
def _timeout_modelo() -> int:
    try:
        valor = int(os.environ.get("CODEX_TIMEOUT_MODELO_S", "90"))
    except ValueError:
        raise ValueError("CODEX_TIMEOUT_MODELO_S debe ser un entero entre 10 y 600.") from None
    if not 10 <= valor <= 600:
        raise ValueError("CODEX_TIMEOUT_MODELO_S debe ser un entero entre 10 y 600.")
    return valor


TIMEOUT_MODELO_S = _timeout_modelo()
REINTENTOS_MODELO = 0
CORRIDAS_CLASIFICADOR = 5
# Revisión humana si algún voto discrepa (confianza < 1). Con el 0.6 del anteproyecto ningún ticket
# llegaba a revisión; con esto, en los 40 de desarrollo se revisa el 28 % y se atrapan 5 de 8 errores.
CONFIANZA_MINIMA = 1.0

# Modelos (sección 9 del anteproyecto)
MODELO_GENERADOR = os.environ.get("CODEX_MODELO_GENERADOR", "gpt-6.2-sol")
MODELO_CLASIFICADOR = os.environ.get("CODEX_MODELO_CLASIFICADOR", "gpt-6.2-sol")
# Juez de la evaluación: un modelo distinto del generador, para no calificar sus propias respuestas
MODELO_JUEZ = os.environ.get("CODEX_MODELO_JUEZ", "gpt-6.2-astra")

def costo_usd(modelo: str, tokens_entrada: int, tokens_salida: int,
              escritura_cache: int = 0, lectura_cache: int = 0) -> float:
    """Costo incremental de API: 0 por la ruta de suscripción, que SÍ consume tokens/cuota.

    No prorratea el precio del plan ni representa los costos históricos de Anthropic.
    """
    if modelo not in {MODELO_GENERADOR, MODELO_CLASIFICADOR, MODELO_JUEZ}:
        raise ValueError("El costo solo se calcula para los modelos actuales de la suscripción")
    return 0.0

# Buzones de rol: no son datos personales y no se enmascaran
CORREOS_INSTITUCIONALES = frozenset({"mesadeayuda@valcora.example"})


def cargar_entorno() -> None:
    """Carga el .env local si existe. No imprime ni devuelve valores."""
    load_dotenv(RAIZ / ".env")
