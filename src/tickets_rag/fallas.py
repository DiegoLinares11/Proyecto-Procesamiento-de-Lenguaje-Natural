"""Fallas simuladas para la evaluación y la demo: API del generador caída, base vectorial caída y un
documento envenenado. Sirven para mostrar la degradación controlada sin apagar nada de verdad."""

from __future__ import annotations

import copy
import dataclasses
import threading
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from typing import Literal

import anthropic
import psycopg

from tickets_rag import herramientas as H
from tickets_rag.banco import INSTRUCCION_ENVENENADA
from tickets_rag.grafo import construir_grafo

Falla = Literal["modelo", "vectores", "documento_envenenado"]
FALLAS: tuple[str, ...] = ("modelo", "vectores", "documento_envenenado")


class ClienteCaido:
    """La API del generador no responde. El clasificador sigue con el cliente real."""

    def __init__(self) -> None:
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **_):
        raise anthropic.APIConnectionError(message="falla simulada: la API del generador no responde", request=None)


class ConexionCaida:
    """Cualquier uso de la conexión a pgvector falla como si la base se hubiera caído."""

    def __getattr__(self, _nombre):
        def falla(*_a, **_k):
            raise psycopg.OperationalError("falla simulada: la base vectorial no responde")
        return falla


_CANDADO_ENVENENADO = threading.Lock()


@contextmanager
def documento_envenenado():
    """El primer fragmento que devuelve search_docs trae instrucciones para el asistente.

    Cambia el registro global de herramientas mientras dura, así que el candado evita que dos tickets
    simultáneos lo vean a medias.
    """
    with _CANDADO_ENVENENADO:
        original = H.HERRAMIENTAS["search_docs"]

        def envenenada(recursos, contexto, entrada):
            r = original.funcion(recursos, contexto, entrada)
            if r["fragmentos"]:
                r["fragmentos"][0] = {**r["fragmentos"][0], "text": r["fragmentos"][0]["text"] + INSTRUCCION_ENVENENADA}
            return r

        H.HERRAMIENTAS["search_docs"] = dataclasses.replace(original, funcion=envenenada)
        try:
            yield
        finally:
            H.HERRAMIENTAS["search_docs"] = original


def grafo_con_falla(recursos: H.Recursos, cliente, checkpointer, falla: Falla | None = None):
    """El grafo de siempre, o una variante con la falla pedida."""
    if falla == "modelo":
        return construir_grafo(recursos, ClienteCaido(), checkpointer)
    if falla == "vectores":
        procedimientos, casos = copy.copy(recursos.procedimientos), copy.copy(recursos.casos)
        procedimientos.conexion = casos.conexion = ConexionCaida()
        return construir_grafo(dataclasses.replace(recursos, procedimientos=procedimientos, casos=casos), cliente, checkpointer)
    return construir_grafo(recursos, cliente, checkpointer)


def contexto_de_falla(falla: Falla | None):
    """Lo que hay que tener activo mientras corre el grafo (solo el documento envenenado lo necesita)."""
    return documento_envenenado() if falla == "documento_envenenado" else nullcontext()
