"""Corre la generación con citas sobre el set de validación y mide su operación.

Uso:
    uv run python scripts/evaluar_generacion.py --sistema linea_base   # BM25 solo sobre el manual
    uv run python scripts/evaluar_generacion.py --sistema rag          # híbrida + reranker + τ

Necesita ANTHROPIC_API_KEY en el .env; el sistema rag necesita además la base de Docker.
Escribe resultados/rag/generacion_<sistema>_trazas.jsonl y generacion_<sistema>_resumen.json.
La fidelidad con Ragas se agrega en la fase de evaluación.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter

import numpy as np

from tickets_rag import config
from tickets_rag.contrato import Respuesta
from tickets_rag.evaluacion import cargar_casos
from tickets_rag.generacion import Generador
from tickets_rag.ingesta import cargar_chunks
from tickets_rag.lexico import IndiceBM25
from tickets_rag.metricas import promedio

SALIDA = config.RESULTADOS / "rag"
UMBRAL_INICIAL = 0.30  # valor del anteproyecto si todavía no se calibró


def construir(sistema: str, chunks: list[dict]) -> tuple[Generador, float | None]:
    if sistema == "linea_base":
        return Generador(IndiceBM25([c for c in chunks if c["doc_type"] == "manual"])), None
    from tickets_rag.recuperacion import Configuracion, RecuperadorHibrido

    comparacion = SALIDA / "recuperacion_comparacion.json"
    umbral = UMBRAL_INICIAL
    if comparacion.exists():
        umbral = json.loads(comparacion.read_text(encoding="utf-8"))["rrf_reranker"]["umbral"]["tau"]
    recuperador = RecuperadorHibrido(chunks, Configuracion(tipos=["manual", "articulo"]))
    return Generador(recuperador, umbral=umbral), umbral


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sistema", choices=["linea_base", "rag"], required=True)
    args = parser.parse_args()

    config.cargar_entorno()
    chunks = cargar_chunks()
    unidad_de = {c["chunk_id"]: c["unidad"] for c in chunks}
    generador, umbral = construir(args.sistema, chunks)
    generador.indice.buscar("calentamiento", rol="N1")  # carga los modelos antes de medir latencia

    trazas = []
    for n, caso in enumerate(cargar_casos(), start=1):
        respuesta, traza = generador.responder(caso["question"], rol=caso["rol"], version=caso["version"])
        Respuesta.model_validate_json(respuesta.model_dump_json())  # el contrato se cumple de ida y vuelta
        esperadas = {f["unidad"] for f in caso["expected_sources"]}
        citadas = [s.chunk_id for s in respuesta.sources]
        trazas.append({
            "id": caso["id"],
            "tipo": caso["tipo"],
            "answerable": caso["answerable"],
            "abstencion_correcta": respuesta.abstained != caso["answerable"],
            "precision_citas": (sum(unidad_de[c] in esperadas for c in citadas) / len(citadas)) if citadas else None,
            **traza,
        })
        print(f"{n:>2} {caso['id']} abstuvo={respuesta.abstained!s:<5} citas={len(citadas)} {traza['segundos_total']} s"
              + (f"  ({traza['motivo_abstencion']})" if traza["motivo_abstencion"] else ""))

    con_respuesta = [t for t in trazas if t["answerable"]]
    sin_respuesta = [t for t in trazas if not t["answerable"]]
    latencias = [t["segundos_total"] for t in trazas]
    resumen = {
        "sistema": args.sistema,
        "modelo": config.MODELO_GENERADOR,
        "umbral_tau": umbral,
        "casos": len(trazas),
        "validez_contrato": 1.0,
        "abstencion_correcta": round(sum(t["abstencion_correcta"] for t in trazas) / len(trazas), 3),
        "falsas_abstenciones": round(sum(t["respuesta"]["abstained"] for t in con_respuesta) / len(con_respuesta), 3),
        "abstenciones_omitidas": f"{sum(not t['respuesta']['abstained'] for t in sin_respuesta)} de {len(sin_respuesta)}",
        "precision_citas": promedio([t["precision_citas"] for t in con_respuesta]),
        "latencia_media_s": round(float(np.mean(latencias)), 2),
        "latencia_p95_s": round(float(np.percentile(latencias, 95)), 2),
        "costo_promedio_usd": round(float(np.mean([t["costo_usd"] for t in trazas])), 5),
        "costo_total_usd": round(sum(t["costo_usd"] for t in trazas), 4),
        "llamadas": sum(t["llamadas"] for t in trazas),
        "motivos_abstencion": dict(Counter(t["motivo_abstencion"] for t in trazas if t["motivo_abstencion"])),
        "modelos_servidos": dict(Counter(t["modelo_servido"] for t in trazas if t["modelo_servido"])),
    }

    SALIDA.mkdir(parents=True, exist_ok=True)
    with (SALIDA / f"generacion_{args.sistema}_trazas.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for t in trazas:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    (SALIDA / f"generacion_{args.sistema}_resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(resumen, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
