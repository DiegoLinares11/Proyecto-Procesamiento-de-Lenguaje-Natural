"""Fallas simuladas para la evaluación y la demo: API del generador caída, base vectorial caída y un
documento envenenado. Sirven para mostrar la degradación controlada sin apagar nada de verdad."""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Callable
from contextlib import nullcontext
from types import MappingProxyType
from typing import Literal

import psycopg

from tickets_rag import herramientas as H
from tickets_rag.banco import INSTRUCCION_ENVENENADA
from tickets_rag.grafo import construir_grafo
from tickets_rag.modelo import ErrorModelo

Falla = Literal["modelo", "vectores", "documento_envenenado"]
FALLAS: tuple[str, ...] = ("modelo", "vectores", "documento_envenenado")


class ClienteCaido:
    """La API del generador no responde. El clasificador sigue con el cliente real."""

    def generar(self, **_):
        raise ErrorModelo("transporte", transitorio=True)


class ConexionCaida:
    """Cualquier uso de la conexión a pgvector falla como si la base se hubiera caído."""

    def __getattr__(self, _nombre):
        def falla(*_a, **_k):
            raise psycopg.OperationalError("falla simulada: la base vectorial no responde")
        return falla


@dataclasses.dataclass(frozen=True)
class _BusquedaEnvenenada:
    """Modifica una copia de la salida, nunca los chunks ni el resultado del recuperador compartido."""

    original: Callable

    def __call__(self, recursos, contexto, entrada):
        resultado = copy.deepcopy(self.original(recursos, contexto, entrada))
        fragmentos = resultado.get("fragmentos") or []
        if fragmentos:
            fragmentos[0]["text"] += INSTRUCCION_ENVENENADA
        return resultado


def _recursos_envenenados(recursos: H.Recursos) -> H.Recursos:
    """Configura la herramienta solo en los recursos del grafo que solicita la simulación.

    El pool recibe estos recursos explícitamente, por lo que no depende de variables de contexto
    que puedan perderse al cambiar de hilo. El mapa es una copia inmutable y conserva los overrides
    que ya tuviera el llamador. Construir otra variante sobre ella no duplica la instrucción.
    """
    locales = dict(recursos.herramientas_locales or {})
    original = locales.get("search_docs", H.HERRAMIENTAS["search_docs"])
    if not isinstance(original.funcion, _BusquedaEnvenenada):
        locales["search_docs"] = dataclasses.replace(original, funcion=_BusquedaEnvenenada(original.funcion))
    return dataclasses.replace(recursos, herramientas_locales=MappingProxyType(locales))


def grafo_con_falla(recursos: H.Recursos, cliente, checkpointer, falla: Falla | None = None):
    """El grafo de siempre, o una variante con la falla pedida."""
    if falla == "modelo":
        return construir_grafo(recursos, ClienteCaido(), checkpointer)
    if falla == "vectores":
        procedimientos, casos = copy.copy(recursos.procedimientos), copy.copy(recursos.casos)
        procedimientos.conexion = casos.conexion = ConexionCaida()
        return construir_grafo(dataclasses.replace(recursos, procedimientos=procedimientos, casos=casos), cliente, checkpointer)
    if falla == "documento_envenenado":
        return construir_grafo(_recursos_envenenados(recursos), cliente, checkpointer)
    return construir_grafo(recursos, cliente, checkpointer)


def contexto_de_falla(falla: Falla | None):
    """Compatibilidad con la demo y el benchmark: las fallas las aplica grafo_con_falla.

    Este contexto no modifica registros globales ni requiere limpieza o un candado entre solicitudes.
    Puede anidarse o terminar por una excepción sin afectar a otros grafos.
    """
    return nullcontext()
