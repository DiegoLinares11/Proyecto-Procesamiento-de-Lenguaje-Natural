"""Corre la generación de la línea base sobre el set de validación y mide su operación.

Uso:
    uv run python scripts/evaluar_generacion.py

Necesita ANTHROPIC_API_KEY en el .env. Escribe resultados/linea_base/generacion_trazas.jsonl
y generacion_resumen.json. La fidelidad con Ragas se agrega en la fase de evaluación.
"""

from __future__ import annotations

import json
from collections import Counter

import numpy as np

from tickets_rag import config
from tickets_rag.contrato import Respuesta
from tickets_rag.generacion import GeneradorLineaBase
from tickets_rag.ingesta import cargar_chunks
from tickets_rag.lexico import IndiceBM25
from tickets_rag.metricas import promedio

SET_VALIDACION = config.EVALUACION / "validacion_dev.jsonl"
SALIDA = config.RESULTADOS / "linea_base"


def main() -> None:
    config.cargar_entorno()
    chunks = cargar_chunks()
    seccion_de = {c["chunk_id"]: (c["doc_id"], c["seccion"]) for c in chunks}
    generador = GeneradorLineaBase(IndiceBM25(chunks))
    casos = [json.loads(l) for l in SET_VALIDACION.read_text(encoding="utf-8").splitlines() if l]

    trazas = []
    for n, caso in enumerate(casos, start=1):
        respuesta, traza = generador.responder(caso["question"], rol=caso["rol"], version=caso["version"])
        Respuesta.model_validate_json(respuesta.model_dump_json())  # el contrato se cumple de ida y vuelta
        esperadas = {(f["doc_id"], f["seccion"]) for f in caso["expected_sources"]}
        citadas = [s.chunk_id for s in respuesta.sources]
        trazas.append({
            "id": caso["id"],
            "tipo": caso["tipo"],
            "answerable": caso["answerable"],
            "abstencion_correcta": respuesta.abstained != caso["answerable"],
            "precision_citas": (sum(seccion_de[c] in esperadas for c in citadas) / len(citadas)) if citadas else None,
            **traza,
        })
        print(f"{n}/{len(casos)} {caso['id']} abstuvo={respuesta.abstained} citas={citadas} {traza['segundos_total']} s")

    con_respuesta = [t for t in trazas if t["answerable"]]
    sin_respuesta = [t for t in trazas if not t["answerable"]]
    latencias = [t["segundos_total"] for t in trazas]
    resumen = {
        "sistema": "linea_base_bm25_prompt_estructurado",
        "modelo": config.MODELO_GENERADOR,
        "casos": len(trazas),
        "validez_contrato": 1.0,
        "abstencion_correcta": round(sum(t["abstencion_correcta"] for t in trazas) / len(trazas), 3),
        "falsas_abstenciones": round(sum(t["respuesta"]["abstained"] for t in con_respuesta) / len(con_respuesta), 3),
        "abstenciones_omitidas": sum(not t["respuesta"]["abstained"] for t in sin_respuesta),
        "precision_citas": promedio([t["precision_citas"] for t in con_respuesta]),
        "latencia_media_s": round(float(np.mean(latencias)), 2),
        "latencia_p95_s": round(float(np.percentile(latencias, 95)), 2),
        "costo_promedio_usd": round(float(np.mean([t["costo_usd"] for t in trazas])), 5),
        "costo_total_usd": round(sum(t["costo_usd"] for t in trazas), 4),
        "tokens_entrada": sum(t["tokens_entrada"] for t in trazas),
        "tokens_salida": sum(t["tokens_salida"] for t in trazas),
        "llamadas": sum(t["llamadas"] for t in trazas),
        "motivos_abstencion": dict(Counter(t["motivo_abstencion"] for t in trazas if t["motivo_abstencion"])),
        "modelos_servidos": dict(Counter(t["modelo_servido"] for t in trazas if t["modelo_servido"])),
    }

    SALIDA.mkdir(parents=True, exist_ok=True)
    with (SALIDA / "generacion_trazas.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for t in trazas:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    (SALIDA / "generacion_resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(resumen, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
