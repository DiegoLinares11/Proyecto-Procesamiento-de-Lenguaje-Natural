"""Snapshot público de la evaluación canónica; sólo lee JSON locales con stdlib.

Un manifiesto ``en_curso`` describe el último estado guardado, no un proceso vivo.
La interrupción sólo se acredita con un registro posterior y conteos coincidentes.
No se inspecciona la caché privada, ni se importa o inicia el evaluador.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SISTEMAS = ("agente", "rag", "linea_base")


class ErrorEstadoEvaluacion(Exception):
    """Los artefactos existen pero no se pueden presentar de forma fiable."""


def _leer(ruta: Path) -> tuple[dict | None, float | None]:
    try:
        if not ruta.exists():
            return None, None
        if ruta.is_symlink() or ruta.stat().st_size > 2_000_000:
            raise ValueError
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        if not isinstance(datos, dict):
            raise ValueError
        return datos, ruta.stat().st_mtime
    except (OSError, ValueError, UnicodeError):
        raise ErrorEstadoEvaluacion("No se pudo leer el estado guardado de la evaluación.") from None


def _conteos(datos: dict, clave: str) -> dict[str, int]:
    valores = datos.get(clave)
    if not isinstance(valores, dict) or set(valores) != set(SISTEMAS):
        raise ErrorEstadoEvaluacion("El progreso guardado no contiene conteos válidos.")
    if any(type(v) is not int or not 0 <= v <= 100_000 for v in valores.values()):
        raise ErrorEstadoEvaluacion("El progreso guardado no contiene conteos válidos.")
    return {s: valores[s] for s in SISTEMAS}


def _fecha(marca: float | None) -> str | None:
    return datetime.fromtimestamp(marca, timezone.utc).isoformat() if marca is not None else None


def obtener_progreso_evaluacion(raiz: Path | None = None, *, banco: str = "banco.jsonl") -> dict:
    raiz = Path(raiz) if raiz is not None else Path(__file__).resolve().parents[2]
    carpeta = raiz / "resultados" / "codex_suscripcion" / "evaluacion" / Path(banco).stem
    manifiesto, fecha_manifiesto = _leer(carpeta / "manifiesto_evaluacion.json")
    parcial, fecha_parcial = _leer(carpeta / "resumen_parcial.json")
    final, fecha_final = _leer(carpeta / "resumen.json")
    marcas = [f for f in (fecha_manifiesto, fecha_parcial, fecha_final) if f is not None]
    respuesta = {
        "version": 1, "banco": banco, "proveedor": "codex_subscription", "solo_lectura": True,
        "estado": "sin_datos", "actualizado_utc": _fecha(max(marcas)) if marcas else None,
        "generaciones": None, "metricas_finales_disponibles": False,
        "calificacion": "pendiente", "interrupcion_confirmada": False,
    }
    if not marcas:
        return respuesta

    respuesta["estado"] = "por_completar"
    if parcial is not None:
        completas = _conteos(parcial, "generaciones_completas")
        planeadas = _conteos(parcial, "generaciones_planeadas")
        if any(completas[s] > planeadas[s] for s in SISTEMAS) or not sum(planeadas.values()):
            raise ErrorEstadoEvaluacion("El progreso guardado contiene conteos inconsistentes.")
        respuesta["generaciones"] = {
            "completas": sum(completas.values()), "planeadas": sum(planeadas.values()),
            "pendientes": sum(planeadas.values()) - sum(completas.values()),
            "por_sistema": {s: {"completas": completas[s], "planeadas": planeadas[s]} for s in SISTEMAS},
        }

    # El resumen final y el cierre del manifiesto deben coincidir. Los resultados
    # históricos los sigue sirviendo /api/evaluacion, separados de este progreso.
    if final is not None and final.get("estado") == "completo" and isinstance(final.get("sistemas"), dict) \
            and set(SISTEMAS).issubset(final["sistemas"]) \
            and (manifiesto is None or manifiesto.get("estado") == "completo"):
        # Un parcial anterior no se transforma en 88/88 ni se presenta como el
        # avance del cierre final. El resumen final conserva sus propias métricas.
        if respuesta["generaciones"] and respuesta["generaciones"]["pendientes"]:
            respuesta["generaciones"] = None
        respuesta.update(estado="completa", metricas_finales_disponibles=True, calificacion="completa")
        return respuesta

    # Este registro no tiene identidad de corrida propia. Sólo es aplicable al
    # banco canónico si es posterior al progreso y reproduce todos sus conteos.
    if Path(banco).stem == "banco" and parcial is not None:
        try:
            interrupcion, fecha_interrupcion = _leer(raiz / "resultados" / "cierre_tecnico" / "interrupcion_ultima.json")
        except ErrorEstadoEvaluacion:
            interrupcion, fecha_interrupcion = None, None
        if interrupcion is not None:
            observado = interrupcion.get("estado_observado", "")
            coherente = (
                isinstance(observado, str) and "interrumpida" in observado and "no activo" in observado
                and interrupcion.get("generaciones_completas") == completas
                and type(interrupcion.get("generaciones_pendientes")) is int
                and interrupcion["generaciones_pendientes"] == respuesta["generaciones"]["pendientes"]
                and interrupcion.get("juez_ragas_completo") is False
                and fecha_interrupcion is not None and fecha_interrupcion >= max(marcas)
            )
            if coherente:
                respuesta.update(estado="interrumpida", interrupcion_confirmada=True,
                                 actualizado_utc=_fecha(fecha_interrupcion))
    return respuesta
