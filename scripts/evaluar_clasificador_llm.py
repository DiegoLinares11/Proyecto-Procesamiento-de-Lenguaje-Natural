"""Evalúa el clasificador few-shot (Codex con suscripción, 5 votos) y lo compara con TF-IDF.

Uso:
    uv run python scripts/evaluar_clasificador_llm.py --conjunto desarrollo   # compara variantes
    uv run python scripts/evaluar_clasificador_llm.py --conjunto prueba --variante juegos_criterios
    uv run python scripts/evaluar_clasificador_llm.py --conjunto manuales --variante juegos_criterios

El prompt se ajusta con los 40 tickets de desarrollo (del historial). Los 60 de prueba se usan una
sola vez, con la variante elegida, para el número final. Necesita sesión de ChatGPT y cuota incluida.

Ojo: F3 es sintético y TF-IDF sale inflado con él. La comparación que vale es con los 20 tickets
escritos a mano que propone el anteproyecto.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sklearn.metrics import f1_score

from tickets_rag import config
from tickets_rag.clasificador import construir, preparar
from tickets_rag.clasificador_llm import ClasificadorLLM, tickets_desarrollo
from tickets_rag.tickets_manuales import MANUALES, cargar_manuales

TICKETS = config.DATOS / "f3_tickets" / "tickets.jsonl"
SALIDA = config.RESULTADOS_SUSCRIPCION / "herramientas"

VARIANTES = {
    "original": dict(juegos_distintos=False, reglas_extra=False, effort="low"),
    "juegos": dict(juegos_distintos=True, reglas_extra=False, effort="low"),
    "juegos_criterios": dict(juegos_distintos=True, reglas_extra=True, effort="low"),
    "juegos_criterios_medium": dict(juegos_distintos=True, reglas_extra=True, effort="medium"),
}


def preparar_conjunto(tickets: list[dict], conjunto: str, manuales: Path = MANUALES) -> tuple[list[dict], list[dict]]:
    """Los manuales son sólo prueba: no se agregan a entrenamiento ni a ejemplos del prompt."""
    if conjunto == "manuales":
        casos = cargar_manuales(manuales)
        entrenamiento = [t for t in tickets if t["particion"] == "indice"]
    elif conjunto == "desarrollo":
        casos = tickets_desarrollo()
        ids = {t["ticket_id"] for t in casos}
        entrenamiento = [t for t in tickets if t["particion"] == "indice" and t["ticket_id"] not in ids]
    elif conjunto == "prueba":
        casos = [t for t in tickets if t["particion"] == "prueba"]
        entrenamiento = [t for t in tickets if t["particion"] == "indice"]
    else:
        raise ValueError("Conjunto desconocido")
    return casos, entrenamiento


def identidad_manuales(casos: list[dict]) -> str:
    contenido = sorted(casos, key=lambda t: t["ticket_id"])
    return hashlib.sha256(json.dumps(contenido, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def reservar_intento(salida: Path, ruta: Path, casos: list[dict], variante: str) -> dict:
    """Registra el primer intento antes de inferir; el orden del JSONL no permite repetirlo."""
    if salida.exists() and any(salida.iterdir()):
        raise ValueError("Ya existe un intento de evaluar este conjunto manual")
    salida.mkdir(parents=True, exist_ok=True)
    registro = {"estado": "iniciado", "inicio_utc": datetime.now(timezone.utc).isoformat(),
                "identidad_canonica": identidad_manuales(casos), "variante": variante,
                "modelo": config.MODELO_CLASIFICADOR,
                "tickets_manuales_sha256": hashlib.sha256(ruta.read_bytes()).hexdigest(),
                "manifiesto_sha256": hashlib.sha256((ruta.parent / "manifiesto.json").read_bytes()).hexdigest(),
                "evaluador_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with (salida / "intento.json").open("x", encoding="utf-8") as f:
        json.dump(registro, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return registro


def evaluar(nombre: str, casos: list[dict], tfidf: dict[str, list[str]], *, al_terminar=None) -> tuple[dict, list[dict]]:
    clasificador = ClasificadorLLM(**VARIANTES[nombre])
    # No dejar tickets en segundo plano ni iniciar nuevos después de un error de sesión/cuota.
    resultados = []
    for t in casos:
        r = clasificador.clasificar(t["texto"])
        resultados.append(r)
        if al_terminar:
            al_terminar(t, r)
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
        "proveedor": "codex_subscription",
        "modelo": config.MODELO_CLASIFICADOR,
        "costo_medido": "API incremental; excluye el precio del plan y consume cuota incluida",
        "tokens_entrada": sum(r.tokens_entrada for r in resultados),
        "tokens_salida": sum(r.tokens_salida for r in resultados),
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
    parser.add_argument("--conjunto", choices=["desarrollo", "prueba", "manuales"], required=True)
    parser.add_argument("--variante", choices=list(VARIANTES), help="obligatoria con --conjunto prueba")
    parser.add_argument("--tickets-manuales", type=Path, default=MANUALES, help="JSONL humano previamente validado y congelado")
    parser.add_argument("--salida-base", type=Path, default=SALIDA, help="carpeta base para resultados del clasificador")
    parser.add_argument("--solo-validar", action="store_true", help="valida el conjunto manual sin clasificar ni consumir cuota")
    args = parser.parse_args()
    if args.conjunto in {"prueba", "manuales"} and not args.variante and not args.solo_validar:
        parser.error("con --conjunto prueba/manuales hay que elegir una sola --variante")
    if args.solo_validar and args.conjunto != "manuales":
        parser.error("--solo-validar corresponde al conjunto manuales")

    config.cargar_entorno()
    tickets = [json.loads(l) for l in TICKETS.read_text(encoding="utf-8").splitlines() if l]
    try:
        casos, entrenamiento = preparar_conjunto(tickets, args.conjunto, args.tickets_manuales)
    except (OSError, ValueError):
        parser.error("No hay un conjunto manual válido y congelado; complete primero scripts/preparar_tickets_manuales.py")
    if args.solo_validar:
        print(json.dumps({"conjunto": "manuales", "tickets": len(casos), "entrenamiento_f3": len(entrenamiento),
                          "inferencias_ejecutadas": 0, "incluidos_en_entrenamiento": False}, ensure_ascii=False))
        return
    salida = args.salida_base
    manuales_hash = None
    if args.conjunto == "manuales":
        manuales_hash = hashlib.sha256(args.tickets_manuales.read_bytes()).hexdigest()
        salida = args.salida_base / "manuales" / identidad_manuales(casos)
        if salida.exists() and any(salida.iterdir()):
            parser.error("Ya existe una evaluación de este conjunto manual; conserve su primera medición")

    tfidf = {}
    for objetivo in ("categoria", "prioridad"):
        modelo = construir().fit([preparar(t["texto"]) for t in entrenamiento], [t[objetivo] for t in entrenamiento])
        tfidf[objetivo] = list(modelo.predict([preparar(t["texto"]) for t in casos]))

    variantes = list(VARIANTES) if args.conjunto == "desarrollo" else [args.variante]
    resumenes = {}
    salida.mkdir(parents=True, exist_ok=True)
    intento = None
    if manuales_hash:
        try:
            intento = reservar_intento(salida, args.tickets_manuales, casos, args.variante)
        except (OSError, ValueError):
            parser.error("No se puede reservar otro intento de este conjunto manual; conserve el registro existente")

    def registrar(ticket, resultado):
        with (salida / "mediciones_parciales.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ticket_id": ticket["ticket_id"], "resultado": resultado.model_dump()}, ensure_ascii=False) + "\n")

    for nombre in variantes:
        try:
            resumen, filas = evaluar(nombre, casos, tfidf, al_terminar=registrar if intento else None)
        except Exception:
            if intento:
                intento["estado"] = "incompleto; conservar parciales, no repetir desde cero"
                (salida / "intento.json").write_text(json.dumps(intento, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise
        resumen["conjunto"] = args.conjunto
        if manuales_hash:
            resumen["tickets_manuales_sha256"] = manuales_hash
            resumen["identidad_canonica"] = intento["identidad_canonica"]
            resumen["manifiesto_sha256"] = intento["manifiesto_sha256"]
            resumen["autoria"] = "humana_declarada_en_manifiesto; no certificada automáticamente"
            resumen["uso"] = "evaluacion_reservada; no entrenamiento ni ajuste del prompt"
        resumenes[nombre] = resumen
        with (salida / f"clasificador_{args.conjunto}_{nombre}.csv").open("w", encoding="utf-8", newline="") as f:
            escritor = csv.DictWriter(f, fieldnames=list(filas[0]))
            escritor.writeheader()
            escritor.writerows(filas)
        print(json.dumps(resumen, ensure_ascii=False))
    (salida / f"clasificador_{args.conjunto}.json").write_text(json.dumps(resumenes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if intento:
        intento.update(estado="completo", fin_utc=datetime.now(timezone.utc).isoformat())
        (salida / "intento.json").write_text(json.dumps(intento, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
