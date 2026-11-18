"""Un solo primer intento del clasificador manual desde la demo local.

Construir el gestor y consultar estado sólo leen artefactos locales. Únicamente
``iniciar`` crea un proceso; su CLI conserva las guardas de cuota por inferencia.
No se importan clasificadores, modelos, SQL ni el script evaluador en el servidor.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from tickets_rag import config
from tickets_rag.tickets_manuales import CATEGORIAS, IDS, PRIORIDADES, cargar_manuales

VARIANTE = "juegos_criterios"
PROVEEDOR = "codex_subscription"
_SCRIPT = "scripts/evaluar_clasificador_llm.py"
_ENTORNO = frozenset({
    "PATH", "HOME", "CODEX_HOME", "CODEX_BIN", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL",
    "USER", "LOGNAME", "SYSTEMROOT", "WINDIR", "SSL_CERT_FILE", "SSL_CERT_DIR", "CODEX_MODELO_CLASIFICADOR",
})
_MENSAJES = {
    "conjunto_no_disponible": "Primero valide y congele los veinte tickets manuales y su autoría.",
    "intento_existente": "Ya existe un primer intento de este conjunto; se conserva y no se repite.",
    "arranque_fallido": "No se pudo iniciar el proceso local; no se creó una evaluación. Puede volver a pulsar Iniciar.",
    "ejecucion_no_confirmada": "El intento no terminó con resultados completos y verificables; se conservan los parciales y no se relanza.",
    "ejecutando": "La evaluación está en curso; consultar el avance no inicia nuevas llamadas.",
    "sin_iniciar": "El conjunto está congelado. Iniciar consume cuota incluida de ChatGPT/Codex.",
    "completo": "Primera evaluación completa; resultados del conjunto congelado actual.",
}


class ErrorEvaluacionManualWeb(Exception):
    def __init__(self, codigo: str, status_code: int = 409):
        self.codigo = codigo if codigo in _MENSAJES else "ejecucion_no_confirmada"
        self.status_code = status_code
        self.mensaje = self.detail = _MENSAJES[self.codigo]
        super().__init__(self.mensaje)


def identidad_canonica(casos: list[dict]) -> str:
    """Mismo algoritmo y serialización que identidad_manuales del CLI existente."""
    ordenados = sorted(casos, key=lambda t: t["ticket_id"])
    return hashlib.sha256(json.dumps(ordenados, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _leer_json(ruta: Path) -> dict | None:
    try:
        if ruta.stat().st_size > 2_000_000:
            return None
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        return datos if isinstance(datos, dict) else None
    except (OSError, ValueError, UnicodeError):
        return None


def _guardar_json(ruta: Path, contenido: dict) -> None:
    temporal = ruta.with_name(f".{ruta.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporal, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
            json.dump(contenido, archivo, ensure_ascii=False, allow_nan=False, indent=2)
            archivo.write("\n")
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(temporal, ruta)
    finally:
        temporal.unlink(missing_ok=True)


def _numero(valor, minimo=0, maximo=1) -> bool:
    return type(valor) in (int, float) and math.isfinite(valor) and minimo <= valor <= maximo


def _macro_f1(reales: list[str], predichas: list[str]) -> float:
    etiquetas = set(reales) | set(predichas)
    valores = []
    for etiqueta in etiquetas:
        tp = sum(a == b == etiqueta for a, b in zip(reales, predichas))
        fp = sum(a != etiqueta and b == etiqueta for a, b in zip(reales, predichas))
        fn = sum(a == etiqueta and b != etiqueta for a, b in zip(reales, predichas))
        valores.append(2 * tp / (2 * tp + fp + fn))
    return round(sum(valores) / len(valores), 3)


class EvaluacionManualWeb:
    """Gestor local con reserva persistente, sin reintento automático.

    ``salida_base`` es la base de herramientas del CLI; los resultados están en
    ``manuales/<identidad>`` y el control privado en ``.web/<identidad>``.
    El factory de procesos recibe los mismos argumentos que ``subprocess.Popen``.
    """

    def __init__(self, *, raiz: Path = config.RAIZ, salida_base: Path | None = None,
                 tickets_manuales: Path | None = None, proceso_factory=None):
        self.raiz = Path(raiz).resolve()
        self.salida_base = Path(salida_base).resolve() if salida_base is not None else (
            self.raiz / "resultados/codex_suscripcion/herramientas"
        )
        self.tickets_manuales = Path(tickets_manuales).resolve() if tickets_manuales is not None else (
            self.raiz / "evaluacion/tickets_manuales/congelado/tickets.jsonl"
        )
        self._crear_proceso = proceso_factory if proceso_factory is not None else subprocess.Popen
        self._candado = threading.RLock()
        self._proceso = None
        self._hilo: threading.Thread | None = None
        self._identidad_activa: str | None = None

    def _conjunto(self) -> tuple[list[dict], dict]:
        """Verifica el holdout y captura hashes sin exponer textos ni el autor."""
        try:
            manifiesto = self.tickets_manuales.parent / "manifiesto.json"
            antes = (_sha(self.tickets_manuales), _sha(manifiesto))
            casos = cargar_manuales(self.tickets_manuales, raiz=self.raiz)
            if antes != (_sha(self.tickets_manuales), _sha(manifiesto)):
                raise ValueError
            return casos, {
                "identidad_canonica": identidad_canonica(casos),
                "tickets_manuales_sha256": antes[0], "manifiesto_sha256": antes[1],
                "evaluador_sha256": _sha(self.raiz / _SCRIPT),
            }
        except (OSError, ValueError, TypeError, KeyError):
            raise ErrorEvaluacionManualWeb("conjunto_no_disponible") from None

    def _carpetas(self, identidad: str) -> tuple[Path, Path]:
        return self.salida_base / "manuales" / identidad, self.salida_base / ".web" / identidad

    @staticmethod
    def _hay_artefactos(salida: Path) -> bool:
        try:
            return salida.exists() and any(salida.iterdir())
        except OSError:
            return True

    @staticmethod
    def _progreso(salida: Path) -> tuple[int, bool]:
        """Lee sólo identificadores del journal; jamás devuelve sus resultados/votos."""
        ruta = salida / "mediciones_parciales.jsonl"
        try:
            if ruta.stat().st_size > 8_000_000:
                return 0, False
            raw = ruta.read_text(encoding="utf-8")
        except FileNotFoundError:
            return 0, False
        except (OSError, UnicodeError):
            return 0, False
        vistos, valido = set(), True
        for linea in raw.splitlines(keepends=True):
            if not linea.endswith("\n"):
                # Una escritura parcial no acredita otro ticket completado.
                valido = False
                continue
            try:
                fila = json.loads(linea)
                identificador = fila.get("ticket_id") if isinstance(fila, dict) else None
            except ValueError:
                valido = False
                continue
            if not isinstance(identificador, str) or identificador not in IDS or identificador in vistos:
                valido = False
                continue
            vistos.add(identificador)
        return len(vistos), valido and len(vistos) == 20

    def _resumen(self, salida: Path, identidad: dict, casos: list[dict], registro: dict | None) -> dict | None:
        """Sólo publica un final exit0 con hashes, variante, CSV y métricas concordantes."""
        if not registro or type(registro.get("codigo_salida")) is not int or registro["codigo_salida"] != 0:
            return None
        if registro.get("estado") != "terminado" or any(registro.get(k) != v for k, v in identidad.items()):
            return None
        if registro.get("variante") != VARIANTE or registro.get("proveedor") != PROVEEDOR:
            return None
        intento = _leer_json(salida / "intento.json")
        finales = _leer_json(salida / "clasificador_manuales.json")
        if not intento or not finales or set(finales) != {VARIANTE}:
            return None
        if intento.get("estado") != "completo" or intento.get("variante") != VARIANTE:
            return None
        if any(intento.get(k) != v for k, v in identidad.items()):
            return None
        resumen = finales[VARIANTE]
        if not isinstance(resumen, dict) or any(resumen.get(k) != identidad[k] for k in (
            "identidad_canonica", "tickets_manuales_sha256", "manifiesto_sha256"
        )):
            return None
        modelo = intento.get("modelo")
        if not isinstance(modelo, str) or not re.fullmatch(r"gpt-[A-Za-z0-9][A-Za-z0-9._-]{0,79}", modelo):
            return None
        if (resumen.get("variante") != VARIANTE or resumen.get("proveedor") != PROVEEDOR
                or resumen.get("conjunto") != "manuales" or resumen.get("tickets") != 20
                or resumen.get("modelo") != modelo):
            return None
        try:
            ruta_csv = salida / f"clasificador_manuales_{VARIANTE}.csv"
            if ruta_csv.stat().st_size > 1_000_000:
                return None
            with ruta_csv.open(encoding="utf-8", newline="") as archivo:
                filas = list(csv.DictReader(archivo))
            por_id = {f["ticket_id"]: f for f in filas}
            if len(filas) != 20 or set(por_id) != set(IDS):
                return None
            for caso in casos:
                fila = por_id[caso["ticket_id"]]
                for campo, etiquetas in (("categoria", CATEGORIAS), ("prioridad", PRIORIDADES)):
                    if fila[f"{campo}_real"] != caso[campo]:
                        return None
                    if any(fila[f"{campo}_{s}"] not in etiquetas for s in ("llm", "tfidf")):
                        return None
            for sistema in ("llm", "tfidf"):
                puntajes = resumen.get(f"macro_f1_{sistema}")
                if not isinstance(puntajes, dict) or set(puntajes) != {"categoria", "prioridad"}:
                    return None
                for campo in ("categoria", "prioridad"):
                    medido = puntajes[campo]
                    esperado = _macro_f1([f[f"{campo}_real"] for f in filas], [f[f"{campo}_{sistema}"] for f in filas])
                    if not _numero(medido) or medido != esperado:
                        return None
        except (OSError, ValueError, KeyError, TypeError, UnicodeError, csv.Error):
            return None
        seguro = {"tickets": 20, "modelo": modelo, "proveedor": PROVEEDOR, "variante": VARIANTE,
                  "macro_f1_llm": dict(resumen["macro_f1_llm"]),
                  "macro_f1_tfidf": dict(resumen["macro_f1_tfidf"])}
        for campo in ("tokens_entrada", "tokens_salida", "tickets_con_error", "revision_humana"):
            valor = resumen.get(campo)
            if type(valor) is int and valor >= 0 and (campo.startswith("tokens_") or valor <= 20):
                seguro[campo] = valor
        if _numero(resumen.get("costo_usd"), 0, 0):
            seguro["costo_usd"] = 0.0
        return seguro

    def _estado(self, casos: list[dict], identidad: dict) -> dict:
        salida, privado = self._carpetas(identidad["identidad_canonica"])
        registro = _leer_json(privado / "trabajo.json")
        reserva = (privado / "reserva.lock").exists()
        hay_control = self._hay_artefactos(privado)
        hay_intento = self._hay_artefactos(salida)
        completados, journal_completo = self._progreso(salida)
        codigo = registro.get("codigo_salida") if registro else None
        if type(codigo) is not int:
            codigo = None
        respuesta = {
            "estado": "sin_iniciar", "mensaje": _MENSAJES["sin_iniciar"], "puede_iniciar": True,
            "variante": VARIANTE, "proveedor": PROVEEDOR,
            "progreso": {"completados": completados, "total": 20}, "resumen": None,
            "codigo_salida": codigo, "identidad_canonica": identidad["identidad_canonica"],
            "tickets_manuales_sha256": identidad["tickets_manuales_sha256"],
        }
        propio_activo = (self._identidad_activa == identidad["identidad_canonica"]
                         and self._hilo is not None and self._hilo.is_alive())
        if propio_activo:
            respuesta.update(estado="ejecutando", mensaje=_MENSAJES["ejecutando"], puede_iniciar=False)
            return respuesta
        if hay_intento or reserva or registro or hay_control:
            respuesta.update(estado="incompleto", mensaje=_MENSAJES["ejecucion_no_confirmada"], puede_iniciar=False)
            # Única recuperación permitida: el sistema operativo no llegó a crear el proceso.
            if (not hay_intento and not reserva and registro and registro.get("estado") == "fallo_arranque"
                    and registro.get("proceso_creado") is False
                    and all(registro.get(k) == v for k, v in identidad.items())):
                respuesta.update(mensaje=_MENSAJES["arranque_fallido"], puede_iniciar=True)
            elif journal_completo:
                resumen = self._resumen(salida, identidad, casos, registro)
                if resumen is not None:
                    respuesta.update(estado="completo", mensaje=_MENSAJES["completo"], resumen=resumen)
        return respuesta

    def estado(self) -> dict:
        """Consulta pasiva: no crea carpetas, hilos, procesos ni llamadas de modelo."""
        with self._candado:
            try:
                casos, identidad = self._conjunto()
            except ErrorEvaluacionManualWeb:
                return {"estado": "no_disponible", "mensaje": _MENSAJES["conjunto_no_disponible"],
                        "puede_iniciar": False, "variante": VARIANTE, "proveedor": PROVEEDOR,
                        "progreso": {"completados": 0, "total": 20}, "resumen": None,
                        "codigo_salida": None, "identidad_canonica": None, "tickets_manuales_sha256": None}
            return self._estado(casos, identidad)

    def _esperar(self, proceso, privado: Path, registro: dict) -> None:
        try:
            codigo = proceso.wait()
            codigo = codigo if type(codigo) is int else None
        except Exception:
            codigo = None
        with self._candado:
            registro.update(estado="terminado", fin_utc=_ahora(), codigo_salida=codigo)
            try:
                _guardar_json(privado / "trabajo.json", registro)
            except OSError:
                # La reserva permanece; no inferir éxito ni permitir otro intento.
                pass

    def iniciar(self) -> dict:
        """Acción explícita del POST: reserva antes de Popen y nunca usa shell."""
        with self._candado:
            casos, identidad = self._conjunto()
            if self._hilo is not None and self._hilo.is_alive():
                raise ErrorEvaluacionManualWeb("intento_existente")
            actual = self._estado(casos, identidad)
            if not actual["puede_iniciar"]:
                raise ErrorEvaluacionManualWeb("intento_existente")
            salida, privado = self._carpetas(identidad["identidad_canonica"])
            try:
                privado.mkdir(parents=True, exist_ok=True, mode=0o700)
            except OSError:
                raise ErrorEvaluacionManualWeb("arranque_fallido", 503) from None
            reserva = privado / "reserva.lock"
            try:
                descriptor = os.open(reserva, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                raise ErrorEvaluacionManualWeb("intento_existente") from None
            except OSError:
                raise ErrorEvaluacionManualWeb("arranque_fallido", 503) from None
            os.close(descriptor)
            registro = {"version": 1, "estado": "reservado", "inicio_utc": _ahora(),
                        "variante": VARIANTE, "proveedor": PROVEEDOR, "proceso_creado": None,
                        "codigo_salida": None, **identidad}
            try:
                _guardar_json(privado / "trabajo.json", registro)
                entorno = {k: v for k, v in os.environ.items() if k in _ENTORNO}
                entorno.update(PYTHONPATH=str(self.raiz / "src"), PYTHONNOUSERSITE="1",
                               PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
                comando = [sys.executable, str(self.raiz / _SCRIPT), "--conjunto", "manuales", "--variante", VARIANTE,
                           "--tickets-manuales", str(self.tickets_manuales), "--salida-base", str(self.salida_base)]
                proceso = self._crear_proceso(comando, cwd=str(self.raiz), env=entorno, shell=False,
                                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL, close_fds=True)
            except OSError:
                registro.update(estado="fallo_arranque", proceso_creado=False, fin_utc=_ahora())
                try:
                    _guardar_json(privado / "trabajo.json", registro)
                    _guardar_json(privado / f"fallo_arranque_{uuid.uuid4().hex}.json", registro)
                    reserva.unlink()
                except OSError:
                    pass  # Si no puede acreditarse el fallo, se conserva la reserva.
                raise ErrorEvaluacionManualWeb("arranque_fallido", 503) from None
            except Exception:
                # Un factory no estándar pudo crear el proceso antes de fallar: no repetir.
                raise ErrorEvaluacionManualWeb("ejecucion_no_confirmada", 503) from None
            self._proceso, self._identidad_activa = proceso, identidad["identidad_canonica"]
            registro.update(estado="ejecutando", proceso_creado=True)
            try:
                _guardar_json(privado / "trabajo.json", registro)
            except OSError:
                pass  # La reserva ya protege contra duplicados tras un reinicio.
            self._hilo = threading.Thread(target=self._esperar, args=(proceso, privado, registro), daemon=True,
                                          name="evaluacion-manual-local")
            try:
                self._hilo.start()
            except Exception:
                # El proceso ya existe: conservar reserva y exigir inspección local.
                raise ErrorEvaluacionManualWeb("ejecucion_no_confirmada", 503) from None
            return self._estado(casos, identidad)
