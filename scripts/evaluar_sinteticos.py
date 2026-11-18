"""Compara TF-IDF y el clasificador LLM con 20 casos SINTÉTICOS de IA, nunca humanos.

--solo-validar no carga NER, clasificadores ni sesión. Una corrida real consume cuota incluida.
La variante se fija antes de medir: cinco votos, juegos distintos y criterios extra, esfuerzo low.
Los tickets completados no se repiten al reanudar el mismo UUID y las mismas huellas.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import tempfile
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tickets_rag import config
from tickets_rag.tickets_manuales import CATEGORIAS, PRIORIDADES, cargar_referencias, normalizar_texto

CONJUNTO = config.EVALUACION / "tickets_sinteticos/tickets.jsonl"
SALIDA = config.RESULTADOS_SUSCRIPCION / "clasificador_sinteticos"
IDS = tuple(f"SYN-{i:02d}" for i in range(1, 21))
TIPOS = ("procedimiento", "datos", "accion", "fuera_de_dominio")
VARIANTE = "juegos_criterios"
AJUSTES = {"corridas": 5, "juegos_distintos": True, "reglas_extra": True, "effort": "low"}
CODIGO = (
    "scripts/evaluar_sinteticos.py", "src/tickets_rag/clasificador.py",
    "src/tickets_rag/clasificador_llm.py", "src/tickets_rag/modelo.py", "src/tickets_rag/pii.py",
    "src/tickets_rag/ingesta.py", "src/tickets_rag/config.py", "uv.lock",
    "src/tickets_rag/historial.py", "src/tickets_rag/f3.py", "src/tickets_rag/tickets_manuales.py",
)


class ErrorSinteticos(ValueError):
    """Mensaje fijo, sin incluir textos de tickets, credenciales o excepciones del proveedor."""


class Justificacion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    categoria: str = Field(min_length=10, max_length=600)
    prioridad: str = Field(min_length=10, max_length=600)
    tipo: str = Field(min_length=10, max_length=600)


class Caso(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ticket_id: str = Field(pattern=r"^SYN-(?:0[1-9]|1[0-9]|20)$")
    texto: str = Field(min_length=20, max_length=8000)
    categoria: Literal["ACCESO", "CORREO", "EQUIPOS", "RED", "APLICACIONES", "OTRO"]
    prioridad: Literal["ALTA", "MEDIA", "BAJA"]
    tipo: Literal["procedimiento", "datos", "accion", "fuera_de_dominio"]
    justificacion: Justificacion
    procedencia: Literal["sintetico_ia"]
    uso: Literal["evaluacion_tecnica_reservada"]


def sha(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def canonico(datos) -> bytes:
    return json.dumps(datos, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def cargar_conjunto(ruta: Path = CONJUNTO, *, raiz: Path = config.RAIZ) -> tuple[list[dict], dict]:
    """Solo lecturas: etiquetas, hashes, procedencia IA y duplicados exactos normalizados."""
    try:
        raw = ruta.read_bytes()
        casos = [Caso.model_validate_json(l).model_dump() for l in raw.splitlines() if l.strip()]
        meta = json.loads((ruta.parent / "manifiesto.json").read_bytes())
        referencias, fuentes = cargar_referencias(raiz)
        textos = [normalizar_texto(c["texto"]) for c in casos]
        balance = {k: dict(Counter(c[k] for c in casos)) for k in ("categoria", "prioridad", "tipo")}
        autoria = meta["autoria"]
        if (len(casos) != 20 or {c["ticket_id"] for c in casos} != set(IDS) or len(set(textos)) != 20
                or any(t in r for t in textos for r in referencias.values())
                or type(meta["version"]) is not int or meta["version"] != 1
                or meta["conjunto"] != "tickets_sinteticos_ia" or meta["estado"] != "congelado_sintetico"
                or meta["tickets"] != 20 or meta["cumple_requisito_20_humanos"] is not False
                or autoria["tipo"] != "IA" or autoria["persona_autora"] is not None
                or not autoria["modelo_redactor"] or autoria["revision_humana"] != "pendiente"
                or meta["uso_permitido"] != "evaluacion_tecnica_reservada"
                or not {"entrenamiento", "ejemplos_few_shot", "ajuste_prompt", "indice", "seleccion_variantes",
                        "acreditacion_20_tickets_humanos"}.issubset(meta["excluido_de"])
                or meta["artefactos_sha256"] != {"tickets.jsonl": sha(raw)}
                or meta["fuentes_referencia"] != fuentes or meta["balance"] != balance
                or meta["chunks_sha256"] != sha((raiz / "indices/chunks.jsonl").read_bytes())
                or date.fromisoformat(meta["fecha_redaccion"]).isoformat() != meta["fecha_redaccion"]
                or date.fromisoformat(meta["fecha_redaccion"]) > date.today()
                or set(balance["categoria"]) != set(CATEGORIAS) or set(balance["prioridad"]) != set(PRIORIDADES)):
            raise ValueError
        return sorted(casos, key=lambda c: c["ticket_id"]), meta
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise ErrorSinteticos("El conjunto sintético no superó la validación de formato, procedencia o integridad.") from None


def predicciones_tfidf(casos: list[dict], entrenamiento: list[dict]) -> dict:
    from tickets_rag.clasificador import construir, preparar
    textos_entrenamiento = [preparar(t["texto"]) for t in entrenamiento]
    textos_casos = [preparar(t["texto"]) for t in casos]
    predicciones = {c["ticket_id"]: {} for c in casos}
    for campo in ("categoria", "prioridad"):
        modelo = construir().fit(textos_entrenamiento, [t[campo] for t in entrenamiento])
        for caso, valor in zip(casos, modelo.predict(textos_casos), strict=True):
            predicciones[caso["ticket_id"]][campo] = str(valor)
    return predicciones


def crear_clasificador(modelo: str):
    from tickets_rag.clasificador_llm import ClasificadorLLM
    return ClasificadorLLM(modelo=modelo, **AJUSTES)


def _validar_tfidf(predicciones: dict, casos: list[dict]) -> None:
    if (not isinstance(predicciones, dict) or set(predicciones) != {c["ticket_id"] for c in casos}
            or any(not isinstance(v, dict) or set(v) != {"categoria", "prioridad"}
                   or v["categoria"] not in CATEGORIAS or v["prioridad"] not in PRIORIDADES
                   for v in predicciones.values())):
        raise ErrorSinteticos("La línea base no devolvió exactamente una categoría y prioridad válidas por ticket.")


def _plan(ruta: Path, meta: dict, casos: list[dict]) -> dict:
    from tickets_rag.clasificador_llm import (
        EJEMPLOS_POR_CATEGORIA, REGLAS_EXTRA, SEMILLA_DESARROLLO, SEMILLA_EJEMPLOS, TIPOS as REGLAS_TIPO,
    )
    return {"conjunto": "tickets_sinteticos_ia", "variante": VARIANTE, "ajustes": AJUSTES,
            "modelo": config.MODELO_CLASIFICADOR, "proveedor": "codex_subscription", "autenticacion": "chatgpt",
            "juegos": list(range(AJUSTES["corridas"])), "semilla_ejemplos": SEMILLA_EJEMPLOS,
            "semilla_desarrollo": SEMILLA_DESARROLLO, "ejemplos_por_categoria": EJEMPLOS_POR_CATEGORIA,
            "criterios": "REGLAS_EXTRA y manual vigente 1.3/1.4, fijados antes de medir",
            "reglas_extra_sha256": sha(REGLAS_EXTRA.encode()), "reglas_tipo_sha256": sha(REGLAS_TIPO.encode()),
            "confianza_minima": config.CONFIANZA_MINIMA,
            "timeout_modelo_s": config.TIMEOUT_MODELO_S,
            "reintentos_modelo_python": config.REINTENTOS_MODELO,
            "umbral_cuota_porcentaje": 80,
            "tickets_sha256": sha(ruta.read_bytes()), "manifiesto_sha256": sha((ruta.parent / "manifiesto.json").read_bytes()),
            "referencias": meta["fuentes_referencia"], "chunks_sha256": meta["chunks_sha256"],
            "orden": [c["ticket_id"] for c in casos],
            "codigo_sha256": {n: sha((config.RAIZ / n).read_bytes()) for n in CODIGO},
            "versiones": {n: importlib.metadata.version(n) for n in ("scikit-learn", "numpy", "pydantic")}}


def _json_atomico(ruta: Path, datos: dict) -> None:
    fd, nombre = tempfile.mkstemp(prefix=".estado-", dir=ruta.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps(datos, ensure_ascii=False, indent=2, allow_nan=False).encode() + b"\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(nombre, ruta)
    finally:
        Path(nombre).unlink(missing_ok=True)


@contextmanager
def _bloquear(carpeta: Path):
    fd = os.open(carpeta / ".corrida.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            if os.name == "nt":
                import msvcrt
                if not os.fstat(fd).st_size:
                    os.write(fd, b"0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ErrorSinteticos("Otra instancia está usando este UUID; no se iniciaron inferencias.") from None
        yield
    finally:
        os.close(fd)


def _resultado(valor: dict) -> dict:
    from tickets_rag.clasificador_llm import ResultadoClasificacion
    r = ResultadoClasificacion.model_validate(valor, strict=True).model_dump()
    if (r["categoria"] not in CATEGORIAS or r["prioridad"] not in PRIORIDADES or r["tipo"] not in TIPOS
            or r["proveedor"] != "codex_subscription" or r["modo_autenticacion"] != "chatgpt"
            or not 1 <= r["corridas_validas"] <= 5 or r["tokens_entrada"] < 0 or r["tokens_salida"] < 0
            or r["costo_usd"] != 0 or r["costo_api_usd"] != 0
            or set(r["confianza"]) != {"categoria", "prioridad", "tipo"}
            or any(not math.isfinite(v) or not 0 <= v <= 1 for v in r["confianza"].values())):
        raise ErrorSinteticos("El clasificador devolvió un resultado incompatible con el contrato de esta corrida.")
    return r


def _leer_parciales(carpeta: Path, registro: dict, casos: list[dict]) -> tuple[list[dict], str | None, dict]:
    ruta = carpeta / "mediciones_parciales.jsonl"
    filas, pendiente, intentos = [], None, {}
    try:
        for linea in ruta.read_text().splitlines() if ruta.exists() else []:
            e = json.loads(linea)
            i = e["ticket_id"]
            if (e["corrida_id"] != registro["corrida_id"] or e["plan_sha256"] != registro["plan_sha256"]
                    or i != casos[len(filas)]["ticket_id"] or type(e["intento"]) is not int):
                raise ValueError
            if e["evento"] == "inicio":
                if e["intento"] != intentos.get(i, 0) + 1:
                    raise ValueError
                intentos[i], pendiente = e["intento"], i
            elif e["evento"] == "resultado" and pendiente == i and e["intento"] == intentos[i]:
                r = _resultado(e["llm"])
                if (e["tfidf"] != registro["tfidf"][i] or not math.isfinite(e["latencia_llm_s"])
                        or e["latencia_llm_s"] < 0):
                    raise ValueError
                filas.append({"ticket_id": i, "llm": r, "tfidf": e["tfidf"], "latencia_llm_s": e["latencia_llm_s"]})
                pendiente = None
            elif e["evento"] != "error" or pendiente != i or e["intento"] != intentos[i]:
                raise ValueError
        return filas, pendiente, intentos
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise ErrorSinteticos("Los parciales no son íntegros o no corresponden a este UUID y plan; no se repitió ningún ticket.") from None


def _evento(carpeta: Path, registro: dict, ticket_id: str, intento: int, evento: str, **datos) -> None:
    fila = {"corrida_id": registro["corrida_id"], "plan_sha256": registro["plan_sha256"],
            "ticket_id": ticket_id, "intento": intento, "evento": evento, "fecha_utc": ahora(), **datos}
    fd = os.open(carpeta / "mediciones_parciales.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "ab") as f:
        f.write(canonico(fila) + b"\n")
        f.flush()
        os.fsync(f.fileno())


def resumir(casos: list[dict], filas: list[dict], registro: dict) -> dict:
    from sklearn.metrics import f1_score
    reales = {c["ticket_id"]: c for c in casos}
    metricas = None
    if filas:
        metricas = {s: {campo: round(float(f1_score(
            [reales[f["ticket_id"]][campo] for f in filas], [f[s][campo] for f in filas],
            labels=list(etiquetas), average="macro", zero_division=0)), 6)
            for campo, etiquetas in (("categoria", CATEGORIAS), ("prioridad", PRIORIDADES))} for s in ("tfidf", "llm")}
    return {"corrida_id": registro["corrida_id"], "plan_sha256": registro["plan_sha256"],
            "conjunto": "tickets_sinteticos_ia", "autoria": "IA", "cumple_requisito_20_humanos": False,
            "alcance": "evaluacion_tecnica_sintetica; no sustituye medicion humana ni representa poblacion real",
            "estado": "completo" if len(filas) == len(casos) else "incompleto", "tickets_objetivo": len(casos),
            "tickets_medidos": len(filas), "metricas_parciales": len(filas) != len(casos),
            "macro_f1": metricas, "modelo": registro["plan"]["modelo"], "variante": VARIANTE,
            "configuracion": registro["plan"]["ajustes"], "proveedor": "codex_subscription",
            "tokens_entrada_tickets_completos": sum(f["llm"]["tokens_entrada"] for f in filas),
            "tokens_salida_tickets_completos": sum(f["llm"]["tokens_salida"] for f in filas),
            "latencia_llm_tickets_completos_s": round(sum(f["latencia_llm_s"] for f in filas), 3),
            "costo_api_usd_tickets_completos": sum(f["llm"]["costo_api_usd"] for f in filas),
            "costo_medido": "API incremental; no incluye precio del plan. Consume cuota de ChatGPT/Codex.",
            "uso_de_intentos_incompletos": "no cuantificado; un intento interrumpido puede haber consumido cuota",
            "errores": [{"ticket_id": f["ticket_id"], "campo": campo, "sistema": s,
                         "esperado": reales[f["ticket_id"]][campo], "observado": f[s][campo]}
                        for f in filas for s in ("tfidf", "llm") for campo in ("categoria", "prioridad")
                        if f[s][campo] != reales[f["ticket_id"]][campo]]}


def ejecutar(*, ruta: Path = CONJUNTO, salida_base: Path = SALIDA, reanudar: str | None = None,
             reintentar_pendiente: bool = False, raiz: Path = config.RAIZ, al_reservar=None) -> tuple[dict, Path]:
    if reintentar_pendiente and not reanudar:
        raise ErrorSinteticos("Reintentar un pendiente requiere el UUID de una corrida anterior.")
    casos, meta = cargar_conjunto(ruta, raiz=raiz)
    plan = _plan(ruta, meta, casos)
    plan_hash = sha(canonico(plan))
    try:
        corrida_id = str(uuid.UUID(reanudar)) if reanudar else str(uuid.uuid4())
        if reanudar and corrida_id != reanudar:
            raise ValueError
    except (ValueError, AttributeError):
        raise ErrorSinteticos("El identificador de reanudación debe ser el UUID canónico de la corrida.") from None
    carpeta = salida_base / corrida_id
    if reanudar:
        if not carpeta.is_dir():
            raise ErrorSinteticos("No existe una corrida con ese UUID.")
    else:
        carpeta.mkdir(parents=True, mode=0o700, exist_ok=False)
    with _bloquear(carpeta):
        if reanudar:
            try:
                registro = json.loads((carpeta / "corrida.json").read_bytes())
                if (registro["corrida_id"] != corrida_id or registro["plan_sha256"] != plan_hash
                        or registro["plan"] != plan or sha(canonico(registro["tfidf"])) != registro["tfidf_sha256"]):
                    raise ValueError
                _validar_tfidf(registro["tfidf"], casos)
            except (OSError, ValueError, TypeError, KeyError):
                raise ErrorSinteticos("Cambió el conjunto, código, referencias, modelo o configuración; no se puede reanudar este UUID.") from None
        else:
            entrenamiento = [t for l in (raiz / "datos/f3_tickets/tickets.jsonl").read_text().splitlines()
                             if l.strip() and (t := json.loads(l))["particion"] == "indice"]
            tfidf = predicciones_tfidf(casos, entrenamiento)
            _validar_tfidf(tfidf, casos)
            registro = {"version": 1, "corrida_id": corrida_id, "plan": plan, "plan_sha256": plan_hash,
                        "estado": "iniciado", "inicio_utc": ahora(), "entrenamiento_tfidf": len(entrenamiento),
                        "entrenamiento": "solo F3 particion indice; sintéticos excluidos",
                        "tfidf": tfidf, "tfidf_sha256": sha(canonico(tfidf))}
            _json_atomico(carpeta / "corrida.json", registro)
        if al_reservar:
            al_reservar({"evento": "corrida", "corrida_id": corrida_id, "salida": str(carpeta)})
        filas, pendiente, intentos = _leer_parciales(carpeta, registro, casos)
        if pendiente and not reintentar_pendiente:
            raise ErrorSinteticos("Hay un ticket iniciado sin resultado. Revise los parciales y use --reintentar-pendiente si acepta repetir ese intento, que puede haber consumido cuota.")
        if len(filas) < len(casos):
            try:
                clasificador = crear_clasificador(plan["modelo"])
            except Exception:
                registro.update(estado="incompleto", ultimo_error={"codigo": "preparacion_local"}, actualizado_utc=ahora())
                _json_atomico(carpeta / "corrida.json", registro)
                _json_atomico(carpeta / "resumen.json", resumir(casos, filas, registro))
                raise ErrorSinteticos("Falló la preparación local del clasificador; se conservaron UUID y parciales y no se inició el siguiente ticket.") from None
            prompts = [sha(s.encode()) for s in clasificador.sistemas]
            if len(prompts) != 5 or ("sistemas_sha256" in registro and registro["sistemas_sha256"] != prompts):
                raise ErrorSinteticos("Los juegos del prompt cambiaron; no se iniciaron nuevas inferencias.")
            registro["sistemas_sha256"] = prompts
            registro["estado"] = "en_curso"
            _json_atomico(carpeta / "corrida.json", registro)
            for ticket in casos[len(filas):]:
                i = ticket["ticket_id"]
                intento = intentos.get(i, 0) + 1
                _evento(carpeta, registro, i, intento, "inicio")
                try:
                    inicio = time.perf_counter()
                    r = _resultado(clasificador.clasificar(ticket["texto"]).model_dump())
                    segundos = time.perf_counter() - inicio
                except Exception as error:
                    codigo = getattr(error, "codigo", "clasificacion_incompleta")
                    if codigo not in {"autenticacion", "cuota", "formato", "timeout", "transporte", "configuracion", "herramienta_no_permitida"}:
                        codigo = "clasificacion_incompleta"
                    _evento(carpeta, registro, i, intento, "error", codigo=codigo)
                    registro.update(estado="incompleto", ultimo_error={"ticket_id": i, "codigo": codigo}, actualizado_utc=ahora())
                    _json_atomico(carpeta / "corrida.json", registro)
                    _json_atomico(carpeta / "resumen.json", resumir(casos, filas, registro))
                    raise ErrorSinteticos("La corrida quedó incompleta. Se conservaron el UUID y los parciales; no se iniciaron los tickets siguientes.") from None
                fila = {"ticket_id": i, "llm": r, "tfidf": registro["tfidf"][i], "latencia_llm_s": segundos}
                _evento(carpeta, registro, i, intento, "resultado", **{k: v for k, v in fila.items() if k != "ticket_id"})
                filas.append(fila)
                _json_atomico(carpeta / "resumen.json", resumir(casos, filas, registro))
        resumen = resumir(casos, filas, registro)
        registro.update(estado="completo", fin_utc=ahora())
        registro.pop("ultimo_error", None)  # La incidencia histórica permanece en el JSONL, no como error activo.
        _json_atomico(carpeta / "corrida.json", registro)
        _json_atomico(carpeta / "resumen.json", resumen)
        return resumen, carpeta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tickets", type=Path, default=CONJUNTO)
    parser.add_argument("--salida-base", type=Path, default=SALIDA)
    parser.add_argument("--solo-validar", action="store_true", help="sin NER, clasificadores, API ni cuota")
    parser.add_argument("--reanudar", help="UUID de una corrida existente; exige idénticas huellas y configuración")
    parser.add_argument("--reintentar-pendiente", action="store_true", help="acepta repetir solo el ticket sin resultado; puede haber consumido cuota")
    args = parser.parse_args()
    if args.reintentar_pendiente and not args.reanudar:
        parser.error("--reintentar-pendiente requiere --reanudar")
    if args.solo_validar and (args.reanudar or args.reintentar_pendiente):
        parser.error("--solo-validar no modifica ni reanuda corridas")
    try:
        if args.solo_validar:
            casos, meta = cargar_conjunto(args.tickets)
            print(json.dumps({"conjunto": "tickets_sinteticos_ia", "tickets": len(casos), "balance": meta["balance"],
                              "cumple_requisito_20_humanos": False, "inferencias_ejecutadas": 0,
                              "metricas": None}, ensure_ascii=False))
            return
        resumen, carpeta = ejecutar(ruta=args.tickets, salida_base=args.salida_base,
                                    reanudar=args.reanudar, reintentar_pendiente=args.reintentar_pendiente,
                                    al_reservar=lambda e: print(json.dumps(e, ensure_ascii=False), flush=True))
        print(json.dumps({"salida": str(carpeta), **resumen}, ensure_ascii=False))
    except ErrorSinteticos as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
