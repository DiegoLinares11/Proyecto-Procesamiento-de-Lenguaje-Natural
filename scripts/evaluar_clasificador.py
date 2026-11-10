"""Entrena el clasificador TF-IDF con los tickets de F3 del índice y lo evalúa con los 60 reservados.

Uso:
    uv run python scripts/evaluar_clasificador.py

Escribe resultados/linea_base/clasificador_tfidf.json y clasificador_predicciones.csv.
"""

from __future__ import annotations

import csv
import json

from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

from tickets_rag import config
from tickets_rag.clasificador import construir, preparar

TICKETS = config.DATOS / "f3_tickets" / "tickets.jsonl"
SALIDA = config.RESULTADOS / "linea_base"
OBJETIVOS = ("categoria", "prioridad")


def main() -> None:
    if not TICKETS.exists():
        raise SystemExit("Falta F3. Corre primero: uv run python scripts/generar_f3.py")
    tickets = [json.loads(l) for l in TICKETS.read_text(encoding="utf-8").splitlines() if l]
    entrenamiento = [t for t in tickets if t["particion"] == "indice"]
    prueba = [t for t in tickets if t["particion"] == "prueba"]
    x_entrenamiento = [preparar(t["texto"]) for t in entrenamiento]
    x_prueba = [preparar(t["texto"]) for t in prueba]

    resumen = {"sistema": "linea_base_tfidf", "entrenamiento": len(entrenamiento), "prueba": len(prueba)}
    predicciones = {t["ticket_id"]: {"ticket_id": t["ticket_id"]} for t in prueba}
    for objetivo in OBJETIVOS:
        modelo = construir().fit(x_entrenamiento, [t[objetivo] for t in entrenamiento])
        reales = [t[objetivo] for t in prueba]
        predichas = list(modelo.predict(x_prueba))
        etiquetas = sorted(set(reales) | set(predichas))
        resumen[objetivo] = {
            "macro_f1": round(f1_score(reales, predichas, average="macro"), 3),
            "accuracy": round(accuracy_score(reales, predichas), 3),
            "por_clase": {
                k: {m: round(v, 3) for m, v in d.items()}
                for k, d in classification_report(reales, predichas, output_dict=True, zero_division=0).items()
                if k in etiquetas
            },
            "etiquetas": etiquetas,
            "matriz_confusion": confusion_matrix(reales, predichas, labels=etiquetas).tolist(),
        }
        for t, p in zip(prueba, predichas):
            predicciones[t["ticket_id"]][f"{objetivo}_real"] = t[objetivo]
            predicciones[t["ticket_id"]][f"{objetivo}_predicha"] = p

    SALIDA.mkdir(parents=True, exist_ok=True)
    (SALIDA / "clasificador_tfidf.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    filas = list(predicciones.values())
    with (SALIDA / "clasificador_predicciones.csv").open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)

    for objetivo in OBJETIVOS:
        r = resumen[objetivo]
        print(f"{objetivo}: macro-F1 {r['macro_f1']}  accuracy {r['accuracy']}")
        for clase, m in r["por_clase"].items():
            print(f"  {clase:<13} f1={m['f1-score']}  n={int(m['support'])}")


if __name__ == "__main__":
    main()
