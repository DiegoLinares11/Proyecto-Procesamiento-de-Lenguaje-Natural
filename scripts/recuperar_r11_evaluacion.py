#!/usr/bin/env python3
"""Prepara una única continuación de R11 sin ejecutar modelos ni adjudicar su envío anterior.

Por defecto sólo verifica. --aplicar conserva los bytes originales en una subcarpeta
privada y retira exclusivamente el registro activo del modelo ambiguo. El evaluador
existente podrá repetir esa llamada al reanudar; no debe presentarse como primer intento.
No modifica el código, las huellas ni los resultados de las 75 generaciones completas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

HUELLA_ESPERADA = "711fc1b25110ebb27ad1d7279e0b9743fbd4d63f646c4ccc6fbea542e7dbf7d9"
PETICION_ESPERADA = "f59a50f5ec0e705fd5d20ec8526858fc13ffee37258f0618eeead2eac2348923"
CLAVES_MODELO = ["modelo", "linea_base", "R11", "generacion", PETICION_ESPERADA, "0"]
CLAVES_ETAPA = ["etapa", "linea_base", "R11", "generacion"]
COMPLETADAS = {"agente": 42, "rag": 23, "linea_base": 10}
PLANEADAS = {"agente": 42, "rag": 23, "linea_base": 23}
CARPETA_RESPALDO = "recuperacion_r11_intento_1"


class ErrorRecuperacion(ValueError):
    pass


def _canonico(dato) -> bytes:
    return json.dumps(dato, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _ruta(journal: Path, claves: list[str]) -> Path:
    return journal / (_sha(_canonico(claves)) + ".json")


def _bytes(ruta: Path) -> bytes:
    if ruta.is_symlink() or not ruta.is_file() or ruta.stat().st_size > 20_000_000:
        raise ErrorRecuperacion("Falta un archivo regular verificable de la corrida.")
    return ruta.read_bytes()


def _json(ruta: Path) -> tuple[dict, bytes]:
    raw = _bytes(ruta)
    dato = json.loads(raw.decode("utf-8"))
    if not isinstance(dato, dict):
        raise ErrorRecuperacion("Un registro de la corrida no tiene estructura válida.")
    return dato, raw


@contextmanager
def _bloquear(journal: Path):
    import fcntl

    if journal.is_symlink() or not journal.is_dir():
        raise ErrorRecuperacion("El journal no es una carpeta regular.")
    descriptor = os.open(journal / ".lock", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ErrorRecuperacion("El candado del journal no es un archivo regular.")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ErrorRecuperacion("La corrida está ocupada; no se permite preparar una recuperación concurrente.") from None
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _verificar(raiz: Path, carpeta: Path, journal: Path, huella_esperada: str) -> dict:
    respaldo = journal / CARPETA_RESPALDO
    if os.path.lexists(respaldo):
        raise ErrorRecuperacion("Ya existe una preparación de R11; no se habilita otro intento ni se modifica el respaldo.")
    manifiesto, manifiesto_raw = _json(carpeta / "manifiesto_evaluacion.json")
    huella = manifiesto.get("huella")
    if not isinstance(huella, dict) or manifiesto.get("huella_sha256") != huella_esperada \
            or _sha(_canonico(huella)) != huella_esperada \
            or manifiesto.get("estado") not in {"en_curso", "incompleto"}:
        raise ErrorRecuperacion("La corrida no acredita la huella original esperada o ya está cerrada.")
    fuentes = huella.get("archivos_sha256")
    if not isinstance(fuentes, dict) or not fuentes:
        raise ErrorRecuperacion("La huella no contiene las fuentes congeladas.")
    for nombre, esperado in fuentes.items():
        relativa = Path(nombre)
        if relativa.is_absolute() or ".." in relativa.parts or _sha(_bytes(raiz / relativa)) != esperado:
            raise ErrorRecuperacion("Cambió una fuente congelada; no se altera ni sustituye la huella para continuar.")
    if (carpeta / "resumen.json").exists():
        raise ErrorRecuperacion("Ya existe un resumen final; esta recuperación no es aplicable.")
    parcial, parcial_raw = _json(carpeta / "resumen_parcial.json")
    if parcial.get("estado") != "incompleto" or parcial.get("no_son_metricas_finales") is not True \
            or parcial.get("generaciones_completas") != COMPLETADAS \
            or parcial.get("generaciones_planeadas") != PLANEADAS:
        raise ErrorRecuperacion("El progreso ya no corresponde a las 75 de 88 generaciones esperadas.")
    if any(type(v) is not int for campo in ("generaciones_completas", "generaciones_planeadas") for v in parcial[campo].values()):
        raise ErrorRecuperacion("Los conteos del progreso no son enteros válidos.")
    hashes, generaciones, metricas, modelos_completos, ambiguos = {}, {}, {}, 0, []
    for ruta in journal.glob("*.json"):
        registro, raw = _json(ruta)
        claves = registro.get("claves")
        if not isinstance(claves, list) or not claves or any(not isinstance(c, str) for c in claves) \
                or ruta != _ruta(journal, claves):
            raise ErrorRecuperacion("El journal contiene una clave o un nombre de registro inválido.")
        hashes[ruta.name] = _sha(raw)
        estado = registro.get("estado")
        if estado == "completo" and ("resultado" not in registro or registro.get("resultado_sha256") != _sha(_canonico(registro["resultado"]))):
            raise ErrorRecuperacion("Un resultado completo no supera su comprobación de integridad.")
        if claves[0] == "modelo":
            if estado == "completo":
                modelos_completos += 1
            else:
                ambiguos.append(claves)
        if claves[0] == "etapa":
            if len(claves) != 4 or claves[1] not in COMPLETADAS:
                raise ErrorRecuperacion("El journal contiene una etapa no reconocida.")
            if estado != "completo" and claves != CLAVES_ETAPA:
                raise ErrorRecuperacion("Existe otra etapa sin completar; no se aplica la excepción de R11.")
            if estado == "completo":
                destino = generaciones if claves[3] == "generacion" else metricas if claves[3] == "metricas" else None
                if destino is None:
                    raise ErrorRecuperacion("La corrida ya avanzó a calificación; esta recuperación no es aplicable.")
                destino.setdefault(claves[1], set()).add(claves[2])
    if ambiguos != [CLAVES_MODELO]:
        raise ErrorRecuperacion("R11 no es la única llamada de modelo sin desenlace; no se permite reiniciarla.")
    if {s: len(generaciones.get(s, set())) for s in COMPLETADAS} != COMPLETADAS or generaciones != metricas:
        raise ErrorRecuperacion("No se verificaron las 75 generaciones y sus métricas completas.")
    modelo_ruta = _ruta(journal, CLAVES_MODELO)
    modelo, modelo_raw = _json(modelo_ruta)
    if modelo.get("estado") != "iniciado" or modelo.get("enviada") is not True \
            or modelo.get("peticion_sha256") != PETICION_ESPERADA or modelo.get("modelo") != "gpt-6.2-sol" \
            or any(k in modelo for k in ("resultado", "resultado_sha256", "error", "fin_utc", "segundos")):
        raise ErrorRecuperacion("R11 no coincide con el envío original sin desenlace esperado.")
    etapa_ruta = _ruta(journal, CLAVES_ETAPA)
    etapa_raw = None
    if etapa_ruta.exists():
        etapa, etapa_raw = _json(etapa_ruta)
        if etapa.get("estado") != "iniciado" or any(k in etapa for k in ("resultado", "resultado_sha256", "error", "fin_utc")):
            raise ErrorRecuperacion("La etapa R11 ya tiene otro estado; no se modifica.")
    return {"hashes": hashes, "modelo_ruta": modelo_ruta, "modelo_raw": modelo_raw, "etapa_raw": etapa_raw,
            "manifiesto_sha256": _sha(manifiesto_raw), "parcial_sha256": _sha(parcial_raw),
            "modelos_completos": modelos_completos, "fuentes_congeladas": len(fuentes)}


def _guardar_privado(ruta: Path, raw: bytes) -> None:
    descriptor = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as archivo:
        archivo.write(raw)
        archivo.flush()
        os.fsync(archivo.fileno())
    if _bytes(ruta) != raw:
        raise ErrorRecuperacion("No se pudo verificar una copia; el registro activo no se retiró.")


def preparar_recuperacion(raiz: Path, *, aplicar: bool = False, huella_esperada: str = HUELLA_ESPERADA) -> dict:
    """La huella inyectable sólo se usa en fixtures; la CLI fija la huella canónica."""
    raiz = Path(raiz).resolve()
    carpeta = raiz / "resultados/codex_suscripcion/evaluacion/banco"
    if carpeta.is_symlink():
        raise ErrorRecuperacion("La corrida no puede ser un enlace simbólico.")
    journal = carpeta / ".progreso"
    with _bloquear(journal):
        verificado = _verificar(raiz, carpeta, journal, huella_esperada)
        resumen = {"estado": "verificado", "aplicado": False, "huella_sha256": huella_esperada,
                   "generaciones_conservadas": 75, "modelos_completos_conservados": verificado["modelos_completos"],
                   "fuentes_congeladas": verificado["fuentes_congeladas"], "reintento_permitido": 1,
                   "tokens_intento_previo": "desconocidos", "duracion_intento_previo": "desconocida"}
        if not aplicar:
            return resumen
        respaldo = journal / CARPETA_RESPALDO
        respaldo.mkdir(mode=0o700)
        copias = {"modelo_original.json": verificado["modelo_raw"]}
        if verificado["etapa_raw"] is not None:
            copias["etapa_original.json"] = verificado["etapa_raw"]
        for nombre, raw in copias.items():
            _guardar_privado(respaldo / nombre, raw)
        auditoria = {
            "version": 1, "tipo": "preparacion_unica_reintento_R11", "fecha_utc": datetime.now(timezone.utc).isoformat(),
            "huella_original_sha256": huella_esperada, "manifiesto_original_sha256": verificado["manifiesto_sha256"],
            "resumen_parcial_original_sha256": verificado["parcial_sha256"],
            "claves_modelo_original": CLAVES_MODELO, "archivo_activo_retirado": verificado["modelo_ruta"].name,
            "intento_previo": {"numero": 1, "estado": "sin_desenlace_no_adjudicado", "tokens": None,
                               "tokens_estado": "desconocidos", "duracion_s": None, "duracion_estado": "desconocida"},
            "continuacion": {"numero_intento_auditado": 2, "maximo_reintentos": 1,
                             "ordinal_journal_reutilizado": 0, "no_es_primer_intento": True,
                             "latencia": "El tiempo del nuevo intento no incluye la duración desconocida del envío anterior."},
            "sin_efectos_sql": True, "generaciones_conservadas": COMPLETADAS,
            "modelos_completos_conservados": verificado["modelos_completos"],
            "copias": {n: {"sha256": _sha(raw), "bytes": len(raw)} for n, raw in copias.items()},
            "registros_activos_antes_sha256": verificado["hashes"],
        }
        _guardar_privado(respaldo / "auditoria.json", json.dumps(auditoria, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8") + b"\n")
        # Volver a verificar el snapshot bajo el mismo candado antes del único retiro.
        for nombre, esperado in verificado["hashes"].items():
            if _sha(_bytes(journal / nombre)) != esperado:
                raise ErrorRecuperacion("Cambió el journal durante la preparación; no se retiró el registro activo.")
        if _sha(_bytes(carpeta / "manifiesto_evaluacion.json")) != verificado["manifiesto_sha256"] \
                or _sha(_bytes(carpeta / "resumen_parcial.json")) != verificado["parcial_sha256"]:
            raise ErrorRecuperacion("Cambió la corrida durante la preparación; no se retiró el registro activo.")
        verificado["modelo_ruta"].unlink()
        return {**resumen, "estado": "preparado", "aplicado": True,
                "aviso": "La siguiente ejecución de R11 será un segundo intento; el desenlace y uso anteriores siguen desconocidos."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument("--verificar", action="store_true", help="sólo verificar, sin cambios (modo predeterminado)")
    modo.add_argument("--aplicar", action="store_true", help="archivar el envío ambiguo y habilitar una única continuación")
    args = parser.parse_args()
    try:
        resultado = preparar_recuperacion(Path(__file__).resolve().parents[1], aplicar=args.aplicar)
    except (ErrorRecuperacion, OSError, ValueError, UnicodeError) as error:
        mensaje = str(error) if isinstance(error, ErrorRecuperacion) else "No se pudo verificar la corrida; no se habilitó una recuperación."
        print(json.dumps({"estado": "bloqueado", "aplicado": False, "mensaje": mensaje}, ensure_ascii=False))
        return 2
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
