"""Evalúa el clasificador few-shot (Haiku 5.5, 5 votos) y lo compara con TF-IDF.

Uso:
    uv run python scripts/evaluar_clasificador_llm.py --conjunto desarrollo   # compara variantes
    uv run python scripts/evaluar_clasificador_llm.py --conjunto prueba --variante juegos_criterios

El prompt se ajusta con los 40 tickets de desarrollo (del historial). Los 60 de prueba se usan una
sola vez, con la variante elegida, para el número final. Necesita ANTHROPIC_API_KEY en el .env.

Ojo: F3 es sintético y TF-IDF sale inflado con él. La comparación que vale es con los 20 tickets
escritos a mano que propone el anteproyecto.
"""

from __future__ import annotations

import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor

from sklearn.metrics import f1_score

from tickets_rag import config
from tickets_rag.clasificador import construir, preparar
from tickets_rag.clasificador_llm import ClasificadorLLM, tickets_desarrollo

TICKETS = config.DATOS / "f3_tickets" / "tickets.jsonl"
SALIDA = config.RESULTADOS / "herramientas"

VARIANTES = {
    "original": dict(juegos_distintos=False, reglas_extra=False, effort="low"),
    "juegos": dict(juegos_distintos=True, reglas_extra=False, effort="low"),
    "juegos_criterios": dict(juegos_distintos=True, reglas_extra=True, effort="low"),
    "juegos_criterios_medium": dict(juegos_distintos=True, reglas_extra=True, effort="medium"),
}


def evaluar(nombre: str, casos: list[dict], tfidf: dict[str, list[str]]) -> tuple[dict, list[dict]]:
    clasificador = ClasificadorLLM(**VARIANTES[nombre])
    with ThreadPoolExecutor(max_workers=4) as pool:
        resultados = list(pool.map(lambda t: clasificador.clasificar(t["texto"]), casos))
    filas = [{
        "ticket_id": t["ticket_id"],
        "categoria_real": t["categoria"], "categoria_llm": r.categoria, "categoria_tfidf": tfidf["categoria"][i],
        "prioridad_real": t["prioridad"], "prioridad_llm": r.prioridad, "prioridad_tfidf": tfidf["prioridad"][i],
        "tipo_llm": r.tipo,
        "confianza_categoria": r.confianza["categoria"], "confianza_prioridad": r.confianza["prioridad"],
        "confianza_tipo": r.confianza["tipo"], "revision_humana": r.needs_human_review,
    } for i, (t, r) in enumerate(zip(casos, resultados))]

    def f1(campo, sistema):
        return round(f1_score([f[f"{campo}_real"] for f in filas], [f[f"{campo}_{sistema}"] for f in filas], average="macro"), 3)

    errores = [f for f in filas if f["categoria_real"] != f["categoria_llm"] or f["prioridad_real"] != f["prioridad_llm"]]
    unanimes = [f for f in filas if min(f["confianza_categoria"], f["confianza_prioridad"]) == 1.0]
    resumen = {
        "variante": nombre,
        "tickets": len(filas),
        "macro_f1_llm": {c: f1(c, "llm") for c in ("categoria", "prioridad")},
        "macro_f1_tfidf": {c: f1(c, "tfidf") for c in ("categoria", "prioridad")},
        "tickets_con_error": len(errores),
        # ¿La confianza detecta errores? Unánimes deberían acertar más que divididos.
        "unanimes": len(unanimes),
        "errores_en_unanimes": sum(f in errores for f in unanimes),
        "errores_en_divididos": len(errores) - sum(f in errores for f in unanimes),
        "revision_humana": sum(f["revision_humana"] for f in filas),
        "errores_enviados_a_revision": sum(f["revision_humana"] for f in errores),
        "tipos": {tipo: sum(f["tipo_llm"] == tipo for f in filas) for tipo in sorted({f["tipo_llm"] for f in filas})},
        "costo_usd": round(sum(r.costo_usd for r in resultados), 4),
        "costo_por_ticket_usd": round(sum(r.costo_usd for r in resultados) / len(filas), 5),
    }
    return resumen, filas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--conjunto", choices=["desarrollo", "prueba"], required=True)
    parser.add_argument("--variante", choices=list(VARIANTES), help="obligatoria con --conjunto prueba")
    args = parser.parse_args()
    if args.conjunto == "prueba" and not args.variante:
        parser.error("con --conjunto prueba hay que elegir una sola --variante")

    config.cargar_entorno()
    tickets = [json.loads(l) for l in TICKETS.read_text(encoding="utf-8").splitlines() if l]
    desarrollo_ids = {t["ticket_id"] for t in tickets_desarrollo()}
    if args.conjunto == "desarrollo":
        casos = tickets_desarrollo()
        entrenamiento = [t for t in tickets if t["particion"] == "indice" and t["ticket_id"] not in desarrollo_ids]
    else:
        casos = [t for t in tickets if t["particion"] == "prueba"]
        entrenamiento = [t for t in tickets if t["particion"] == "indice"]

    tfidf = {}
    for objetivo in ("categoria", "prioridad"):
        modelo = construir().fit([preparar(t["texto"]) for t in entrenamiento], [t[objetivo] for t in entrenamiento])
        tfidf[objetivo] = list(modelo.predict([preparar(t["texto"]) for t in casos]))

    variantes = list(VARIANTES) if args.conjunto == "desarrollo" else [args.variante]
    resumenes = {}
    SALIDA.mkdir(parents=True, exist_ok=True)
    for nombre in variantes:
        resumen, filas = evaluar(nombre, casos, tfidf)
        resumenes[nombre] = resumen
        with (SALIDA / f"clasificador_{args.conjunto}_{nombre}.csv").open("w", encoding="utf-8", newline="") as f:
            escritor = csv.DictWriter(f, fieldnames=list(filas[0]))
            escritor.writeheader()
            escritor.writerows(filas)
        print(json.dumps(resumen, ensure_ascii=False))
    (SALIDA / f"clasificador_{args.conjunto}.json").write_text(json.dumps(resumenes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
