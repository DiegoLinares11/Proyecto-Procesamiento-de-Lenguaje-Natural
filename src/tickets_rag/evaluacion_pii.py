"""Métricas de PII por entidad exacta sobre un holdout fijado antes del NER.

Este módulo no carga Presidio, spaCy, un LLM ni una base de datos. Los diagnósticos
contienen exclusivamente tipos e intervalos; nunca el valor de una entidad.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

TIPOS = ("PERSON", "EMAIL", "PHONE", "DPI", "CARD")
VERSION_BANCO = "1.0"
SHA256_BANCO = "bb5280953bece83a5861ea873f5424c8d94ea25594aeeed555525c74548d6d06"
META_RECALL = 0.95


def sha256_archivo(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _intervalo_valido(inicio: Any, fin: Any, longitud: int) -> bool:
    return type(inicio) is int and type(fin) is int and 0 <= inicio < fin <= longitud


def _solapan(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return max(a[0], b[0]) < min(a[1], b[1])


def validar_caso(caso: dict) -> None:
    """Rechaza anotaciones ambiguas antes de puntuar, sin incluir sus valores."""
    if not isinstance(caso, dict) or not isinstance(caso.get("id"), str):
        raise ValueError("Caso sin identificador válido")
    texto = caso.get("texto")
    entidades = caso.get("entidades")
    negativos = caso.get("negativos", [])
    if not isinstance(texto, str) or not isinstance(entidades, list) or not isinstance(negativos, list):
        raise ValueError("Texto o anotaciones no válidos")
    intervalos: list[tuple[int, int]] = []
    for entidad in entidades:
        if not isinstance(entidad, dict) or entidad.get("tipo") not in TIPOS:
            raise ValueError("Tipo de entidad no válido")
        inicio, fin = entidad.get("inicio"), entidad.get("fin")
        if not _intervalo_valido(inicio, fin, len(texto)):
            raise ValueError("Intervalo de entidad no válido")
        if any(_solapan((inicio, fin), otro) for otro in intervalos):
            raise ValueError("Entidades duplicadas o solapadas en la referencia")
        intervalos.append((inicio, fin))
    for negativo in negativos:
        if not isinstance(negativo, dict):
            raise ValueError("Negativo no válido")
        inicio, fin = negativo.get("inicio"), negativo.get("fin")
        if not _intervalo_valido(inicio, fin, len(texto)):
            raise ValueError("Intervalo negativo no válido")
        if any(_solapan((inicio, fin), otro) for otro in intervalos):
            raise ValueError("Un negativo solapa una entidad de referencia")


def cargar_banco(ruta: Path) -> list[dict]:
    """Sólo acepta los bytes congelados de la versión 1.0, no una copia retocada."""
    contenido = ruta.read_bytes()
    if hashlib.sha256(contenido).hexdigest() != SHA256_BANCO:
        raise ValueError("El banco no coincide con el SHA-256 congelado")
    casos = [json.loads(linea) for linea in contenido.decode("utf-8").splitlines() if linea.strip()]
    if len(casos) != 30 or [c.get("id") for c in casos] != [f"PII-{i:02d}" for i in range(1, 31)]:
        raise ValueError("El banco debe contener los 30 casos ordenados")
    for caso in casos:
        validar_caso(caso)
        if caso.get("version") != VERSION_BANCO or caso.get("origen") != "sintetico_ia_seguridad":
            raise ValueError("Versión o procedencia del banco no válida")
        if not caso["entidades"]:
            raise ValueError("Todos los textos del holdout requieren PII sembrada")
    return casos


def _metricas(tp: int, fp: int, fn: int) -> dict:
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
    }


def _span(tipo: str, inicio: int | None, fin: int | None) -> dict:
    return {"tipo": tipo, "inicio": inicio, "fin": fin}


def _leer_deteccion(deteccion: Any, longitud: int) -> tuple[dict, bool]:
    if isinstance(deteccion, dict):
        tipo, inicio, fin = (deteccion.get(k) for k in ("tipo", "inicio", "fin"))
    else:
        tipo, inicio, fin = (getattr(deteccion, k, None) for k in ("tipo", "inicio", "fin"))
    # No copiar campos desconocidos ni valores desde el detector al reporte.
    tipo_valido = isinstance(tipo, str) and tipo in TIPOS
    intervalo_valido = _intervalo_valido(inicio, fin, longitud)
    return _span(
        tipo if tipo_valido else "DESCONOCIDO",
        inicio if type(inicio) is int else None,
        fin if type(fin) is int else None,
    ), tipo_valido and intervalo_valido


def evaluar_caso(caso: dict, detecciones: list, texto_redactado: str, conteos: dict) -> dict:
    """Evalúa asignación exacta 1:1 y verifica que el enmascarado sea fiel.

    Los duplicados cuentan como FP. Un tipo o intervalo inválido también cuenta
    como FP y nunca puede acreditar redacción efectiva.
    """
    validar_caso(caso)
    if not isinstance(detecciones, list):
        raise ValueError("El detector debe devolver una lista")
    texto = caso["texto"]
    pendientes = Counter((e["tipo"], e["inicio"], e["fin"]) for e in caso["entidades"])
    aciertos: list[dict] = []
    falsos_positivos: list[dict] = []
    predicciones: list[dict] = []
    invalidas = 0
    for deteccion in detecciones:
        span, valido = _leer_deteccion(deteccion, len(texto))
        predicciones.append(span)
        clave = (span["tipo"], span["inicio"], span["fin"])
        if valido and pendientes[clave] > 0:
            pendientes[clave] -= 1
            aciertos.append(span)
        else:
            falsos_positivos.append(span)
        invalidas += not valido
    falsos_negativos = [_span(*clave) for clave, n in pendientes.items() for _ in range(n)]

    errores_redaccion: list[str] = []
    ordenadas = sorted(
        (p for p in predicciones if _intervalo_valido(p["inicio"], p["fin"], len(texto))),
        key=lambda p: (p["inicio"], p["fin"]),
    )
    solapadas = any(a["fin"] > b["inicio"] for a, b in zip(ordenadas, ordenadas[1:]))
    if invalidas:
        errores_redaccion.append("detecciones_invalidas")
    if solapadas:
        errores_redaccion.append("detecciones_duplicadas_o_solapadas")
    conteos_esperados = dict(Counter(p["tipo"] for p in predicciones))
    conteos_validos = isinstance(conteos, dict) and all(
        k in TIPOS and type(v) is int and v > 0 for k, v in conteos.items()
    )
    if not conteos_validos or conteos != conteos_esperados:
        errores_redaccion.append("conteos_inconsistentes")
    if not invalidas and not solapadas:
        partes: list[str] = []
        cursor = 0
        for p in ordenadas:
            partes.extend((texto[cursor:p["inicio"]], f"[{p['tipo']}_REDACTED]"))
            cursor = p["fin"]
        partes.append(texto[cursor:])
        if not isinstance(texto_redactado, str) or texto_redactado != "".join(partes):
            errores_redaccion.append("texto_no_coincide_con_sustituciones")

    negativas = caso.get("negativos", [])
    negativos_afectados = {
        i for i, negativo in enumerate(negativas)
        if any(
            _intervalo_valido(p["inicio"], p["fin"], len(texto))
            and _solapan((p["inicio"], p["fin"]), (negativo["inicio"], negativo["fin"]))
            for p in predicciones
        )
    }
    detecciones_sobre_negativos = sum(
        _intervalo_valido(p["inicio"], p["fin"], len(texto))
        and any(_solapan((p["inicio"], p["fin"]), (n["inicio"], n["fin"])) for n in negativas)
        for p in predicciones
    )
    tipos_presentes = set(TIPOS) | {p["tipo"] for p in predicciones}
    por_tipo = {
        tipo: _metricas(
            sum(p["tipo"] == tipo for p in aciertos),
            sum(p["tipo"] == tipo for p in falsos_positivos),
            sum(p["tipo"] == tipo for p in falsos_negativos),
        ) for tipo in sorted(tipos_presentes)
    }
    n_referencia = len(caso["entidades"])
    efectiva = len(aciertos) if not errores_redaccion else 0
    return {
        "id": caso["id"],
        "categoria": caso.get("categoria"),
        "entidades_referencia": n_referencia,
        "detecciones": len(predicciones),
        "detecciones_invalidas": invalidas,
        "estricto": _metricas(len(aciertos), len(falsos_positivos), len(falsos_negativos)),
        "por_tipo": por_tipo,
        "redaccion": {
            "integra": not errores_redaccion,
            "errores": errores_redaccion,
            "entidades_efectivas": efectiva,
            "recall_efectivo": efectiva / n_referencia if n_referencia else None,
        },
        "negativos": {
            "fragmentos": len(negativas),
            "fragmentos_afectados": len(negativos_afectados),
            "detecciones_sobre_negativos": detecciones_sobre_negativos,
        },
        "coincidencias": aciertos,
        "falsos_positivos": falsos_positivos,
        "falsos_negativos": falsos_negativos,
    }


def resumir(resultados: list[dict]) -> dict:
    """Agrega micro métricas; nunca interpreta ausencias como un resultado perfecto."""
    estricto = _metricas(*(sum(r["estricto"][k] for r in resultados) for k in ("tp", "fp", "fn")))
    tipos = set(TIPOS) | {tipo for r in resultados for tipo in r["por_tipo"]}
    por_tipo = {}
    for tipo in sorted(tipos):
        por_tipo[tipo] = _metricas(*(
            sum(r["por_tipo"].get(tipo, {}).get(k, 0) for r in resultados) for k in ("tp", "fp", "fn")
        ))
        referencia_tipo = por_tipo[tipo]["tp"] + por_tipo[tipo]["fn"]
        efectivos_tipo = sum(
            r["por_tipo"].get(tipo, {}).get("tp", 0)
            for r in resultados if r["redaccion"]["integra"]
        )
        por_tipo[tipo]["entidades_efectivas"] = efectivos_tipo
        por_tipo[tipo]["recall_efectivo"] = efectivos_tipo / referencia_tipo if referencia_tipo else None
    n_referencia = sum(r["entidades_referencia"] for r in resultados)
    efectivas = sum(r["redaccion"]["entidades_efectivas"] for r in resultados)
    recall_efectivo = efectivas / n_referencia if n_referencia else None
    integras = sum(r["redaccion"]["integra"] for r in resultados)
    cumple = bool(resultados) and (
        estricto["recall"] is not None and estricto["recall"] >= META_RECALL
        and recall_efectivo is not None and recall_efectivo >= META_RECALL
        and integras == len(resultados)
    )
    return {
        "textos_evaluados": len(resultados),
        "entidades_referencia": n_referencia,
        "estricto": estricto,
        "por_tipo": por_tipo,
        "redaccion": {
            "textos_integros": integras,
            "textos_no_integros": len(resultados) - integras,
            "entidades_efectivas": efectivas,
            "recall_efectivo": recall_efectivo,
        },
        "negativos": {
            k: sum(r["negativos"][k] for r in resultados)
            for k in ("fragmentos", "fragmentos_afectados", "detecciones_sobre_negativos")
        },
        "meta_recall": META_RECALL,
        "cumple_meta": cumple,
    }
