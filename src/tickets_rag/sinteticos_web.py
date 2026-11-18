"""Lectura del conjunto sintético y de resultados compatibles; nunca inicia inferencias."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tickets_rag import config


class ErrorVistaSinteticos(ValueError):
    pass


def _sha(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def obtener_sinteticos(raiz: Path = config.RAIZ) -> dict:
    carpeta = raiz / "evaluacion/tickets_sinteticos"
    try:
        raw = (carpeta / "tickets.jsonl").read_bytes()
        manifest_raw = (carpeta / "manifiesto.json").read_bytes()
        meta = json.loads(manifest_raw)
        tickets = [json.loads(l) for l in raw.splitlines() if l.strip()]
        if (meta["autoria"]["tipo"] != "IA" or meta["cumple_requisito_20_humanos"] is not False
                or meta["artefactos_sha256"]["tickets.jsonl"] != _sha(raw) or len(tickets) != 20
                or {t["ticket_id"] for t in tickets} != {f"SYN-{n:02d}" for n in range(1, 21)}
                or any(t["procedencia"] != "sintetico_ia" for t in tickets)):
            raise ValueError
    except (OSError, ValueError, TypeError, KeyError):
        raise ErrorVistaSinteticos("El conjunto sintético no está disponible o no supera la verificación de integridad.") from None

    evaluacion = {"estado": "sin_iniciar", "tickets_medidos": 0, "tickets_objetivo": 20,
                  "metricas_parciales": True, "macro_f1": None}
    resultados = raiz / "resultados/codex_suscripcion/clasificador_sinteticos"
    # Solo resultados vinculados al mismo conjunto y manifiesto; no exponer el journal privado.
    for resumen_path in sorted(resultados.glob("*/resumen.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True):
        try:
            resumen = json.loads(resumen_path.read_bytes())
            registro = json.loads((resumen_path.parent / "corrida.json").read_bytes())
            plan = registro["plan"]
            canonico = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            if (plan["tickets_sha256"] != _sha(raw) or plan["manifiesto_sha256"] != _sha(manifest_raw)
                    or _sha(canonico) != registro["plan_sha256"] or resumen["plan_sha256"] != registro["plan_sha256"]
                    or resumen["corrida_id"] != registro["corrida_id"] or resumen["autoria"] != "IA"
                    or resumen["cumple_requisito_20_humanos"] is not False
                    or resumen["tickets_objetivo"] != 20 or type(resumen["tickets_medidos"]) is not int
                    or not 0 <= resumen["tickets_medidos"] <= 20):
                continue
            if resumen["estado"] == "completo" and (resumen["tickets_medidos"] != 20 or resumen["metricas_parciales"] is not False):
                continue
            evaluacion = resumen
            break
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return {"metadatos": meta, "tickets": tickets, "evaluacion": evaluacion}
