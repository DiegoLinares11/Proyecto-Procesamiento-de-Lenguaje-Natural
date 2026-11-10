"""Evalúa la recuperación BM25 de la línea base con el set de validación.

Uso:
    uv run python scripts/evaluar_recuperacion.py

Escribe resultados/linea_base/recuperacion_por_caso.csv y recuperacion_resumen.json.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict

from tickets_rag import config
from tickets_rag.ingesta import cargar_chunks
from tickets_rag.lexico import IndiceBM25
from tickets_rag.metricas import precision_at_k, promedio, recall_at_k, reciprocal_rank

SET_VALIDACION = config.EVALUACION / "validacion_dev.jsonl"
SALIDA = config.RESULTADOS / "linea_base"


def cargar_casos() -> list[dict]:
    return [json.loads(l) for l in SET_VALIDACION.read_text(encoding="utf-8").splitlines() if l]


def main() -> None:
    chunks = cargar_chunks()
    indice = IndiceBM25(chunks)
    k = config.TOP_K
    filas = []
    for caso in cargar_casos():
        esperadas = {(f["doc_id"], f["seccion"]) for f in caso["expected_sources"]}
        relevantes = {c["chunk_id"] for c in chunks if (c["doc_id"], c["seccion"]) in esperadas}
        resultados = indice.buscar(caso["question"], rol=caso["rol"], version=caso["version"], top_k=k)
        ids = [r.chunk["chunk_id"] for r in resultados]
        filas.append({
            "id": caso["id"],
            "tipo": caso["tipo"],
            "rol": caso["rol"],
            "answerable": caso["answerable"],
            f"recall@{k}": recall_at_k(ids, relevantes, k),
            "reciprocal_rank": reciprocal_rank(ids, relevantes),
            f"precision@{k}": precision_at_k(ids, relevantes, k),
            "resultados": len(ids),
            "score_top1": round(resultados[0].score, 3) if resultados else 0.0,
            "secciones_esperadas": " ".join(sorted(s for _, s in esperadas)),
            "secciones_recuperadas": " ".join(r.chunk["seccion"] for r in resultados),
            "fuga_de_permisos": any(caso["rol"] not in r.chunk["roles_permitidos"] for r in resultados),
        })

    respondibles = [f for f in filas if f["answerable"]]
    por_tipo = defaultdict(list)
    for f in respondibles:
        por_tipo[f["tipo"]].append(f)
    resumen = {
        "sistema": "linea_base_bm25",
        "casos": len(filas),
        "casos_con_respuesta": len(respondibles),
        f"recall@{k}": promedio([f[f"recall@{k}"] for f in respondibles]),
        "mrr": promedio([f["reciprocal_rank"] for f in respondibles]),
        f"precision@{k}": promedio([f[f"precision@{k}"] for f in respondibles]),
        "por_tipo": {
            t: {
                "casos": len(fs),
                f"recall@{k}": promedio([f[f"recall@{k}"] for f in fs]),
                "mrr": promedio([f["reciprocal_rank"] for f in fs]),
            }
            for t, fs in sorted(por_tipo.items())
        },
        "sin_respuesta_con_evidencia_devuelta": sum(1 for f in filas if not f["answerable"] and f["resultados"] > 0),
        "fugas_de_permisos": sum(f["fuga_de_permisos"] for f in filas),
    }

    SALIDA.mkdir(parents=True, exist_ok=True)
    with (SALIDA / "recuperacion_por_caso.csv").open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)
    (SALIDA / "recuperacion_resumen.json").write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Recall@{k}: {resumen[f'recall@{k}']}   MRR: {resumen['mrr']}   Precision@{k}: {resumen[f'precision@{k}']}")
    for t, r in resumen["por_tipo"].items():
        print(f"  {t:<14} n={r['casos']}  recall@{k}={r[f'recall@{k}']}  mrr={r['mrr']}")
    print(f"Sin respuesta que igual devolvieron evidencia: {resumen['sin_respuesta_con_evidencia_devuelta']} de "
          f"{len(filas) - len(respondibles)}   Fugas de permisos: {resumen['fugas_de_permisos']}")
    for f in filas:
        if f["answerable"] and (f[f"recall@{k}"] or 0) < 1:
            print(f"  falla {f['id']} ({f['tipo']}): esperadas {f['secciones_esperadas']} | recuperadas {f['secciones_recuperadas']}")


if __name__ == "__main__":
    main()
