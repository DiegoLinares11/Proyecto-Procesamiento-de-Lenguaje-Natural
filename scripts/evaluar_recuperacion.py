"""Compara configuraciones de recuperación con el set de validación.

Uso:
    docker compose up -d
    uv run python scripts/evaluar_recuperacion.py

Corre después de ingestar.py e indexar_vectores.py. Escribe resultados/rag/recuperacion_*.
La primera configuración es la línea base de la fase 2: BM25 solo sobre el manual.
"""

from __future__ import annotations

import csv
import json

from tickets_rag import config, vectores
from tickets_rag.evaluacion import calibrar_umbral, cargar_casos, evaluar
from tickets_rag.ingesta import cargar_chunks
from tickets_rag.lexico import IndiceBM25
from tickets_rag.recuperacion import Configuracion, RecuperadorHibrido

SALIDA = config.RESULTADOS / "rag"
PROCEDIMIENTOS = ["manual", "articulo"]  # los tickets se buscan aparte, como casos similares

CONFIGURACIONES = {
    "linea_base": Configuracion(usar_vectores=False, usar_reranker=False, tipos=["manual"]),
    "bm25": Configuracion(usar_vectores=False, usar_reranker=False, tipos=PROCEDIMIENTOS),
    "minilm": Configuracion(modelo="minilm", usar_bm25=False, usar_reranker=False, tipos=PROCEDIMIENTOS),
    "bge-m3": Configuracion(usar_bm25=False, usar_reranker=False, tipos=PROCEDIMIENTOS),
    "rrf_0.3_0.7": Configuracion(usar_reranker=False, peso_bm25=0.3, peso_vectores=0.7, tipos=PROCEDIMIENTOS),
    "rrf": Configuracion(usar_reranker=False, tipos=PROCEDIMIENTOS),
    "rrf_0.7_0.3": Configuracion(usar_reranker=False, peso_bm25=0.7, peso_vectores=0.3, tipos=PROCEDIMIENTOS),
    "rrf_reranker": Configuracion(tipos=PROCEDIMIENTOS),
    "rrf_reranker_con_tickets": Configuracion(),
}


def evaluar_casos_similares(chunks, conexion, bm25, casos) -> dict:
    """Canal aparte de tickets: ¿alguno de los 3 tickets recuperados se resolvió con el
    procedimiento que la consulta espera? Solo aplica a consultas que esperan un procedimiento del manual."""
    recuperador = RecuperadorHibrido(chunks, Configuracion(tipos=["ticket"]), conexion=conexion, bm25=bm25)
    aciertos, total, obsoletos = 0, 0, 0
    for caso in casos:
        secciones = {f["seccion"] for f in caso["expected_sources"] if f["doc_id"].startswith("F1")}
        if not caso["answerable"] or not secciones or caso["version"]:
            continue
        tickets = recuperador.buscar(caso["question"], caso["rol"], top_k=3)
        total += 1
        aciertos += any(r.chunk["seccion_manual"] in secciones for r in tickets)
        obsoletos += sum(not r.chunk["vigente"] for r in tickets)
    return {"consultas": total, "hit@3_mismo_procedimiento": round(aciertos / total, 3), "tickets_obsoletos_devueltos": obsoletos}


def main() -> None:
    chunks = cargar_chunks()
    bm25 = IndiceBM25(chunks)
    conexion = vectores.conectar()
    casos = cargar_casos()
    SALIDA.mkdir(parents=True, exist_ok=True)

    resumenes, filas_todas = {}, []
    for nombre, cfg in CONFIGURACIONES.items():
        recuperador = RecuperadorHibrido(chunks, cfg, conexion=conexion, bm25=bm25)
        recuperador.buscar("calentamiento", rol="N1")  # carga los modelos antes de medir latencia
        filas, resumen = evaluar(lambda c: recuperador.buscar(c["question"], c["rol"], c["version"]), casos)
        resumen["configuracion"] = cfg.nombre()
        if cfg.usar_reranker:
            resumen["umbral"] = calibrar_umbral(resumen["score_top1_con_respuesta"], resumen["score_top1_sin_respuesta"])
        resumenes[nombre] = resumen
        filas_todas.extend({"sistema": nombre, **f} for f in filas)
        print(f"{nombre:<26} recall@5={resumen['recall@k']:<6} mrr={resumen['mrr']:<6} "
              f"p@5={resumen['precision@k']:<6} p95={resumen['latencia_p95_s']} s  fugas={resumen['fugas_de_permisos']}")

    similares = evaluar_casos_similares(chunks, conexion, bm25, casos)
    print(f"\nTickets como casos similares: {similares}")

    with (SALIDA / "recuperacion_por_caso.csv").open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=list(filas_todas[0]))
        escritor.writeheader()
        escritor.writerows(filas_todas)
    (SALIDA / "recuperacion_comparacion.json").write_text(
        json.dumps({**resumenes, "casos_similares": similares}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print("\nRecall@5 por tipo de consulta:")
    tipos = sorted({t for r in resumenes.values() for t in r["por_tipo"]})
    print(f"{'':<26}" + "".join(f"{t[:12]:>13}" for t in tipos))
    for nombre, r in resumenes.items():
        print(f"{nombre:<26}" + "".join(f"{str(r['por_tipo'].get(t, {}).get('recall@k', '-')):>13}" for t in tipos))
    for nombre, r in resumenes.items():
        if "umbral" in r:
            print(f"Umbral calibrado para {nombre}: {r['umbral']}")


if __name__ == "__main__":
    main()
