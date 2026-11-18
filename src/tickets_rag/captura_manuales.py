"""Captura local de tickets humanos: borrador privado, validación y congelación sin modelos.

No redacta, corrige ni anonimiza los textos. Los datos de autoría pertenecen a quien completa el
formulario. Conserva formatos anteriores sin completar sus declaraciones automáticamente.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError, field_validator, model_validator

from tickets_rag import config
from tickets_rag.banco_revision import validar_oficial
from tickets_rag.tickets_manuales import (
    CAMPOS_CSV, CATEGORIAS, IDS, PRIORIDADES, ErrorTicketsManuales,
    cargar_manuales, leer_csv, preparar_manuales,
)

_REVISION_MAXIMA = 2**53 - 1
_MAX_BORRADOR_BYTES = 1_000_000
_CANDADOS: dict[Path, threading.RLock] = {}
_REGISTRO_CANDADOS = threading.Lock()


class ErrorCaptura(ValueError):
    """Código HTTP y mensajes seguros; no incorpora excepciones con entradas humanas."""

    def __init__(self, codigo: int, mensaje: str, detalles: tuple[str, ...] | list[str] = ()) -> None:
        self.codigo = self.status_code = codigo
        self.mensaje = mensaje
        self.detalles = self.errores = tuple(detalles)
        super().__init__(mensaje)


class _Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Declaraciones(_Estricto):
    autoria_humana: StrictBool
    no_redacto_f3: StrictBool
    sin_ia_en_redaccion: StrictBool
    sin_copia_de_otros_conjuntos: StrictBool
    sin_datos_personales_reales: StrictBool
    reserva_exclusiva_evaluacion: StrictBool


class _AutoriaDatos(_Estricto):
    estado: Literal["pendiente", "declarado"]
    autor: Annotated[StrictStr, Field(max_length=120)]
    fecha_redaccion: Annotated[StrictStr, Field(max_length=10)] | None


class _AutoriaLegacy(_AutoriaDatos):
    declaraciones: _Declaraciones


class _Ticket(_Estricto):
    ticket_id: Annotated[StrictStr, Field(max_length=6)]
    texto: Annotated[StrictStr, Field(max_length=8000)]
    categoria: Annotated[StrictStr, Field(max_length=20)]
    prioridad: Annotated[StrictStr, Field(max_length=10)]

    @field_validator("ticket_id")
    @classmethod
    def _id(cls, valor):
        if valor not in IDS:
            raise ValueError("Identificador fuera del conjunto manual.")
        return valor

    @field_validator("categoria")
    @classmethod
    def _categoria(cls, valor):
        if valor not in ("", *CATEGORIAS):
            raise ValueError("Categoría fuera del catálogo.")
        return valor

    @field_validator("prioridad")
    @classmethod
    def _prioridad(cls, valor):
        if valor not in ("", *PRIORIDADES):
            raise ValueError("Prioridad fuera del catálogo.")
        return valor


class _Contenido(_Estricto):
    revision: Annotated[StrictInt, Field(ge=0, le=_REVISION_MAXIMA)]
    tickets: Annotated[list[_Ticket], Field(min_length=20, max_length=20)]
    autoria: _AutoriaDatos | _AutoriaLegacy

    @field_validator("tickets")
    @classmethod
    def _ids(cls, filas):
        if {f.ticket_id for f in filas} != set(IDS):
            raise ValueError("Se requiere un identificador de cada ticket manual.")
        return filas


class _Persistido(_Contenido):
    version: Literal[1, 2]

    @model_validator(mode="after")
    def _formato_autoria(self):
        if (self.version == 1) != isinstance(self.autoria, _AutoriaLegacy):
            raise ValueError("La versión guardada no corresponde al formato de autoría.")
        return self


class _ControlCongelado(_Estricto):
    version: Literal[1]
    revision: Annotated[StrictInt, Field(ge=1, le=_REVISION_MAXIMA)]
    manifiesto_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]


def _inicial() -> dict:
    return {"revision": 0,
            "tickets": [{"ticket_id": i, "texto": "", "categoria": "", "prioridad": ""} for i in IDS],
            "autoria": {"estado": "pendiente", "autor": "", "fecha_redaccion": None}}


def _revision(valor) -> int:
    if type(valor) is not int or not 0 <= valor <= _REVISION_MAXIMA:
        raise ErrorCaptura(422, "La revisión de la captura no tiene un formato válido.")
    return valor


def _bytes_json(valor: dict) -> bytes:
    return (json.dumps(valor, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _escribir_privado(ruta: Path, datos: bytes) -> None:
    descriptor = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as archivo:
        archivo.write(datos)
        archivo.flush()
        os.fsync(archivo.fileno())


class CapturaManuales:
    def __init__(self, raiz: Path = config.RAIZ, carpeta: Path | None = None) -> None:
        self.raiz = Path(raiz).resolve()
        base = Path(carpeta) if carpeta is not None else self.raiz / "evaluacion/tickets_manuales"
        self.carpeta = base if base.is_absolute() else self.raiz / base
        self.local = self.carpeta / "borrador_local"
        self.borrador = self.local / "borrador.json"
        self.congelado = self.carpeta / "congelado"
        with _REGISTRO_CANDADOS:
            self._candado = _CANDADOS.setdefault(self.carpeta.resolve(), threading.RLock())

    @contextmanager
    def _bloquear(self):
        # RLock coordina instancias/hilos y el bloqueo del archivo coordina procesos del servidor.
        with self._candado:
            try:
                if self.local.is_symlink() or self.carpeta.is_symlink():
                    raise ErrorCaptura(500, "La carpeta local de captura no es válida.")
                self.local.mkdir(parents=True, exist_ok=True, mode=0o700)
                self.local.chmod(0o700)
                flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(self.local / ".captura.lock", flags, 0o600)
                with os.fdopen(descriptor, "a+b") as archivo:
                    if os.name == "nt":
                        import msvcrt
                        if archivo.tell() == 0:
                            archivo.write(b"0")
                            archivo.flush()
                        archivo.seek(0)
                        msvcrt.locking(archivo.fileno(), msvcrt.LK_LOCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(archivo.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        if os.name == "nt":
                            archivo.seek(0)
                            msvcrt.locking(archivo.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            fcntl.flock(archivo.fileno(), fcntl.LOCK_UN)
            except OSError:
                raise ErrorCaptura(500, "No se pudo acceder al almacenamiento privado de la captura.") from None

    def _leer_borrador(self) -> dict:
        if not os.path.lexists(self.borrador):
            return _inicial()
        try:
            if self.borrador.is_symlink() or self.borrador.stat().st_size > _MAX_BORRADOR_BYTES:
                raise ValueError
            datos = _Persistido.model_validate(json.loads(self.borrador.read_text(encoding="utf-8"))).model_dump()
            datos.pop("version")
            return datos
        except (OSError, ValueError, TypeError):
            raise ErrorCaptura(422, "El borrador local no pudo verificarse; no se reemplazó su contenido.") from None

    def _snapshot(self, datos: dict, estado: str) -> dict:
        return {**datos, "version": 1 if "declaraciones" in datos["autoria"] else 2,
                "estado": estado, "categorias": list(CATEGORIAS), "prioridades": list(PRIORIDADES)}

    def _validar_banco(self) -> None:
        try:
            validar_oficial(self.raiz / "evaluacion/banco.jsonl", raiz=self.raiz)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise ErrorCaptura(422, "El banco oficial o sus referencias no superaron la validación de integridad.") from None

    def _leer_congelado(self) -> dict:
        try:
            if self.congelado.is_symlink():
                raise ValueError
            self._validar_banco()
            cargar_manuales(self.congelado / "tickets.jsonl", raiz=self.raiz)
            filas = leer_csv((self.congelado / "fuente.csv").read_bytes())
            autoria = json.loads((self.congelado / "autoria.json").read_text(encoding="utf-8"))
            control = self.congelado / "captura.json"
            revision = 0  # Un conjunto válido recibido previamente por la CLI no tiene revisión de UI.
            if os.path.lexists(control):
                if control.is_symlink() or control.stat().st_size > 4096:
                    raise ValueError
                meta = _ControlCongelado.model_validate_json(control.read_bytes())
                esperado = hashlib.sha256((self.congelado / "manifiesto.json").read_bytes()).hexdigest()
                if meta.manifiesto_sha256 != esperado:
                    raise ValueError
                revision = meta.revision
            datos = _Contenido.model_validate({"revision": revision, "tickets": filas, "autoria": autoria}).model_dump()
            return self._snapshot(datos, "congelado")
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise ErrorCaptura(422, "La carpeta congelada existe, pero no se pudo verificar su integridad.") from None

    def estado(self) -> dict:
        with self._bloquear():
            if os.path.lexists(self.congelado):
                return self._leer_congelado()
            return self._snapshot(self._leer_borrador(), "borrador")

    def _editable(self, revision: int) -> dict:
        if os.path.lexists(self.congelado):
            raise ErrorCaptura(409, "El conjunto ya tiene una carpeta congelada y no admite edición ni sobrescritura.")
        datos = self._leer_borrador()
        if datos["revision"] != revision:
            raise ErrorCaptura(409, "La captura cambió desde la última lectura; recargue antes de guardar o continuar.")
        return datos

    def guardar(self, payload) -> dict:
        try:
            datos = _Contenido.model_validate(payload).model_dump()
        except ValidationError:
            raise ErrorCaptura(422, "La captura no cumple el formato, las etiquetas o los límites permitidos.") from None
        with self._bloquear():
            self._editable(datos["revision"])
            if datos["revision"] >= _REVISION_MAXIMA:
                raise ErrorCaptura(409, "La revisión de la captura no permite otra actualización.")
            datos["revision"] += 1
            temporal = None
            try:
                descriptor, nombre = tempfile.mkstemp(prefix=".borrador-", dir=self.local)
                temporal = Path(nombre)
                with os.fdopen(descriptor, "wb") as archivo:
                    archivo.write(_bytes_json({"version": 1 if "declaraciones" in datos["autoria"] else 2, **datos}))
                    archivo.flush()
                    os.fsync(archivo.fileno())
                os.replace(temporal, self.borrador)
            except OSError:
                raise ErrorCaptura(500, "No se pudo guardar la captura local.") from None
            finally:
                if temporal is not None:
                    temporal.unlink(missing_ok=True)
            return self._snapshot(datos, "borrador")

    @contextmanager
    def _entradas(self, datos: dict):
        salida = io.StringIO(newline="")
        csv_writer = csv.DictWriter(salida, fieldnames=CAMPOS_CSV)
        csv_writer.writeheader()
        csv_writer.writerows(datos["tickets"])
        with tempfile.TemporaryDirectory(prefix=".validacion-", dir=self.local) as temporal:
            carpeta = Path(temporal)
            csv_ruta, autoria_ruta = carpeta / "entrada.csv", carpeta / "autoria.json"
            _escribir_privado(csv_ruta, salida.getvalue().encode("utf-8"))
            _escribir_privado(autoria_ruta, _bytes_json(datos["autoria"]))
            yield csv_ruta, autoria_ruta, carpeta

    def _preparar(self, datos: dict, *, publicar: bool) -> dict:
        self._validar_banco()
        try:
            with self._entradas(datos) as (csv_ruta, autoria_ruta, temporal):
                staging = temporal / "congelado" if publicar else None
                resumen = preparar_manuales(csv_ruta, autoria_ruta, raiz=self.raiz, salida=staging)
                if publicar:
                    # Verificar los hashes emitidos por el importador antes de exponer el conjunto.
                    cargar_manuales(staging / "tickets.jsonl", raiz=self.raiz)
                    control = {"version": 1, "revision": datos["revision"] + 1,
                               "manifiesto_sha256": hashlib.sha256((staging / "manifiesto.json").read_bytes()).hexdigest()}
                    _escribir_privado(staging / "captura.json", _bytes_json(control))
                    # mkdir exclusivo impide sobrescribir incluso una carpeta vacía creada por otra CLI.
                    try:
                        self.congelado.mkdir(mode=0o700)
                    except FileExistsError:
                        raise ErrorCaptura(409, "La carpeta congelada ya existe; no se sobrescribió.") from None
                    # El manifiesto se publica al final. Lectores externos rechazan una copia incompleta;
                    # los métodos de captura permanecen bajo el bloqueo durante toda la publicación.
                    for nombre in ("tickets.jsonl", "fuente.csv", "autoria.json", "captura.json", "manifiesto.json"):
                        _escribir_privado(self.congelado / nombre, (staging / nombre).read_bytes())
                return resumen
        except ErrorTicketsManuales as error:
            raise ErrorCaptura(422, "La captura todavía no cumple los requisitos para congelarse.", error.errores) from None
        except OSError:
            raise ErrorCaptura(500, "No se pudo completar la operación local; el borrador se conserva.") from None

    def validar(self, revision: int) -> dict:
        revision = _revision(revision)
        with self._bloquear():
            datos = self._editable(revision)
            resumen = self._preparar(datos, publicar=False)
            return {"revision": revision, "estado": "borrador", "valido": True, "resumen": resumen}

    def congelar(self, revision: int) -> dict:
        revision = _revision(revision)
        with self._bloquear():
            datos = self._editable(revision)
            if revision >= _REVISION_MAXIMA:
                raise ErrorCaptura(409, "La revisión de la captura no permite otra actualización.")
            self._preparar(datos, publicar=True)
            return self._leer_congelado()
