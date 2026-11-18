"""Journal privado y reanudación conservadora de la evaluación, sin prompts ni credenciales.

Los resultados estructurados se conservan sin pérdida en archivos 0600 dentro de
una carpeta 0700 ignorada por Git. Son necesarios para reproducir los primeros
votos y las etapas internas de Ragas sin repetir inferencias. No son un export
público. Una operación enviada sin resultado queda ambigua y no se repite.
"""

from __future__ import annotations

import contextvars
import copy
import dataclasses
import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from tickets_rag.modelo import Bloque, ClienteModelo, ErrorModelo, ResultadoModelo, UsoModelo

_BLOQUEOS_MODELO = {"cuota", "autenticacion", "configuracion", "modelo", "herramienta_no_permitida"}


class ErrorProgreso(ErrorModelo):
    """Es bloqueo de configuración para que juez/grafo/Ragas no continúen el lote."""

    def __init__(self, causa="integridad", identificador=None):
        super().__init__("configuracion")
        self.causa = causa if causa in {"integridad", "existente", "ocupado", "envio_incierto", "sql_incierto", "cambio_peticion", "recursos_ocupados", "dependencia_ragas"} else "integridad"
        self.identificador = identificador if isinstance(identificador, str) and len(identificador) <= 100 else None


def ahora():
    return datetime.now(timezone.utc).isoformat()


def canonico(valor):
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(valor):
    return hashlib.sha256(canonico(valor)).hexdigest()


def sha_archivo(ruta):
    return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


def escribir_atomico(ruta: Path, valor, *, privado=False):
    escribir_bytes_atomico(ruta, json.dumps(valor, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8") + b"\n", privado=privado)


def escribir_bytes_atomico(ruta: Path, datos: bytes, *, privado=False):
    ruta.parent.mkdir(parents=True, exist_ok=True, mode=0o700 if privado else 0o755)
    temporal = ruta.with_name(f".{ruta.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(temporal, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600 if privado else 0o644)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(datos)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporal, ruta)
    finally:
        temporal.unlink(missing_ok=True)


def error_seguro(error):
    salida = {"tipo": type(error).__name__}
    if isinstance(error, ErrorModelo):
        salida["codigo_modelo"] = error.codigo
    if isinstance(error, ErrorProgreso):
        salida.update(causa=error.causa, identificador=error.identificador)
    return salida


class ProgresoEvaluacion:
    def __init__(self, salida: Path, huella: dict, *, reanudar=False):
        self.salida, self.huella = Path(salida), copy.deepcopy(huella)
        self.privado = self.salida / ".progreso"
        self._candado = threading.RLock()
        self._lock = None
        self.reanudar = reanudar
        self.manifiesto = None
        self._condicion_trabajos = threading.Condition()
        self._trabajos = {}
        self._trabajos_terminados = []

    @contextmanager
    def trabajo_herramienta(self, sistema, caso, nombre):
        """Seguimiento efímero: ninguna escritura/I/O dentro del plazo del worker."""
        clave, inicio = uuid.uuid4().hex, time.monotonic()
        dato = {"sistema": sistema, "id": caso, "herramienta": nombre}
        with self._condicion_trabajos:
            self._trabajos[clave] = dato
        try:
            yield
        finally:
            with self._condicion_trabajos:
                self._trabajos.pop(clave, None)
                self._trabajos_terminados.append({**dato, "segundos": round(time.monotonic()-inicio, 6)})
                self._condicion_trabajos.notify_all()

    def esperar_herramientas(self, timeout):
        inicio = time.monotonic()
        with self._condicion_trabajos:
            activos_iniciales = len(self._trabajos)
            while self._trabajos:
                restante = timeout-(time.monotonic()-inicio)
                if restante <= 0:
                    break
                self._condicion_trabajos.wait(timeout=restante)
            return {"drenado": not self._trabajos, "espera_s": round(time.monotonic()-inicio, 6),
                    "limite_s": timeout, "activos_iniciales": activos_iniciales,
                    "activos": copy.deepcopy(list(self._trabajos.values())),
                    "trabajos_terminados": copy.deepcopy(self._trabajos_terminados)}

    def __enter__(self):
        if self.salida.is_symlink() or self.privado.is_symlink():
            raise ErrorProgreso("integridad")
        existe = self.salida.exists() and any(self.salida.iterdir())
        if existe and not reanudar_valido(self.salida, self.huella, self.reanudar):
            raise ErrorProgreso("existente")
        self.privado.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.privado.chmod(0o700)
        fd = os.open(self.privado / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        self._lock = os.fdopen(fd, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self._lock.write(b"0"); self._lock.flush(); self._lock.seek(0)
                msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            ruta = self.salida / "manifiesto_evaluacion.json"
            if ruta.exists():
                if not self.reanudar:
                    raise ErrorProgreso("existente")
                self.manifiesto = self.leer(ruta)
                if self.manifiesto.get("huella") != self.huella:
                    raise ErrorProgreso("integridad")
                self.manifiesto["reanudaciones"] += 1
            else:
                if self.reanudar or existe:
                    raise ErrorProgreso("integridad")
                self.manifiesto = {"version": 1, "inicio_utc": ahora(), "estado": "en_curso",
                                   "huella": self.huella, "huella_sha256": digest(self.huella), "reanudaciones": 0,
                                   "errores": [], "limpieza_acciones": "pendiente",
                                   "privacidad": "cache estructurada privada 0700/0600, sin prompts/auth/stdout",
                                   "latencias": "tiempo activo acumulado por caso; excluye espera entre reanudaciones"}
            self.manifiesto["estado"] = "en_curso"
            self.guardar_manifiesto()
            return self
        except BlockingIOError:
            self._lock.close(); self._lock = None
            raise ErrorProgreso("ocupado") from None
        except Exception:
            self._lock.close(); self._lock = None
            raise

    def __exit__(self, tipo, error, tb):
        try:
            if error is not None and self.manifiesto is not None:
                self.manifiesto["estado"] = "incompleto"
                self.manifiesto["errores"].append({"fecha_utc": ahora(), **error_seguro(error)})
                self.guardar_manifiesto()
        finally:
            if self._lock is not None:
                self._lock.close(); self._lock = None

    def guardar_manifiesto(self):
        escribir_atomico(self.salida / "manifiesto_evaluacion.json", self.manifiesto)

    @staticmethod
    def leer(ruta):
        try:
            ruta = Path(ruta)
            if ruta.is_symlink() or ruta.stat().st_size > 20_000_000:
                raise ValueError
            return json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            raise ErrorProgreso("integridad") from None

    def ruta(self, *claves):
        return self.privado / (digest(list(claves)) + ".json")

    def obtener(self, *claves):
        ruta = self.ruta(*claves)
        if not ruta.exists():
            return None
        registro = self.leer(ruta)
        if not isinstance(registro, dict) or registro.get("claves") != list(claves):
            raise ErrorProgreso("integridad")
        if registro.get("estado") == "completo" and registro.get("resultado_sha256") != digest(registro.get("resultado")):
            raise ErrorProgreso("integridad")
        if registro.get("estado") == "fallido" and registro.get("error_sha256") != digest(registro.get("error")):
            raise ErrorProgreso("integridad")
        return registro

    def guardar(self, claves, registro):
        with self._candado:
            datos = {**registro, "claves": list(claves)}
            if datos.get("estado") == "completo":
                datos["resultado_sha256"] = digest(datos.get("resultado"))
            if datos.get("estado") == "fallido":
                datos["error_sha256"] = digest(datos.get("error"))
            escribir_atomico(self.ruta(*claves), datos, privado=True)

    def operacion(self, claves, peticion, funcion, *, segura_repetir=False):
        with self._candado:
            anterior = self.obtener(*claves)
            huella = digest(peticion)
            if anterior:
                if anterior.get("peticion_sha256") != huella:
                    raise ErrorProgreso("cambio_peticion", "/".join(claves))
                if anterior["estado"] == "completo":
                    return copy.deepcopy(anterior["resultado"])
                if not segura_repetir:
                    raise ErrorProgreso("sql_incierto", "/".join(claves[:4]))
            registro = {"estado": "iniciado", "peticion_sha256": huella, "inicio_utc": ahora()}
            self.guardar(claves, registro)
        try:
            resultado = funcion()
        except BaseException as error:
            self.guardar(claves, {**registro, "estado": "incompleto", "error": error_seguro(error)})
            raise
        self.guardar(claves, {**registro, "estado": "completo", "resultado": resultado, "fin_utc": ahora()})
        return resultado

    def etapa(self, sistema, caso, nombre, funcion):
        claves = ("etapa", sistema, caso, nombre)
        previo = self.obtener(*claves)
        if previo and previo["estado"] == "completo":
            return copy.deepcopy(previo["resultado"])
        tiempo = (previo or {}).get("tiempo_activo_s", 0.0)
        inicio = time.perf_counter()
        registro = {"estado": "iniciado", "inicio_utc": ahora(), "tiempo_activo_s": tiempo}
        self.guardar(claves, registro)
        try:
            resultado = funcion()
        except BaseException as error:
            registro.update(estado="incompleto", tiempo_activo_s=round(tiempo + time.perf_counter()-inicio, 6), error=error_seguro(error))
            self.guardar(claves, registro)
            raise
        registro.update(estado="completo", tiempo_activo_s=round(tiempo + time.perf_counter()-inicio, 6), resultado=resultado, fin_utc=ahora())
        if nombre == "generacion" and isinstance(resultado, dict) and "segundos" in resultado:
            resultado["segundos_intento_final"] = resultado["segundos"]
            resultado["segundos"] = round(registro["tiempo_activo_s"], 3)
            resultado["latencia_medicion"] = "tiempo activo acumulado; excluye espera entre reanudaciones"
        self.guardar(claves, registro)
        return resultado

    def terminar(self):
        self.manifiesto.update(estado="completo", fin_utc=ahora())
        self.guardar_manifiesto()

    def fallos_modelo(self):
        """Solo metadatos seguros; los tokens de intentos sin respuesta son desconocidos."""
        fallos = []
        for ruta in sorted(self.privado.glob("*.json")):
            dato = self.leer(ruta)
            claves = dato.get("claves", [])
            if len(claves) != 6 or claves[0] != "modelo":
                continue
            dato = self.obtener(*claves)
            if dato.get("estado") == "fallido":
                fallos.append({"sistema": claves[1], "id": claves[2], "etapa": claves[3],
                               "ocurrencia": int(claves[5]), "codigo": dato["error"]["codigo_modelo"],
                               "segundos": dato["segundos"], "tokens": None, "tokens_estado": "desconocidos",
                               "reintentada": False})
        return fallos


def reanudar_valido(salida, huella, reanudar):
    if not reanudar:
        return False
    ruta = Path(salida) / "manifiesto_evaluacion.json"
    if not ruta.is_file():
        return False
    registro = ProgresoEvaluacion.leer(ruta)
    return (registro.get("huella") == huella and registro.get("huella_sha256") == digest(huella)
            and registro.get("estado") in {"en_curso", "incompleto", "completo"})


class ClientePersistente(ClienteModelo):
    """Replay por huella y número de ocurrencia; mantiene votos repetidos intencionales."""

    def __init__(self, progreso, ambito, *, generador_falso=None, **kwargs):
        super().__init__(**kwargs)
        self.progreso, self.ambito = progreso, tuple(ambito)
        self.generador_falso = generador_falso
        self._conteos = {}
        self._orden = []
        self.operaciones_sensibles = set()
        self._mutex = threading.RLock()
        self._actual = contextvars.ContextVar("llamada_evaluacion", default=None)
        self.detenido = None

    def conteos(self):
        with self._mutex:
            return dict(self._conteos)

    def orden(self):
        with self._mutex:
            return list(self._orden)

    def avanzar(self, delta, orden):
        with self._mutex:
            for huella in orden:
                registro = self.progreso.obtener("orden_modelo", *self.ambito, str(len(self._orden)))
                if not registro or registro.get("peticion_sha256") != huella:
                    raise ErrorProgreso("cambio_peticion", "/".join(self.ambito))
                self._orden.append(huella)
            for h, n in delta.items():
                if not isinstance(h, str) or type(n) is not int or n < 0:
                    raise ErrorProgreso("integridad")
                self._conteos[h] = self._conteos.get(h, 0) + n

    def comprobar(self):
        if self.detenido is not None:
            raise self.detenido
        for claves in self.operaciones_sensibles:
            registro = self.progreso.obtener(*claves)
            if registro and registro.get("estado") != "completo":
                self.detenido = ErrorProgreso("sql_incierto", "/".join(claves[:4]))
                raise self.detenido

    def _ejecutar(self, *args, **kwargs):
        self.marcar_envio()
        return super()._ejecutar(*args, **kwargs)

    def marcar_envio(self):
        actual = self._actual.get()
        if actual is None:
            raise ErrorProgreso("integridad")
        claves, registro = actual
        registro["enviada"] = True
        self.progreso.guardar(claves, registro)

    def generar(self, *, modelo, sistema, mensajes, esquema, herramientas=None, permitir_herramientas=True, esfuerzo="medium"):
        self.comprobar()
        definicion = esquema.model_json_schema() if isinstance(esquema, type) and issubclass(esquema, BaseModel) else esquema
        argumentos = dict(modelo=modelo, sistema=sistema, mensajes=mensajes, esquema=definicion,
                          herramientas=herramientas, permitir_herramientas=permitir_herramientas, esfuerzo=esfuerzo)
        huella = digest(argumentos)
        with self._mutex:
            orden_claves = ("orden_modelo", *self.ambito, str(len(self._orden)))
            orden_previo = self.progreso.obtener(*orden_claves)
            if orden_previo and orden_previo.get("peticion_sha256") != huella:
                raise ErrorProgreso("cambio_peticion", "/".join(self.ambito))
            if not orden_previo:
                self.progreso.guardar(orden_claves, {"estado": "declarado", "peticion_sha256": huella})
            self._orden.append(huella)
            indice = self._conteos.get(huella, 0)
            self._conteos[huella] = indice + 1
        claves = ("modelo", *self.ambito, huella, str(indice))
        previo = self.progreso.obtener(*claves)
        if previo and previo["estado"] == "completo":
            return self._restaurar(previo["resultado"], esquema)
        if previo and previo["estado"] == "fallido":
            error = ErrorModelo(previo["error"]["codigo_modelo"], transitorio=previo["error"].get("transitorio", False))
            if error.codigo in _BLOQUEOS_MODELO:
                self.detenido = error
            raise error
        if previo and previo.get("enviada"):
            self.detenido = ErrorProgreso("envio_incierto", "/".join(self.ambito))
            raise self.detenido
        registro = {"estado": "iniciado", "peticion_sha256": huella, "enviada": False,
                    "modelo": modelo, "inicio_utc": ahora()}
        self.progreso.guardar(claves, registro)
        token = self._actual.set((claves, registro))
        inicio = time.perf_counter()
        try:
            llamar = self.generador_falso or super().generar
            r = llamar(modelo=modelo, sistema=sistema, mensajes=mensajes, esquema=esquema,
                       herramientas=herramientas, permitir_herramientas=permitir_herramientas, esfuerzo=esfuerzo)
            if getattr(r, "proveedor", None) != "codex_subscription" or getattr(r, "modo_autenticacion", None) != "chatgpt":
                raise ErrorModelo("configuracion")
            resultado = {"model": r.model, "usage": dataclasses.asdict(r.usage), "content": [b.to_dict() for b in r.content],
                         "parsed_output": r.parsed_output.model_dump(mode="json") if r.parsed_output is not None else None,
                         "stop_reason": r.stop_reason, "proveedor": r.proveedor, "modo_autenticacion": r.modo_autenticacion}
            self.progreso.guardar(claves, {**registro, "estado": "completo", "resultado": resultado,
                                           "segundos": round(time.perf_counter()-inicio, 6), "fin_utc": ahora()})
            return r
        except BaseException as error:
            # Un error devuelto es un desenlace observado, no un envío de estado desconocido.
            # Un bloqueo anterior al envío permite continuar explícitamente tras recuperar cuota/auth.
            definitivo = isinstance(error, ErrorModelo) and not isinstance(error, ErrorProgreso) and (
                registro["enviada"] or error.codigo not in _BLOQUEOS_MODELO)
            self.progreso.guardar(claves, {**registro, "estado": "fallido" if definitivo else "incompleto",
                                           "error": {**error_seguro(error), "transitorio": getattr(error, "transitorio", False)},
                                           "segundos": round(time.perf_counter()-inicio, 6)})
            if isinstance(error, ErrorModelo):
                if error.codigo in _BLOQUEOS_MODELO:
                    self.detenido = error
            else:
                self.detenido = ErrorProgreso("envio_incierto", "/".join(self.ambito))
            raise
        finally:
            self._actual.reset(token)

    @staticmethod
    def _restaurar(datos, esquema):
        if datos.get("proveedor") != "codex_subscription" or datos.get("modo_autenticacion") != "chatgpt":
            raise ErrorProgreso("integridad")
        parsed = datos["parsed_output"]
        if parsed is not None and isinstance(esquema, type) and issubclass(esquema, BaseModel):
            parsed = esquema.model_validate(parsed)
        return ResultadoModelo(datos["model"], UsoModelo(**datos["usage"]), [Bloque(**b) for b in datos["content"]],
                               parsed, datos["stop_reason"], datos["proveedor"], datos["modo_autenticacion"])


def recursos_con_memoria(recursos, progreso, sistema, caso, cliente):
    """Memoriza el envelope observado por el grafo, nunca éxitos tardíos del pool.

    La recuperación conserva su función original: no escribe journal dentro del plazo de GPU.
    Únicamente una acción con efectos tiene un guard durable antes de ejecutar SQL.
    """
    from tickets_rag import herramientas as H
    sensibles = {"take_action", "escalate"}

    def observar(runtime, contexto, nombre, argumentos, permitidas, timeout):
        cliente.comprobar()
        peticion = {"nombre": nombre, "contexto": dataclasses.asdict(contexto), "argumentos": argumentos,
                    "permitidas": sorted(permitidas), "timeout": timeout}
        claves = ("herramienta_observada", sistema, caso, nombre, digest(peticion))
        efecto = ("efecto_herramienta", sistema, caso, nombre, digest(peticion))
        anterior = progreso.obtener(*claves)
        if anterior and anterior["estado"] == "completo":
            guardado = anterior["resultado"]
            cliente.avanzar(guardado["consumos_modelo"], guardado["orden_modelo"])
        else:
            # Usar los recursos efectivos recibidos por H.ejecutar: grafo_con_falla puede
            # haber inyectado búsqueda envenenada, conexión caída u otro override local.
            sin_hook = dataclasses.replace(runtime, ejecutor_observado=None)
            if nombre in sensibles:
                original = (runtime.herramientas_locales or {}).get(nombre, H.HERRAMIENTAS[nombre])
                cliente.operaciones_sensibles.add(efecto)

                def ejecutar_efecto(r, ctx, entrada):
                    return progreso.operacion(efecto, peticion, lambda: original.funcion(r, ctx, entrada))

                locales = {**(runtime.herramientas_locales or {}),
                           nombre: dataclasses.replace(original, funcion=ejecutar_efecto)}
                sin_hook = dataclasses.replace(sin_hook, herramientas_locales=locales)
            if nombre != "classify" and nombre in H.HERRAMIENTAS:
                # Los timeouts no detienen hilos activos. Solo contarlos en memoria permite
                # esperar su salida antes de cerrar conexiones/liberar pesos/cargar Ragas.
                herramienta = (sin_hook.herramientas_locales or {}).get(nombre, H.HERRAMIENTAS[nombre])
                funcion = herramienta.funcion
                def seguir_trabajo(r, ctx, entrada):
                    with progreso.trabajo_herramienta(sistema, caso, nombre):
                        return funcion(r, ctx, entrada)
                locales = {**(sin_hook.herramientas_locales or {}),
                           nombre: dataclasses.replace(herramienta, funcion=seguir_trabajo)}
                sin_hook = dataclasses.replace(sin_hook, herramientas_locales=locales)
            antes, orden_antes = cliente.conteos(), len(cliente.orden())

            def realizar():
                observado = H.ejecutar(sin_hook, contexto, nombre, argumentos, permitidas, timeout=timeout)
                # H convierte errores del clasificador en ResultadoHerramienta. Un bloqueo
                # de cuota/auth/config/modelo debe seguir deteniendo el lote, y no quedar
                # memorizado como un error de herramienta que permita saltarse el preflight.
                if cliente.detenido is not None:
                    raise cliente.detenido
                despues = cliente.conteos()
                delta = {h: n-antes.get(h, 0) for h, n in despues.items() if n != antes.get(h, 0)}
                # Si el worker empezó una acción y el llamador recibió error, no se sabe
                # si su efecto ocurrió. Una finalización tardía no borra esta ambigüedad.
                incierto = nombre in sensibles and not observado.ok and progreso.obtener(*efecto) is not None
                return {"observacion": dataclasses.asdict(observado), "consumos_modelo": delta,
                        "orden_modelo": cliente.orden()[orden_antes:], "efecto_incierto": incierto}

            guardado = progreso.operacion(claves, peticion, realizar, segura_repetir=nombre not in sensibles)
        if guardado.get("efecto_incierto"):
            cliente.detenido = ErrorProgreso("sql_incierto", "/".join(claves[:4]))
        cliente.comprobar()
        return H.ResultadoHerramienta(**copy.deepcopy(guardado["observacion"]))

    clasificador = copy.copy(recursos.clasificador)
    if clasificador is not None:
        clasificador.cliente = cliente
    return dataclasses.replace(recursos, clasificador=clasificador, ejecutor_observado=observar)


def evaluar_incremental(progreso, plan, generar, medir, *, juzgar=None, ragas=None, publicar=None, preparar=None,
                        antes_calificar=None, cliente_factory=ClientePersistente):
    """Orquesta etapas independientes; los callbacks no se invocan para etapas completas."""
    filas = {s: [] for s in plan}

    def etapa_modelo(sistema, caso, etapa, callback):
        def ejecutar():
            cliente = cliente_factory(progreso, (sistema, caso, etapa))
            valor = callback(sistema, caso, cliente)
            cliente.comprobar()
            return valor
        return progreso.etapa(sistema, caso, etapa, ejecutar)

    def emitir():
        if publicar is not None:
            publicar(filas)

    try:
        for sistema, ids in plan.items():
            for caso in ids:
                previa = progreso.obtener("etapa", sistema, caso, "generacion")
                if preparar is not None and (not previa or previa["estado"] != "completo"):
                    preparar(sistema)
                r = etapa_modelo(sistema, caso, "generacion", generar)
                fila = {"id": caso, **r}
                filas[sistema].append(fila)
                emitir()
                m = progreso.etapa(sistema, caso, "metricas", lambda s=sistema, c=caso, f=fila: medir(s, c, f))
                fila.update(m)
                emitir()
        etapas = (["juez"] if juzgar is not None else []) + (["ragas"] if ragas is not None else [])
        pendientes = any((progreso.obtener("etapa", s, id, etapa) or {}).get("estado") != "completo"
                         for s, ids in plan.items() for id in ids for etapa in etapas)
        if pendientes and antes_calificar is not None:
            antes_calificar()
        for sistema, lista in filas.items():
            for fila in lista:
                caso = fila["id"]
                if juzgar is not None:
                    calificacion = etapa_modelo(sistema, caso, "juez", lambda s, c, cl, f=fila: juzgar(s, c, f, cl))
                    if calificacion is not None:
                        fila["juez"] = calificacion
                    emitir()
                if ragas is not None:
                    resultado = etapa_modelo(sistema, caso, "ragas", lambda s, c, cl, f=fila: ragas(s, c, f, cl))
                    if resultado is not None:
                        fila["ragas"] = resultado
                    emitir()
        return filas
    except BaseException:
        emitir()
        raise
