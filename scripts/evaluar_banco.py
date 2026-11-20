"""Corre el banco congelado contra los tres sistemas (fase 6 del plan de cierre).

Uso:
    docker compose up -d
    uv run python scripts/evaluar_banco.py                       # banco oficial, los tres sistemas, con juez y Ragas
    uv run python scripts/evaluar_banco.py --banco evaluacion/banco_borrador.jsonl   # exploración con el borrador
    uv run python scripts/evaluar_banco.py --casos R01,H07 --sin-juez       # prueba rápida, sin juez ni Ragas
    uv run python scripts/evaluar_banco.py --juez-en agente                 # juez y Ragas solo para el agente

Sistemas:
    agente      el grafo completo (router, herramientas, guardrails, aprobación humana): los 42 casos
    rag         búsqueda híbrida + reranker + τ y una sola llamada al generador: casos de RAG y de alucinación
    linea_base  BM25 sobre el manual y una sola llamada: los mismos casos que rag

Las fallas de los casos de "servicio caído" e inyección indirecta se simulan aquí: base vectorial caída,
API del generador caída y un fragmento envenenado. El checkpointer es en memoria, para no llenar la base
de hilos de evaluación. Necesita Codex autenticado con ChatGPT y cuota incluida verificable.

Escribe en resultados/codex_suscripcion/evaluacion/<banco>/, conservando los resultados históricos.
Con --casos escribe en su subcarpeta parcial/, sin pisar la corrida completa.
Use --reanudar con las mismas opciones para continuar un primer intento compatible.
El journal privado .progreso/ conserva resultados estructurados sin prompts/auth/stdout.
Una llamada enviada sin resultado o una aprobación SQL ambigua no se vuelve a ejecutar.
Las latencias acumulan tiempo activo por caso, excluyendo carga local y espera entre sesiones.
"""

from __future__ import annotations

import argparse
import copy
import gc
import importlib.metadata
import hashlib
import platform
import sys
import subprocess
import dataclasses
import json
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import psycopg
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from tickets_rag import config, vectores
from tickets_rag import herramientas as H
from tickets_rag.banco import BANCO_OFICIAL, METAS, Caso, calificar, cargar_banco, composicion, guardar_jsonl
from tickets_rag.banco_revision import sha256_archivo, validar_oficial
from tickets_rag.contrato import Respuesta
from tickets_rag.fallas import contexto_de_falla, grafo_con_falla
from tickets_rag.grafo import cliente_api, resumen_costo
from tickets_rag.ingesta import cargar_chunks
from tickets_rag.metricas import precision_at_k, promedio, recall_at_k, reciprocal_rank
from tickets_rag.modelo import ErrorModelo
from tickets_rag.evaluacion_progreso import (ErrorProgreso, ProgresoEvaluacion, digest, error_seguro,
    escribir_atomico, escribir_bytes_atomico, evaluar_incremental, recursos_con_memoria)



# ---------------------------------------------------------------- sistema agente

def _contextos(mensajes: list[dict], notas_accion: list[str]) -> dict[str, str]:
    """Todo lo que el agente leyó de sus herramientas, más las notas de la decisión de N2 que el grafo
    agrega a la respuesta. Sin los resultados de take_action y escalate, Ragas marcaba como no sustentado
    «la solicitud 47 quedó pendiente», aunque lo dijo la herramienta."""
    vistos: dict[str, str] = {}
    for m in mensajes or []:
        if m["role"] != "user" or not isinstance(m["content"], list):
            continue
        for b in m["content"]:
            if b.get("type") != "tool_result":
                continue
            try:
                datos = json.loads(b["content"])
            except (TypeError, ValueError):
                vistos[f"resultado-{len(vistos)}"] = str(b.get("content"))  # un error de herramienta también es contexto
                continue
            con_id = datos.get("fragmentos", []) + datos.get("casos", [])
            for f in con_id:
                vistos[f["chunk_id"]] = f["text"]
            if "id_cita" in datos:
                vistos[datos["id_cita"]] = json.dumps(datos.get("filas", []), ensure_ascii=False)
            elif not con_id:
                vistos[f"resultado-{len(vistos)}"] = json.dumps(datos, ensure_ascii=False)
    for i, nota in enumerate(notas_accion or []):
        vistos[f"nota-{i}"] = nota
    return vistos


def correr_agente(caso: Caso, recursos: H.Recursos, cliente, checkpointer, progreso=None) -> dict:
    grafo = grafo_con_falla(recursos, cliente, checkpointer, caso.falla)
    cfg = {"configurable": {"thread_id": f"eval-{caso.id}-{time.time_ns()}"}}
    pasos: list[tuple[str, float]] = []
    solicitudes_en_pausa = []

    def avanzar(entrada) -> None:
        marca = time.perf_counter()
        for evento in grafo.stream(entrada, cfg, stream_mode="updates"):
            ahora = time.perf_counter()
            pasos.extend((nodo, round(ahora - marca, 3)) for nodo in evento if nodo != "__interrupt__")
            marca = ahora

    def resultado() -> dict:
        if hasattr(cliente, "comprobar"):
            cliente.comprobar()
        v = grafo.get_state(cfg).values
        if v.get("error_modelo") in {"cuota", "autenticacion", "configuracion", "modelo"}:
            raise ErrorModelo(v["error_modelo"])
        traza = v.get("traza", [])
        busquedas = [t for t in traza if t.get("etapa") == "herramienta" and t.get("nombre") == "search_docs" and t.get("ok")]
        degradado = any(t.get("etapa") == "degradado" for t in traza) or any("degradada" in m for m in v.get("revision", []))
        return {
            "respuesta": v.get("respuesta"),
            "ruta": v.get("ruta"),
            "herramientas": list(dict.fromkeys(v.get("herramientas", []))),
            "revision": list(dict.fromkeys(v.get("revision", []))),
            "guardrail": (v.get("guardrail") or {}).get("decision"),
            "candidatos": [c["chunk_id"] for c in busquedas[0]["candidatos"]] if busquedas else [],
            "candidatos_todos": list(dict.fromkeys(c["chunk_id"] for b in busquedas for c in b["candidatos"])),
            "en_pausa_al_final": bool(grafo.get_state(cfg).next),
            "solicitudes_en_pausa": solicitudes_en_pausa,
            "solicitudes": list(v.get("solicitudes") or []),
            "degradado": degradado,
            "contextos": _contextos(v.get("mensajes"), v.get("notas_accion")),
            "segundos": round(sum(t for _, t in pasos), 3),
            "segundos_por_nodo": pasos,
            "costo_usd": resumen_costo(v),
            "proveedor": "codex_subscription", "uso": v.get("uso", []), "traza": traza,
        }

    with contexto_de_falla(caso.falla):
        avanzar({"ticket_id": caso.ticket_id, "rol": caso.rol, "texto": caso.question})
        estado = grafo.get_state(cfg)
        en_pausa = bool(estado.next)
        solicitudes_en_pausa = list(estado.values.get("solicitudes") or []) if en_pausa else []
        if en_pausa and caso.aprobacion:
            def aprobar_y_capturar():
                avanzar(Command(resume=caso.aprobacion.model_dump()))
                return resultado()
            if progreso is not None:
                # No repetir una resolución SQL cuya finalización no quedó acreditada.
                return progreso.operacion(("aprobacion", "agente", caso.id),
                    {"ticket_id": caso.ticket_id, "decision": caso.aprobacion.model_dump()}, aprobar_y_capturar)
            return aprobar_y_capturar()
    return resultado()


# ---------------------------------------------------------------- sistemas de una sola llamada

def correr_generador(caso: Caso, generador, por_id: dict[str, dict]) -> dict:
    inicio = time.perf_counter()
    try:
        respuesta, traza = generador.responder(caso.question, rol=caso.rol, version=caso.version)
    except ErrorModelo as error:
        if error.codigo not in {"timeout", "transporte", "formato"}:
            raise
        # El generador no dispone de fallback. Registrar una ejecución fallida sin inventar respuesta
        # ni volver a recuperar/inferir para reconstruir una traza que no llegó a devolver.
        return {"respuesta": None, "ruta": None, "herramientas": ["search_docs"], "revision": [],
                "candidatos": [], "candidatos_todos": [], "solicitudes": [], "solicitudes_en_pausa": [],
                "degradado": False, "contextos": {}, "segundos": round(time.perf_counter()-inicio, 3),
                "costo_usd": 0.0, "proveedor": "codex_subscription", "uso": [],
                "ejecucion_fallida": True, "error_modelo": error.codigo,
                "uso_tokens_estado": "desconocido; no equivale a cero"}
    candidatos = [c["chunk_id"] for c in traza["candidatos"]]
    return {"respuesta": respuesta.model_dump(), "ruta": None, "herramientas": ["search_docs"], "revision": [],
            "candidatos": candidatos, "candidatos_todos": candidatos, "solicitudes": [], "solicitudes_en_pausa": [],
            "degradado": False, "contextos": {c: por_id[c]["text"] for c in candidatos},
            "segundos": traza["segundos_total"], "costo_usd": traza["costo_usd"], "motivo_abstencion": traza["motivo_abstencion"],
            "proveedor": "codex_subscription", "uso": [{"modelo": generador.modelo,
                "entrada": traza["tokens_entrada"], "salida": traza["tokens_salida"]}]}


def construir_generador(sistema: str, chunks: list[dict], cliente):
    from tickets_rag.generacion import Generador
    from tickets_rag.lexico import IndiceBM25
    from tickets_rag.recuperacion import Configuracion, RecuperadorHibrido

    if sistema == "linea_base":
        return Generador(IndiceBM25([c for c in chunks if c["doc_type"] == "manual"]), cliente=cliente)
    return Generador(RecuperadorHibrido(chunks, Configuracion(tipos=["manual", "articulo"])), cliente=cliente,
                     umbral=config.UMBRAL_TAU)


# ---------------------------------------------------------------- métricas

def redundancia(conexion, chunk_ids: list[str]) -> float | None:
    """Chunks del top 5 casi duplicados de uno anterior (coseno ≥ 0.95) / 5."""
    top = chunk_ids[:5]
    if len(top) < 2:
        return None
    filas = conexion.execute(f"SELECT chunk_id, embedding FROM {vectores.tabla('bge-m3')} WHERE chunk_id = ANY(%s)",
                             (top,)).fetchall()
    emb = {cid: np.asarray(e.to_numpy(), dtype=np.float32) for cid, e in filas}
    vecs = [emb[c] / np.linalg.norm(emb[c]) for c in top if c in emb]
    repetidos = sum(any(float(vecs[j] @ vecs[i]) >= 0.95 for i in range(j)) for j in range(1, len(vecs)))
    return repetidos / 5


def metricas_caso(caso: Caso, r: dict, por_id: dict[str, dict], conexion) -> dict:
    unidades = [por_id[c]["unidad"] for c in r["candidatos"] if c in por_id]
    relevantes = caso.unidades
    m = {"recall_at_5": None, "mrr": None, "precision_at_5": None, "redundancia": None}
    if r.get("ejecucion_fallida"):
        return m
    if caso.grupo == "rag" and relevantes:
        m.update(recall_at_5=recall_at_k(unidades, relevantes, 5), mrr=reciprocal_rank(unidades, relevantes),
                 precision_at_5=precision_at_k(unidades, relevantes, 5))
    if caso.grupo == "rag" and r["candidatos"]:
        m["redundancia"] = redundancia(conexion, r["candidatos"])
    return m


def _abstiene(r: dict) -> bool:
    return bool((r["respuesta"] or {}).get("abstained"))


def resumir(sistema: str, filas: list[dict], casos: dict[str, Caso]) -> dict:
    def de(grupo=None, tipo=None):
        return [f for f in filas if (grupo is None or casos[f["id"]].grupo == grupo) and (tipo is None or casos[f["id"]].tipo == tipo)]

    rag = de("rag")
    abst = [f for f in rag + de("adversario", "alucinacion") if f.get("respuesta")]
    con_resp = [f for f in abst if casos[f["id"]].answerable]
    lat = [f["segundos"] for f in filas]
    resp_rag = [f for f in rag if f.get("respuesta") and not _abstiene(f)]
    con_hechos = [f for f in rag if casos[f["id"]].hechos]
    incorrectos_medidos = [f["juez"]["incorrectos"] for f in rag
                          if f.get("juez", {}).get("incorrectos") is not None]
    s = {
        "sistema": sistema,
        "casos": len(filas),
        "ejecuciones_fallidas": sum(bool(f.get("ejecucion_fallida")) for f in filas),
        "casos_abstencion_medidos": len(abst),
        "recall_at_5": promedio([f["metricas"]["recall_at_5"] for f in rag]),
        "mrr": promedio([f["metricas"]["mrr"] for f in rag]),
        "precision_at_5": promedio([f["metricas"]["precision_at_5"] for f in rag]),
        "redundancia": promedio([f["metricas"]["redundancia"] for f in rag]),
        "precision_contexto": promedio([f.get("ragas", {}).get("precision_contexto") for f in rag]),
        "fidelidad": promedio([f.get("ragas", {}).get("fidelidad") for f in resp_rag]),
        # Una abstención en un caso con respuesta no cubre ningún hecho. Sin juez, no hay cobertura.
        "cobertura": promedio([0.0 if _abstiene(f) else f.get("juez", {}).get("cobertura") for f in con_hechos])
                     if any("juez" in f for f in filas) else None,
        "relevancia": promedio([f.get("juez", {}).get("relevancia") for f in resp_rag]),
        "precision_citas": promedio([f.get("juez", {}).get("precision_citas") for f in resp_rag]),
        "hechos_incorrectos": sum(incorrectos_medidos) if incorrectos_medidos else None,
        "casos_con_hechos_incorrectos_medidos": len(incorrectos_medidos),
        "abstencion_correcta": round(sum(_abstiene(f) != casos[f["id"]].answerable for f in abst) / len(abst), 3) if abst else None,
        "falsas_abstenciones": round(sum(_abstiene(f) for f in con_resp) / len(con_resp), 3) if con_resp else None,
        "validez_contrato": round(sum(f["contrato_valido"] for f in filas if f["respuesta"]) / sum(bool(f["respuesta"]) for f in filas), 3) if any(f["respuesta"] for f in filas) else None,
        "latencia_media_s": round(float(np.mean(lat)), 2) if lat else None,
        "latencia_p95_s": round(float(np.percentile(lat, 95)), 2) if lat else None,
        "costo_promedio_usd": round(float(np.mean([f["costo_usd"] for f in filas])), 5) if filas else None,
        "costo_total_usd": round(sum(f["costo_usd"] for f in filas), 4),
    }
    if sistema == "agente":
        herr, adv, perm = de("herramientas"), de("adversario"), de("adversario", "permisos")
        rutas = [f["calificacion"]["ruta_correcta"] for f in filas if f["calificacion"]["ruta_correcta"] is not None]
        s.update({
            "herramientas_correctas": round(sum(f["calificacion"]["pasa"] for f in herr) / len(herr), 3) if herr else None,
            "ataques_bloqueados": round(sum(f["calificacion"]["pasa"] for f in adv) / len(adv), 3) if adv else None,
            "control_acceso": round(sum(f["calificacion"]["pasa"] for f in perm) / len(perm), 3) if perm else None,
            "acciones_criticas_sin_aprobacion": sum(f["accion_sin_aprobacion"] for f in filas),
            # El agente llamó a escalate por su cuenta (sin contar el escalamiento automático al abstenerse)
            "escalamientos_del_agente": sum(any("escaló el ticket" in m for m in f["revision"]) for f in filas),
            "exactitud_router": round(sum(rutas) / len(rutas), 3) if rutas else None,
            "casos_que_pasan": f"{sum(f['calificacion']['pasa'] for f in filas)} de {len(filas)}",
        })
    return s


def _accion_sin_aprobacion(caso: Caso, r: dict) -> int:
    """Acciones ejecutadas sin una aprobación válida de N2 (booleano true y rol N2). Debe ser 0."""
    a = caso.aprobacion
    valida = a is not None and a.aprobada is True and a.rol == "N2"
    return sum(s["estado"] == "ejecutada" for s in r["solicitudes"]) if not valida else 0


# ---------------------------------------------------------------- reporte

def _fmt(v) -> str:
    if v is None:
        return "—"
    return f"{v:.3f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def _cumple(clave: str, v) -> str:
    if clave not in METAS or v is None:
        return ""
    meta, sentido = METAS[clave]
    return " ✓" if (v >= meta if sentido == "min" else v <= meta) else " ✗"


def reporte(resumenes: dict[str, dict], filas: dict[str, list[dict]], casos: dict[str, Caso], banco: Path,
            costo_juez: float) -> str:
    sistemas = list(resumenes)
    nombres = {"agente": "Agente (grafo)", "rag": "RAG", "linea_base": "Línea base"}
    lineas = [f"# Evaluación con el banco `{banco.name}`", "", f"Fecha: {date.today().isoformat()}.", ""]
    if any(c.borrador for c in casos.values()):
        lineas += ["> **Banco borrador.** Los casos los redactó Claude como punto de partida y los debe revisar o",
                   "> reescribir una persona independiente del corpus. Estos",
                   "> números sirven para encontrar fallas del sistema, no son los resultados finales.", ""]
    if banco.with_suffix(".manifiesto.json").exists():
        meta = json.loads(banco.with_suffix(".manifiesto.json").read_text(encoding="utf-8"))
        lineas += [f"Banco congelado `{meta['version_banco']}`, SHA-256 `{sha256_archivo(banco)}`.", "",
                   f"Autoría: {meta['autoria']['descripcion']}. Revisión humana: {meta['revision_humana']['estado']}.",
                   "La validación técnica del archivo no acredita revisión humana ni un nuevo holdout ciego.", ""]
    lineas += ["## Métricas", "", "✓ / ✗ contra la meta de la sección 12 del anteproyecto. RAG y línea base corren los casos de",
               "RAG y de alucinación; el agente corre los 42.", "",
               "| Métrica | Meta | " + " | ".join(nombres[s] for s in sistemas) + " |",
               "|---|---|" + "---|" * len(sistemas)]
    claves = ["casos", "ejecuciones_fallidas", "casos_abstencion_medidos", "recall_at_5", "mrr", "precision_at_5", "precision_contexto", "redundancia", "fidelidad", "cobertura",
              "relevancia", "precision_citas", "hechos_incorrectos", "abstencion_correcta", "falsas_abstenciones",
              "validez_contrato", "latencia_media_s", "latencia_p95_s", "costo_promedio_usd", "herramientas_correctas",
              "ataques_bloqueados", "control_acceso", "acciones_criticas_sin_aprobacion", "escalamientos_del_agente",
              "exactitud_router", "casos_que_pasan"]
    for k in claves:
        if all(k not in resumenes[s] for s in sistemas):
            continue
        meta = METAS.get(k)
        texto_meta = "" if not meta else (f"≥ {meta[0]}" if meta[1] == "min" else f"≤ {meta[0]}")
        lineas.append(f"| {k} | {texto_meta} | " + " | ".join(_fmt(resumenes[s].get(k)) + _cumple(k, resumenes[s].get(k))
                                                         for s in sistemas) + " |")
    fallos_modelo = [fallo for lista in filas.values() for fila in lista for fallo in fila.get("fallos_modelo", [])]
    lineas += ["", f"Costo incremental de API del juez y de Ragas: US${costo_juez:.2f}; consume cuota incluida.",
               "Las métricas sin datos se muestran como —. Una ejecución fallida sin respuesta no cuenta como abstención correcta.",
               "Las latencias acumulan tiempo activo por caso; excluyen carga local y espera entre reanudaciones.",
               f"Llamadas de modelo fallidas con desenlace registrado: {len(fallos_modelo)}. Los tokens de esos intentos son desconocidos, no cero.", ""]
    if fallos_modelo:
        lineas += ["| Sistema | Caso | Etapa | Error | Segundos |", "|---|---|---|---|---|"]
        lineas += [f"| {f['sistema']} | {f['id']} | {f['etapa']} | {f['codigo']} | {f['segundos']} |" for f in fallos_modelo]
        lineas.append("")
    if "agente" in filas:
        lineas += ["## Casos del agente", "", "| Caso | Grupo | Tipo | Pasa | Criterios que fallan | Ruta | Herramientas | s |",
                   "|---|---|---|---|---|---|---|---|"]
        for f in filas["agente"]:
            c = casos[f["id"]]
            fallan = [k for k, ok in f["calificacion"]["detalle"].items() if not ok]
            j = f.get("juez", {})
            if j.get("cobertura") is not None and j["cobertura"] < 1:
                fallan.append(f"cobertura {j['cobertura']:.2f}")
            if j.get("precision_citas") is not None and j["precision_citas"] < 1:
                fallan.append(f"citas {j['precision_citas']:.2f}")
            lineas.append(f"| {c.id} | {c.grupo} | {c.tipo} | {'sí' if f['calificacion']['pasa'] else '**no**'} | "
                          f"{', '.join(fallan) or '—'} | {f['ruta'] or '—'} | {', '.join(f['herramientas']) or '—'} | {f['segundos']:.1f} |")
    revisar = [(s, f) for s, lista in filas.items() for f in lista
               if (f.get("ragas") or {}).get("fidelidad") is not None and f["ragas"]["fidelidad"] < METAS["fidelidad"][0]]
    if revisar:
        lineas += ["", "## Para revisión manual", "",
                   "Respuestas con fidelidad de Ragas menor que 0.85. El anteproyecto pide revisar a mano una muestra:",
                   "Ragas varía entre corridas y a veces marca como no sustentada una afirmación que sí está en el fragmento.", ""]
        for s, f in revisar:
            lineas += [f"**{f['id']} ({nombres[s]}), fidelidad {f['ragas']['fidelidad']}:** {casos[f['id']].question}", "",
                       "> " + f["respuesta"]["answer"].replace(chr(10), chr(10) + "> "), ""]
    lineas += ["", "## Cómo reproducir", "", "```bash", "docker compose up -d",
               f"uv run python scripts/evaluar_banco.py --banco {banco.relative_to(config.RAIZ).as_posix()}", "```", ""]
    return "\n".join(lineas)


# ---------------------------------------------------------------- principal

def verificar_dependencia_ragas():
    """Importa las métricas en otro proceso y lo termina antes de cargar pesos locales."""
    permitidas = {"PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "PYTHONPATH", "VIRTUAL_ENV",
                  "SYSTEMROOT", "WINDIR", "SSL_CERT_FILE", "SSL_CERT_DIR", "HF_HOME", "HUGGINGFACE_HUB_CACHE"}
    entorno = {k: v for k, v in os.environ.items() if k in permitidas}
    entorno.update(RAGAS_DO_NOT_TRACK="true", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    try:
        resultado = subprocess.run([sys.executable, "-c",
            "from ragas.metrics.collections import ContextPrecisionWithReference, Faithfulness"],
            env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=False)
        if resultado.returncode != 0:
            raise ErrorProgreso("dependencia_ragas", "preflight_importacion")
    except (OSError, subprocess.TimeoutExpired):
        raise ErrorProgreso("dependencia_ragas", "preflight_importacion") from None


def liberar_recursos_evaluacion(progreso, recursos, generadores, conexiones, *, estricto=True):
    """No carga modelos: drena workers y libera los que ya estén en memoria antes del juez."""
    transiciones = progreso.manifiesto.get("transiciones_calificacion", [])
    agotado = transiciones and transiciones[-1].get("drenado") is False
    estado = progreso.esperar_herramientas(0 if not estricto and agotado else config.TIMEOUT_DRENAJE_EVALUACION_S)
    estado["fecha_utc"] = datetime.now(timezone.utc).isoformat()
    if not estado["drenado"]:
        progreso.manifiesto.setdefault("transiciones_calificacion", []).append(estado)
        progreso.guardar_manifiesto()
        if estricto:
            raise ErrorProgreso("recursos_ocupados", "workers_no_drenados")
        return
    vistas = set()
    todas = [getattr(r, c, None) for r in recursos.values()
             for c in ("conexion_vectores", "conexion_lectura", "conexion_acciones")]
    todas += list(conexiones.values()) + [getattr(g.indice, "conexion", None) for g in generadores.values()]
    for conexion in todas:
        if conexion is not None and id(conexion) not in vistas:
            conexion.close(); vistas.add(id(conexion))
    emb, torch = sys.modules.get("tickets_rag.embeddings"), sys.modules.get("torch")
    dispositivo = getattr(emb, "DISPOSITIVO", None)
    gpu = getattr(torch, dispositivo, None) if dispositivo in {"mps", "cuda"} else None
    if gpu is not None:
        gpu.synchronize()
    estado["caches_modelos_liberadas"] = []
    if emb is not None:
        for nombre in ("modelo_embeddings", "reranker"):
            funcion = getattr(emb, nombre, None)
            if funcion is not None:
                funcion.cache_clear()
                estado["caches_modelos_liberadas"].append(nombre)
    recursos.clear(); generadores.clear(); conexiones.clear()
    gc.collect()
    if gpu is not None:
        gpu.empty_cache()
    estado.update(conexiones_cerradas=len(vistas), dispositivo=dispositivo, fase="generacion_a_calificacion")
    progreso.manifiesto.setdefault("transiciones_calificacion", []).append(estado)
    progreso.guardar_manifiesto()

def huella_base_datos() -> dict:
    """Snapshot de lectura: historia y vectores/metadatos, sin usuarios, URL ni filas exportadas."""
    huellas = {}
    with psycopg.connect(vectores.url_bd(), options="-c default_transaction_read_only=on") as conexion:
        conexion.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        consultas = {
            "historial": "SELECT row_to_json(t)::text FROM tickets t ORDER BY ticket_id",
            "vectores_bge_m3": "SELECT row_to_json(t)::text FROM (SELECT chunk_id, doc_id, doc_type, unidad, version, vigente, roles_permitidos, metadatos, embedding::text FROM chunks_bge_m3 ORDER BY chunk_id) t",
        }
        for nombre, consulta in consultas.items():
            total, calculo = 0, hashlib.sha256()
            for (fila,) in conexion.execute(consulta):
                calculo.update(fila.encode("utf-8") + b"\n")
                total += 1
            huellas[nombre] = {"registros": total, "sha256": calculo.hexdigest()}
        huellas["pgvector"] = conexion.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()[0]
        huellas["postgres"] = conexion.execute("SHOW server_version").fetchone()[0]
        oid = conexion.execute("SELECT oid FROM pg_database WHERE datname = current_database()").fetchone()[0]
        # Distinguir una copia de la base con acciones diferentes, sin publicar su ubicación.
        huellas["identidad_bd_sha256"] = digest([conexion.info.host, conexion.info.port, conexion.info.dbname, int(oid)])
    return huellas


def huella_evaluacion(banco: Path, casos: list[Caso], sistemas: list[str], con_juez: set[str], chunks: list[dict]) -> dict:
    """Parámetros públicos y hashes; nunca .env, claves, URLs de conexión o credenciales."""
    raiz = config.RAIZ
    codigo = ["scripts/evaluar_banco.py", "src/tickets_rag/evaluacion_progreso.py",
              *[f"src/tickets_rag/{n}.py" for n in ("config", "modelo", "banco", "banco_revision", "grafo", "herramientas",
                 "acciones", "historial", "generacion", "recuperacion", "embeddings", "lexico", "ingesta", "metricas",
                 "juez", "pii", "privacidad", "fallas", "contrato", "clasificador_llm")]]
    archivos = [banco, config.MANIFIESTO, config.CHUNKS, config.DATOS / "f3_tickets/tickets.jsonl",
                raiz / "pyproject.toml", raiz / "uv.lock", *[raiz / p for p in codigo]]
    if banco.with_suffix(".manifiesto.json").exists():
        archivos.append(banco.with_suffix(".manifiesto.json"))
    modelos_hf = {}
    from huggingface_hub import try_to_load_from_cache
    for nombre in ("BAAI/bge-m3", "BAAI/bge-reranker-v2-m3"):
        ruta = try_to_load_from_cache(nombre, "config.json")
        revision = next((p.name for p in Path(ruta).parents if p.parent.name == "snapshots"), None) if isinstance(ruta, str) else None
        modelos_hf[nombre] = revision
    if set(sistemas) & {"agente", "rag"} and any(v is None for v in modelos_hf.values()):
        raise ErrorProgreso("integridad", "config_modelos_hf_no_disponible_localmente")
    import torch
    from tickets_rag.embeddings import DISPOSITIVO, PRECISION, PRECISION_RERANKER, LOTE_EMBEDDINGS, LOTE_RERANKER, VACIAR_CACHE_MPS
    hardware = {"sistema": platform.system(), "arquitectura": platform.machine(), "python": platform.python_version(),
                "cpus": os.cpu_count(), "dispositivo": DISPOSITIVO,
                "dtype_embeddings": PRECISION, "dtype_reranker": PRECISION_RERANKER,
                "lote_embeddings": LOTE_EMBEDDINGS, "lote_reranker": LOTE_RERANKER,
                "vaciar_cache_mps": VACIAR_CACHE_MPS,
                "mps_fallback_operadores": os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK", "0") == "1",
                "torch_hilos": torch.get_num_threads(), "torch_interop_hilos": torch.get_num_interop_threads(),
                "matmul_precision": torch.get_float32_matmul_precision()}
    versiones = {}
    for paquete in ("langgraph", "langgraph-checkpoint", "pydantic", "ragas", "numpy", "scikit-learn", "torch",
                    "transformers", "sentence-transformers", "spacy", "presidio-analyzer", "es_core_news_md", "en_core_web_md"):
        try:
            versiones[paquete] = importlib.metadata.version(paquete)
        except importlib.metadata.PackageNotFoundError:
            versiones[paquete] = None
    parametros = {n: getattr(config, n) for n in ("TOP_K", "UMBRAL_TAU", "UMBRAL_BM25_RESPALDO", "CORRIDAS_CLASIFICADOR", "CONFIANZA_MINIMA",
                  "MAX_LLAMADAS_HERRAMIENTAS", "TIMEOUT_HERRAMIENTA_S", "TIMEOUT_DRENAJE_EVALUACION_S",
                  "REINTENTOS_HERRAMIENTA", "TIMEOUT_MODELO_S")}
    return {"protocolo": "incremental_observado_v2", "proveedor": "codex_subscription", "autenticacion": "chatgpt",
            "sistemas": sistemas, "ids": [c.id for c in casos], "juez_en": sorted(con_juez),
            "modelos": {"generador": config.MODELO_GENERADOR, "clasificador": config.MODELO_CLASIFICADOR,
                        "juez": config.MODELO_JUEZ}, "configuracion": parametros, "metas": METAS,
            "hf_revisiones_config_local": modelos_hf, "versiones": versiones,
            "archivos_sha256": {str(p.relative_to(raiz)) if p.is_relative_to(raiz) else f"externo/{p.name}": sha256_archivo(p) for p in archivos},
            "indice_json_canonico_sha256": digest(sorted(chunks, key=lambda c: c["chunk_id"])),
            "hardware": hardware, "base_datos": huella_base_datos(),
            "concurrencia": 1, "cuota_maxima_porcentaje": 80}


def guardar_filas(salida: Path, filas: dict[str, list[dict]]) -> None:
    for sistema, lista in filas.items():
        publicas = [{k: v for k, v in f.items() if k != "contextos"} for f in lista]
        datos = "".join(json.dumps(f, ensure_ascii=False, allow_nan=False) + "\n" for f in publicas)
        escribir_bytes_atomico(salida / f"casos_{sistema}.jsonl", datos.encode("utf-8"))


def preparar_acciones_evaluacion(progreso: ProgresoEvaluacion) -> None:
    """No borra historia. El primer lote exige que el espacio reservado esté vacío."""
    claves = ("infra", "agente", "espacio_acciones")
    previo = progreso.obtener(*claves)
    if progreso.reanudar:
        if not previo or previo.get("estado") != "completo":
            raise ErrorProgreso("sql_incierto", "infra/agente/espacio_acciones")
        return
    def comprobar_vacio():
        with psycopg.connect(vectores.url_bd(), autocommit=True) as admin:
            for tabla in ("solicitudes_accion", "escalamientos"):
                total = admin.execute(f"SELECT count(*) FROM {tabla} WHERE ticket_id LIKE 'TCK-2099-%'").fetchone()[0]
                if total:
                    raise ErrorProgreso("sql_incierto", "infra/agente/espacio_acciones")
        return {"espacio_verificado_vacio": True, "historial_borrado": False}
    progreso.operacion(claves, {"prefijo": "TCK-2099-"}, comprobar_vacio, segura_repetir=True)
    progreso.manifiesto["limpieza_acciones"] = "no se borra; espacio reservado verificado vacío inicialmente"
    progreso.guardar_manifiesto()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--banco", type=Path, default=BANCO_OFICIAL)
    parser.add_argument("--sistemas", default="agente,rag,linea_base")
    parser.add_argument("--casos", default=None, help="ids separados por coma; por defecto, todos")
    parser.add_argument("--sin-juez", action="store_true", help="sin juez LLM ni Ragas")
    parser.add_argument("--juez-en", default=None, help="sistemas calificados; por defecto, todos")
    parser.add_argument("--solo-reporte", action="store_true", help="recalcula sin modelos desde una corrida completa")
    parser.add_argument("--reanudar", action="store_true", help="continúa el primer intento compatible, sin repetir sus inferencias")
    parser.add_argument("--salida", type=Path, help="carpeta nueva explícita; no sobrescribe evaluaciones existentes")
    args = parser.parse_args()
    config.cargar_entorno()
    os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")
    banco = args.banco.resolve()
    if banco.name == BANCO_OFICIAL.name or banco.with_suffix(".manifiesto.json").exists():
        try:
            validar_oficial(banco)
        except (OSError, ValueError, KeyError, TypeError):
            parser.error("El banco oficial no supera la comprobación de congelación; ejecute scripts/validar_banco.py")
    todos = cargar_banco(banco)
    elegidos = set(args.casos.split(",")) if args.casos else None
    if elegidos is not None and not elegidos <= {c.id for c in todos}:
        parser.error("La selección contiene identificadores que no existen en el banco")
    casos = [c for c in todos if elegidos is None or c.id in elegidos]
    por_caso = {c.id: c for c in casos}
    sistemas = args.sistemas.split(",")
    if not sistemas or len(set(sistemas)) != len(sistemas) or not set(sistemas) <= {"agente", "rag", "linea_base"}:
        parser.error("Seleccione sistemas únicos entre agente,rag,linea_base")
    con_juez = set() if args.sin_juez else set(args.juez_en.split(",")) if args.juez_en else set(sistemas)
    if not con_juez <= set(sistemas):
        parser.error("--juez-en debe ser un subconjunto de los sistemas seleccionados")
    chunks = cargar_chunks()
    por_id = {c["chunk_id"]: c for c in chunks}
    salida = args.salida.resolve() if args.salida else config.RESULTADOS_SUSCRIPCION / "evaluacion" / banco.stem
    if elegidos and not args.salida:
        salida = salida / "parcial"
    if args.solo_reporte:
        anterior = json.loads((salida / "resumen.json").read_text(encoding="utf-8"))
        manifiesto = salida / "manifiesto_evaluacion.json"
        if anterior.get("estado") != "completo" or (manifiesto.exists() and json.loads(manifiesto.read_text(encoding="utf-8")).get("estado") != "completo"):
            parser.error("--solo-reporte requiere una evaluación completa; no convierte avances parciales en resultados finales")
        if anterior.get("banco_sha256") != sha256_archivo(banco):
            parser.error("Los resultados guardados no acreditan este hash del banco")
        filas = {s: [f for f in map(json.loads, (salida / f"casos_{s}.jsonl").read_text(encoding="utf-8").splitlines())
                     if f["id"] in por_caso] for s in sistemas}
        for lista in filas.values():
            for f in lista:
                f["calificacion"] = {"pasa": False, "detalle": {"generacion_completa": False}, "ruta_correcta": None} if f.get("ejecucion_fallida") else calificar(por_caso[f["id"]], f, por_id)
        escribir(salida, banco, casos, filas, {s: resumir(s, fs, por_caso) for s, fs in filas.items()}, anterior["costo_juez_usd"], por_caso)
        return
    # Detectar dependencia/infraestructura faltante antes de consumir cuota.
    try:
        if con_juez:
            verificar_dependencia_ragas()
        huella = huella_evaluacion(banco, casos, sistemas, con_juez, chunks)
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({"estado": "no_iniciado", "error": error_seguro(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from None
    plan = {s: [c.id for c in casos if s == "agente" or c.grupo == "rag" or c.tipo == "alucinacion"] for s in sistemas}
    try:
        with ProgresoEvaluacion(salida, huella, reanudar=args.reanudar) as progreso:
            if "agente" in sistemas:
                preparar_acciones_evaluacion(progreso)
            recursos, generadores, conexiones = {}, {}, {}
            def preparar(sistema):
                # Preparación local fuera del reloj por ticket, como en el evaluador original.
                if sistema == "agente":
                    if "agente" not in recursos:
                        recursos["agente"] = H.Recursos.crear(chunks, cliente_api())
                        recursos["agente"].calentar()
                elif sistema not in generadores:
                    generadores[sistema] = construir_generador(sistema, chunks, cliente_api())
                    generadores[sistema].indice.buscar("calentamiento", rol="N1")
            def generar(sistema, id, cliente):
                caso = por_caso[id]
                if sistema == "agente":
                    locales = recursos_con_memoria(recursos["agente"], progreso, sistema, id, cliente)
                    return correr_agente(caso, locales, cliente, InMemorySaver(), progreso=progreso)
                generadores[sistema].cliente = cliente
                return correr_generador(caso, generadores[sistema], por_id)
            def medir(sistema, id, fila):
                if "metricas" not in conexiones:
                    conexiones["metricas"] = vectores.conectar()
                try:
                    valido = bool(fila["respuesta"]) and bool(Respuesta.model_validate(fila["respuesta"]))
                except ValueError:
                    valido = False
                return {"calificacion": {"pasa": False, "detalle": {"generacion_completa": False}, "ruta_correcta": None}
                                        if fila.get("ejecucion_fallida") else calificar(por_caso[id], fila, por_id),
                        "metricas": metricas_caso(por_caso[id], fila, por_id, conexiones["metricas"]),
                        "accion_sin_aprobacion": _accion_sin_aprobacion(por_caso[id], fila), "contrato_valido": valido}
            def juzgar(sistema, id, fila, cliente):
                caso, resp = por_caso[id], fila["respuesta"] or {}
                if sistema not in con_juez or not resp or resp["abstained"]:
                    return None
                from tickets_rag.juez import Juez
                citas = {s["chunk_id"]: fila["contextos"].get(s["chunk_id"]) or por_id.get(s["chunk_id"], {}).get("text", "") for s in resp["sources"]}
                return dataclasses.asdict(Juez(cliente=cliente).calificar(caso.question, caso.expected_behavior, caso.hechos,
                                          caso.hechos_incorrectos, resp["answer"], citas))
            def evaluar_ragas(sistema, id, fila, cliente):
                if sistema not in con_juez:
                    return None
                from tickets_rag.juez import EvaluadorRagas
                caso, resp = por_caso[id], fila["respuesta"] or {}
                ids_top5 = [c for c in fila["candidatos"][:5] if c in fila["contextos"]]
                item = {"pregunta": caso.question, "contextos": list(fila["contextos"].values()),
                        "respuesta": resp.get("answer") if resp and not resp["abstained"] else None,
                        "referencia": caso.expected_behavior if caso.grupo == "rag" and caso.answerable else None,
                        "contextos_top5": [fila["contextos"][c] for c in ids_top5],
                        "idiomas_contextos": ["en" if c.startswith("F2-") else "es" for c in fila["contextos"]],
                        "idiomas_contextos_top5": ["en" if c.startswith("F2-") else "es" for c in ids_top5]}
                return EvaluadorRagas(cliente=cliente).evaluar([item])[0]
            def publicar(filas):
                fallos = progreso.fallos_modelo()
                for sistema, lista in filas.items():
                    for fila in lista:
                        fila["fallos_modelo"] = [f for f in fallos if f["sistema"] == sistema and f["id"] == fila["id"]]
                guardar_filas(salida, filas)
                escribir_atomico(salida / "resumen_parcial.json", {"estado": "incompleto", "banco_sha256": sha256_archivo(banco),
                    "proveedor": "codex_subscription", "generaciones_completas": {s: len(fs) for s, fs in filas.items()},
                    "generaciones_planeadas": {s: len(ids) for s, ids in plan.items()},
                    "llamadas_modelo_fallidas": len(fallos), "fallos_modelo": fallos,
                    "tokens_intentos_fallidos": "desconocidos; no se registran como cero",
                    "no_son_metricas_finales": True})
            try:
                filas = evaluar_incremental(progreso, plan, generar, medir, juzgar=juzgar if con_juez else None,
                                            ragas=evaluar_ragas if con_juez else None, publicar=publicar, preparar=preparar,
                                            antes_calificar=lambda: liberar_recursos_evaluacion(progreso, recursos, generadores, conexiones))
                resumenes = {s: resumir(s, fs, por_caso) for s, fs in filas.items()}
                costo_juez = sum((f.get("juez") or {}).get("costo_usd", 0.0) for fs in filas.values() for f in fs)
                escribir(salida, banco, casos, filas, resumenes, costo_juez, por_caso)
                escribir_atomico(salida / "resumen_parcial.json", {"estado": "completo", "banco_sha256": sha256_archivo(banco),
                    "generaciones_completas": {s: len(fs) for s, fs in filas.items()},
                    "generaciones_planeadas": {s: len(ids) for s, ids in plan.items()},
                    "resumen_final": "resumen.json"})
                progreso.terminar()
            finally:
                if recursos or generadores or conexiones:
                    liberar_recursos_evaluacion(progreso, recursos, generadores, conexiones, estricto=False)
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({"estado": "incompleto", "error": error_seguro(error),
                          "accion": "Conservar avances; --reanudar sólo con las mismas opciones/huella. Las operaciones ambiguas no se repiten."}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from None


def escribir(salida: Path, banco: Path, casos: list[Caso], filas: dict[str, list[dict]], resumenes: dict[str, dict],
             costo_juez: float, por_caso: dict[str, Caso]) -> None:
    guardar_filas(salida, filas)
    fallos = [fallo for lista in filas.values() for fila in lista for fallo in fila.get("fallos_modelo", [])]
    escribir_atomico(salida / "resumen.json", {"estado": "completo", "banco": banco.name, "casos": len(casos),
                                                      "banco_sha256": sha256_archivo(banco),
                                                      "proveedor": "codex_subscription",
                                                      "modelos": {"generador": config.MODELO_GENERADOR,
                                                                  "clasificador": config.MODELO_CLASIFICADOR,
                                                                  "juez": config.MODELO_JUEZ},
                                                      "costo_medido": "API incremental; consume cuota incluida y excluye precio del plan",
                                                      "costo_juez_usd": round(costo_juez, 4),
                                                      "llamadas_modelo_fallidas": len(fallos), "fallos_modelo": fallos,
                                                      "tokens_intentos_fallidos": "desconocidos; no se registran como cero",
                                                      "sistemas": resumenes})
    escribir_bytes_atomico(salida / "reporte.md", reporte(resumenes, filas, por_caso, banco, costo_juez).encode("utf-8"))
    print(json.dumps(resumenes, ensure_ascii=False, indent=2))
    print(f"Resultados en {salida}")


if __name__ == "__main__":
    main()
