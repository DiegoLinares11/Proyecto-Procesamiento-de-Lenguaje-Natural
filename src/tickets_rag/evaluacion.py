"""Evaluación de recuperación con el set de validación, a nivel de unidad.

Una unidad es lo que una persona citaría: un procedimiento del manual, un artículo de Microsoft
o un ticket. Un artículo largo ocupa varios chunks, y basta con recuperar uno de ellos para
contar la unidad como encontrada.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from collections.abc import Callable

import numpy as np

from tickets_rag import config
from tickets_rag.lexico import Resultado
from tickets_rag.metricas import promedio

SET_VALIDACION = config.EVALUACION / "validacion_dev.jsonl"


def cargar_casos() -> list[dict]:
    return [json.loads(l) for l in SET_VALIDACION.read_text(encoding="utf-8").splitlines() if l]


def evaluar(buscar: Callable[[dict], list[Resultado]], casos: list[dict], k: int = config.TOP_K) -> tuple[list[dict], dict]:
    filas = []
    for caso in casos:
        relevantes = {f["unidad"] for f in caso["expected_sources"]}
        inicio = time.perf_counter()
        resultados = buscar(caso)[:k]
        segundos = time.perf_counter() - inicio
        unidades = [r.chunk["unidad"] for r in resultados]
        primera = next((n for n, u in enumerate(unidades, start=1) if u in relevantes), None)
        filas.append({
            "id": caso["id"],
            "tipo": caso["tipo"],
            "answerable": caso["answerable"],
            "recall@k": len(set(unidades) & relevantes) / len(relevantes) if relevantes else None,
            "reciprocal_rank": (1 / primera if primera else 0.0) if relevantes else None,
            "precision@k": sum(u in relevantes for u in unidades) / k if relevantes else None,
            "score_top1": round(resultados[0].score, 4) if resultados else 0.0,
            "segundos": round(segundos, 3),
            "unidades_esperadas": " ".join(sorted(relevantes)),
            "unidades_recuperadas": " ".join(unidades),
            "tipos_recuperados": " ".join(r.chunk["doc_type"] for r in resultados),
            "fuga_de_permisos": any(caso["rol"] not in r.chunk["roles_permitidos"] for r in resultados),
        })

    con_respuesta = [f for f in filas if f["answerable"]]
    por_tipo = defaultdict(list)
    for f in con_respuesta:
        por_tipo[f["tipo"]].append(f)
    segundos = [f["segundos"] for f in filas]
    resumen = {
        "casos": len(filas),
        "recall@k": promedio([f["recall@k"] for f in con_respuesta]),
        "mrr": promedio([f["reciprocal_rank"] for f in con_respuesta]),
        "precision@k": promedio([f["precision@k"] for f in con_respuesta]),
        "por_tipo": {t: {"casos": len(fs), "recall@k": promedio([f["recall@k"] for f in fs]),
                         "mrr": promedio([f["reciprocal_rank"] for f in fs])} for t, fs in sorted(por_tipo.items())},
        "latencia_media_s": round(float(np.mean(segundos)), 3),
        "latencia_p95_s": round(float(np.percentile(segundos, 95)), 3),
        "fugas_de_permisos": sum(f["fuga_de_permisos"] for f in filas),
        "score_top1_con_respuesta": [f["score_top1"] for f in con_respuesta],
        "score_top1_sin_respuesta": [f["score_top1"] for f in filas if not f["answerable"]],
    }
    return filas, resumen


def calibrar_umbral(con_respuesta: list[float], sin_respuesta: list[float]) -> dict:
    """Umbral τ que más casos clasifica bien: abstenerse si el mejor score es menor que τ.

    Con pocos casos sin respuesta, el valor es orientativo y conviene revisarlo con el banco
    oficial antes de fijarlo.
    """
    candidatos = sorted(set(con_respuesta) | set(sin_respuesta))
    mejor = None
    for i, valor in enumerate(candidatos):
        # τ a medio camino entre dos scores observados, para no depender de un empate exacto
        tau = (valor + candidatos[i + 1]) / 2 if i + 1 < len(candidatos) else valor + 1e-4
        falsas = sum(s < tau for s in con_respuesta)
        omitidas = sum(s >= tau for s in sin_respuesta)
        aciertos = len(con_respuesta) + len(sin_respuesta) - falsas - omitidas
        # Ante un empate se prefiere el τ más bajo: una falsa abstención cuesta menos que inventar.
        if mejor is None or aciertos > mejor["aciertos"]:
            mejor = {"tau": round(tau, 4), "aciertos": aciertos, "falsas_abstenciones": falsas,
                     "abstenciones_omitidas": omitidas, "casos": len(con_respuesta) + len(sin_respuesta)}
    return mejor
