"""Validación offline del banco congelado y su procedencia; no ejecuta el sistema."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from tickets_rag import config
from tickets_rag.banco import BANCO_OFICIAL, Caso, cargar_banco, composicion

HERRAMIENTAS = {"classify", "search_docs", "buscar_casos_similares", "query_tickets", "take_action", "escalate"}
CONSULTAS = {"estado_ticket", "conteo_por_categoria", "tiempo_resolucion", "tickets_por_procedimiento", "escalados"}
IDS = {f"{prefijo}{i:02d}" for prefijo, total in (("R", 20), ("H", 10), ("A", 12)) for i in range(1, total + 1)}


def sha256_archivo(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def sha256_json(datos) -> str:
    return hashlib.sha256(json.dumps(datos, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def normalizar_pregunta(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.casefold())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(re.findall(r"\w+", texto))


def validar_contenido(casos: list[Caso], chunks: list[dict], referencias: list[str]) -> dict:
    """Verifica contratos y fuentes. No certifica semántica ni independencia humana."""
    if len(casos) != 42 or {c.id for c in casos} != IDS:
        raise ValueError("Se requieren exactamente los 42 identificadores R01–R20, H01–H10 y A01–A12")
    if any(n != esperado for tipos in composicion(casos).values() for n, esperado in tipos.values()):
        raise ValueError("La composición no coincide con el anteproyecto")
    if any(c.borrador for c in casos):
        raise ValueError("El banco revisado todavía contiene marcas de borrador")
    preguntas = [normalizar_pregunta(c.question) for c in casos]
    if len(set(preguntas)) != 42:
        raise ValueError("Hay preguntas duplicadas tras normalizar mayúsculas, tildes y puntuación")
    previas = {normalizar_pregunta(t) for t in referencias}
    if any(p in previas for p in preguntas):
        raise ValueError("Se repite literalmente una pregunta del borrador, desarrollo o F3")
    unidades: dict[str, list[dict]] = {}
    for chunk in chunks:
        unidades.setdefault(chunk["unidad"], []).append(chunk)
    for caso in casos:
        prefijo = f"{caso.id}: "
        if not caso.expected_behavior.strip():
            raise ValueError(prefijo + "falta el comportamiento esperado")
        if not caso.answerable and "abstiene" not in caso.criterio:
            raise ValueError(prefijo + "falta comprobar abstención en un caso sin respuesta")
        if caso.grupo == "rag" and caso.answerable and (not caso.hechos or not caso.unidades):
            raise ValueError(prefijo + "faltan hechos o evidencia RAG")
        if not caso.answerable and caso.expected_sources:
            raise ValueError(prefijo + "un caso sin respuesta no debe atribuir fuentes esperadas")
        if set(caso.herramientas_esperadas) & set(caso.herramientas_prohibidas):
            raise ValueError(prefijo + "una herramienta está exigida y prohibida")
        if (set(caso.herramientas_esperadas) | set(caso.herramientas_prohibidas)) - HERRAMIENTAS:
            raise ValueError(prefijo + "herramienta desconocida")
        if {normalizar_pregunta(t) for t in caso.hechos} & {normalizar_pregunta(t) for t in caso.hechos_incorrectos}:
            raise ValueError(prefijo + "un hecho está exigido y prohibido")
        if len({f.unidad for f in caso.expected_sources}) != len(caso.expected_sources):
            raise ValueError(prefijo + "fuente esperada repetida")
        paginas = set()
        paginas_inicio_f1 = set()
        for fuente in caso.expected_sources:
            if fuente.unidad.startswith("SQL:"):
                if (fuente.unidad[4:] not in CONSULTAS or fuente.doc_id != "tickets"
                        or fuente.source != "Historial de tickets (PostgreSQL)" or fuente.seccion != fuente.unidad[4:]):
                    raise ValueError(prefijo + "referencia SQL fuera del catálogo")
                continue
            fragmentos = unidades.get(fuente.unidad)
            if not fragmentos:
                raise ValueError(prefijo + "unidad esperada ausente del índice")
            if any(c["source"] != fuente.source or c["doc_id"] != fuente.doc_id for c in fragmentos):
                raise ValueError(prefijo + "documento o nombre de fuente incorrecto")
            if fuente.unidad.startswith("F1") and any(c["seccion"] != fuente.seccion for c in fragmentos):
                raise ValueError(prefijo + "sección F1 incorrecta")
            if not any(caso.rol in c["roles_permitidos"] for c in fragmentos):
                raise ValueError(prefijo + "la evidencia esperada no está autorizada para el rol")
            for c in fragmentos:
                paginas.update(range(c["page"], c.get("page_end", c["page"]) + 1))
                if fuente.unidad.startswith("F1"):
                    paginas_inicio_f1.add(c["page"])
        esperadas = set(caso.expected_pages)
        if len(esperadas) != len(caso.expected_pages) or any(p < 1 for p in esperadas):
            raise ValueError(prefijo + "páginas inválidas o repetidas")
        if not paginas_inicio_f1 <= esperadas or not esperadas <= paginas:
            raise ValueError(prefijo + "páginas esperadas no corresponden a la evidencia")
        if caso.unidades and not esperadas:
            raise ValueError(prefijo + "faltan páginas de evidencia documental")
    return {"casos": len(casos), "grupos": dict(Counter(c.grupo for c in casos)),
            "composicion": composicion(casos), "duplicados_exactos_normalizados": 0,
            "fuentes_roles_paginas": "validos", "oraculos_semanticos": "revision_documentada_no_certificacion_automatica"}


def validar_oficial(banco: Path = BANCO_OFICIAL, *, manifiesto: Path | None = None,
                    raiz: Path = config.RAIZ, chunks: list[dict] | None = None) -> dict:
    manifiesto = manifiesto or banco.with_suffix(".manifiesto.json")
    meta = json.loads(manifiesto.read_text(encoding="utf-8"))
    if meta.get("version_formato") != 1 or meta.get("banco", {}).get("archivo") != banco.name:
        raise ValueError("Manifiesto del banco incompatible")
    if meta["banco"]["sha256"] != sha256_archivo(banco):
        raise ValueError("El banco cambió después de su congelación")
    necesarias = {"evaluacion/banco_borrador.jsonl", "evaluacion/validacion_dev.jsonl",
                  "datos/f3_tickets/tickets.jsonl", "datos/manifiesto.json", "datos/f1_manual/manual_mesa_ayuda.md"}
    corpus = json.loads((raiz / "datos/manifiesto.json").read_text(encoding="utf-8"))
    necesarias.update(d["ruta"] for d in corpus["documentos"])
    if not necesarias <= set(meta["referencias_sha256"]):
        raise ValueError("Faltan hashes de fuentes necesarias para la congelación")
    for relativo, esperado in meta["referencias_sha256"].items():
        ruta = (raiz / relativo).resolve()
        if not ruta.is_relative_to(raiz.resolve()) or sha256_archivo(ruta) != esperado:
            raise ValueError("Cambió una fuente de referencia del banco congelado")
    revision = (raiz / meta["revision_casos"]["archivo"]).resolve()
    if not revision.is_relative_to(raiz.resolve()) or sha256_archivo(revision) != meta["revision_casos"]["sha256"]:
        raise ValueError("El registro de revisión no coincide con el banco congelado")
    if chunks is None:
        chunks = [json.loads(l) for l in (raiz / "indices/chunks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if meta["indice"]["sha256_json_canonico"] != sha256_json(chunks):
        raise ValueError("El índice no coincide con el snapshot de validación del banco")
    referencias = []
    for nombre, campo in (("evaluacion/banco_borrador.jsonl", "question"),
                          ("evaluacion/validacion_dev.jsonl", "question"),
                          ("datos/f3_tickets/tickets.jsonl", "texto")):
        referencias.extend(json.loads(l)[campo] for l in (raiz / nombre).read_text(encoding="utf-8").splitlines() if l.strip())
    casos = cargar_banco(banco)
    resumen = validar_contenido(casos, chunks, referencias)
    revisiones = json.loads(revision.read_text(encoding="utf-8"))
    if len(revisiones) != 42 or {r["id"] for r in revisiones} != IDS:
        raise ValueError("El registro de revisión no cubre los 42 casos")
    return {"estado": "valido_tecnicamente", "version_banco": meta["version_banco"],
            "sha256_banco": meta["banco"]["sha256"], "procedencia": meta["autoria"],
            "revision_humana": meta["revision_humana"], "inferencias_ejecutadas": 0,
            "mide_desempeno": False, **resumen}
