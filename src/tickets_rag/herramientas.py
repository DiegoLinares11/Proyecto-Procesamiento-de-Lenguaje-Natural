"""Herramientas del agente: contratos, permisos, límites y ejecución (sección 11 del anteproyecto).

Cada herramienta tiene un esquema Pydantic para sus argumentos, que también se envía a la API como
`input_schema` con `strict: true`. Lo que el modo estricto no admite (mínimos, máximos, patrones)
se quita del esquema enviado y lo sigue validando Pydantic: si el modelo se pasa, recibe el error
y corrige la llamada.

Lo que nunca decide el modelo:
- El rol y el ticket salen del Contexto de la sesión, no de los argumentos.
- Qué herramientas puede usar: el router define la lista permitida de cada ruta.
- Aprobar una acción: take_action solo la deja pendiente; aprueba una persona N2.

Ejecución: cada llamada tiene un límite de 10 s y un reintento ante fallas pasajeras (red, base de
datos o API). Los errores se devuelven como texto para que el modelo corrija, nunca como excepción.
"""

from __future__ import annotations

import copy
import json
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as TimeoutFuturo
from dataclasses import dataclass, field
from typing import Annotated, Literal

import anthropic
import psycopg
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tickets_rag import acciones, config, historial
from tickets_rag.lexico import IndiceBM25


@dataclass(frozen=True)
class Contexto:
    """Datos de la sesión. El agente no puede cambiarlos."""
    ticket_id: str
    rol: Literal["N1", "N2"]


class ErrorHerramienta(Exception):
    """Error que se le devuelve al modelo como tool_result con is_error."""


# ---------------------------------------------------------------- Argumentos (lo que envía el modelo)

class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntradaBusqueda(_Entrada):
    query: str = Field(description="Consulta en lenguaje natural. Si no trae lo necesario, reformúlala con otras palabras.")
    version: Literal["2026-1", "2026-2"] | None = Field(
        default=None, description="Solo si el usuario pide una versión anterior del manual; si no, null (versión vigente).")
    top_k: int = Field(default=5, ge=1, le=10, description="Cantidad de fragmentos, de 1 a 10.")


class EntradaCasos(_Entrada):
    query: str = Field(description="Descripción del problema para buscar tickets resueltos parecidos.")
    top_k: int = Field(default=3, ge=1, le=5, description="Cantidad de tickets, de 1 a 5.")


class EntradaClasificar(_Entrada):
    text: str = Field(description="Texto del ticket a clasificar.")


class _Q(_Entrada):
    pass


class QEstado(_Q, historial.ParamEstado):
    consulta: Literal["estado_ticket"]


class QConteo(_Q, historial.ParamConteo):
    consulta: Literal["conteo_por_categoria"]


class QTiempo(_Q, historial.ParamTiempo):
    consulta: Literal["tiempo_resolucion"]


class QProcedimiento(_Q, historial.ParamProcedimiento):
    consulta: Literal["tickets_por_procedimiento"]


class QEscalados(_Q, historial.ParamEscalados):
    consulta: Literal["escalados"]


class EntradaQueryTickets(_Entrada):
    peticion: Annotated[QEstado | QConteo | QTiempo | QProcedimiento | QEscalados, Field(discriminator="consulta")] = Field(
        description="Una consulta del catálogo con sus parámetros. Fechas en AAAA-MM-DD; el rango no puede pasar de 366 días."
    )


class EntradaAccion(_Entrada):
    accion: acciones.Accion = Field(description="Acción sensible que se solicita para el ticket en curso.")
    motivo: str = Field(description="Por qué hace falta, citando el procedimiento del manual que lo indica.")


# Causas de escalamiento del procedimiento 8.1 del manual. sin_evidencia la usa el grafo al abstenerse;
# el modelo no puede usarla (lo bloquea el nodo de herramientas).
CausaEscalamiento = Literal["procedimiento_exclusivo_n2", "pasos_agotados", "incidente_seguridad", "varias_personas",
                            "accion_sensible", "sin_evidencia"]
# Motivos que en realidad dicen que no hay que escalar, o que están vacíos. En la evaluación del 17 de
# noviembre el modelo llamó a escalate con «placeholder» y con «No procede escalar: el 4.3 se resuelve en N1».
RE_NO_ESCALA = re.compile(
    r"(?i)\bno\s+(?:procede|corresponde|hace\s+falta|es\s+necesario|se\s+requiere|amerita)\s+(?:escalar|el\s+escalamiento)"
    r"|\bno\s+(?:escalar|se\s+escala|escalo)\b|\bplaceholder\b|\bpor\s+completar\b")


class EntradaEscalar(_Entrada):
    causa: CausaEscalamiento = Field(
        description="Causa del procedimiento 8.1 que se cumple hoy para lo que describe el ticket: el procedimiento es "
                    "exclusivo de N2, el ticket dice que ya se aplicaron los pasos y el problema sigue, posible incidente "
                    "de seguridad, afecta a varias personas o a un proceso crítico, o hace falta una acción que solo N2 "
                    "aprueba. sin_evidencia está reservada para el sistema.")
    motivo: str = Field(description="Diagnóstico breve: qué se intentó y por qué hace falta N2. Sin datos personales.")
    fuentes: list[str] = Field(default_factory=list, max_length=10,
                               description="chunk_id de la evidencia revisada, máximo 10.")


# ---------------------------------------------------------------- Recursos compartidos

@dataclass
class Recursos:
    """Conexiones y modelos que usan las herramientas. Se crean una vez por proceso."""
    chunks: list[dict]
    bm25: IndiceBM25
    procedimientos: object | None = None          # RecuperadorHibrido sobre manual y artículos
    casos: object | None = None                   # RecuperadorHibrido sobre tickets
    conexion_vectores: psycopg.Connection | None = None
    conexion_lectura: psycopg.Connection | None = None
    conexion_acciones: psycopg.Connection | None = None
    clasificador: object | None = None
    chunk_ids: set[str] = field(default_factory=set)

    @classmethod
    def crear(cls, chunks: list[dict], cliente: anthropic.Anthropic | None = None) -> Recursos:
        from tickets_rag import vectores
        from tickets_rag.clasificador_llm import ClasificadorLLM
        from tickets_rag.recuperacion import Configuracion, RecuperadorHibrido

        bm25 = IndiceBM25(chunks)
        conexion = vectores.conectar()
        return cls(
            chunks=chunks,
            bm25=bm25,
            procedimientos=RecuperadorHibrido(chunks, Configuracion(tipos=["manual", "articulo"]), conexion=conexion, bm25=bm25),
            casos=RecuperadorHibrido(chunks, Configuracion(tipos=["ticket"]), conexion=conexion, bm25=bm25),
            conexion_vectores=conexion,
            conexion_lectura=historial.conectar_lectura(),
            conexion_acciones=acciones.conectar_acciones(),
            clasificador=ClasificadorLLM(cliente),
            chunk_ids={c["chunk_id"] for c in chunks},
        )

    def __post_init__(self) -> None:
        if not self.chunk_ids:
            self.chunk_ids = {c["chunk_id"] for c in self.chunks}

    def calentar(self) -> None:
        """Carga BGE-M3 y el reranker antes de atender: la primera carga tarda más que el límite de 10 s."""
        for recuperador in (self.procedimientos, self.casos):
            if recuperador is not None:
                recuperador.buscar("calentamiento", rol="N1")


# ---------------------------------------------------------------- Implementaciones

def _fragmento(r) -> dict:
    c = r.chunk
    return {"chunk_id": c["chunk_id"], "tipo": c["doc_type"], "source": c["source"], "page": c["page"],
            "version": c["version"], "score": round(r.score, 4), "text": c["text"]}


def _buscar_degradable(recursos: Recursos, recuperador, query: str, rol: str, version: str | None, top_k: int):
    """Búsqueda híbrida; si la base vectorial falla, sigue solo con BM25 y el reranker."""
    from tickets_rag.recuperacion import Configuracion, RecuperadorHibrido

    try:
        return recuperador.buscar(query, rol, version, top_k=top_k), False
    except psycopg.Error:
        cfg = Configuracion(usar_vectores=False, tipos=recuperador.cfg.tipos)
        respaldo = RecuperadorHibrido(recursos.chunks, cfg, bm25=recursos.bm25)
        return respaldo.buscar(query, rol, version, top_k=top_k), True


def search_docs(recursos: Recursos, contexto: Contexto, e: EntradaBusqueda) -> dict:
    resultados, degradado = _buscar_degradable(recursos, recursos.procedimientos, e.query, contexto.rol, e.version, e.top_k)
    mejor = resultados[0].score if resultados else 0.0
    return {
        "fragmentos": [_fragmento(r) for r in resultados],
        "mejor_score": round(mejor, 4),
        "evidencia_suficiente": bool(resultados) and mejor >= config.UMBRAL_TAU,
        "degradado": degradado,
    }


def buscar_casos_similares(recursos: Recursos, contexto: Contexto, e: EntradaCasos) -> dict:
    resultados, degradado = _buscar_degradable(recursos, recursos.casos, e.query, contexto.rol, None, e.top_k)
    return {
        # En F3, page es el número de registro del ticket en tickets.jsonl (sección 10 del anteproyecto).
        "casos": [{"ticket_id": r.chunk["seccion"], "procedimiento": r.chunk["seccion_manual"],
                   "categoria": r.chunk["categoria"], "score": round(r.score, 4), "text": r.chunk["text"],
                   "chunk_id": r.chunk["chunk_id"], "source": r.chunk["source"], "page": r.chunk["page"],
                   "tipo": "ticket"} for r in resultados],
        "nota": "Son ejemplos de casos parecidos, no procedimientos: la política es el manual.",
        "degradado": degradado,
    }


def classify(recursos: Recursos, contexto: Contexto, e: EntradaClasificar) -> dict:
    return recursos.clasificador.clasificar(e.text).model_dump()


def query_tickets(recursos: Recursos, contexto: Contexto, e: EntradaQueryTickets) -> dict:
    p = e.peticion
    try:
        return historial.query_tickets(recursos.conexion_lectura, p.consulta, p.model_dump(exclude={"consulta"}, mode="json"))
    except historial.ErrorConsulta as error:
        raise ErrorHerramienta(str(error)) from None


def take_action(recursos: Recursos, contexto: Contexto, e: EntradaAccion) -> dict:
    try:
        return acciones.solicitar_accion(recursos.conexion_acciones, contexto.ticket_id, e.accion, e.motivo, contexto.rol)
    except acciones.ErrorAccion as error:
        raise ErrorHerramienta(str(error)) from None


def escalate(recursos: Recursos, contexto: Contexto, e: EntradaEscalar) -> dict:
    if len(e.motivo.strip()) < 15 or RE_NO_ESCALA.search(e.motivo):
        raise ErrorHerramienta("No se escaló: el motivo está vacío o dice que no hace falta escalar. Si no hace falta, "
                               "no llames a escalate y responde con los pasos del procedimiento.")
    desconocidas = [f for f in e.fuentes if f not in recursos.chunk_ids]
    if desconocidas:
        raise ErrorHerramienta(f"Fuentes que no existen en el índice: {desconocidas}. Usa chunk_id de la evidencia.")
    try:
        return acciones.escalar(recursos.conexion_acciones, contexto.ticket_id, f"[{e.causa}] {e.motivo}", e.fuentes,
                                contexto.rol)
    except acciones.ErrorAccion as error:
        raise ErrorHerramienta(str(error)) from None


# ---------------------------------------------------------------- Registro

@dataclass(frozen=True)
class Herramienta:
    nombre: str
    descripcion: str
    entrada: type[BaseModel]
    funcion: Callable[[Recursos, Contexto, BaseModel], dict]
    roles: frozenset[str] = frozenset({"N1", "N2"})


def _descripcion_catalogo() -> str:
    return " ".join(f"{n.value}: {d}" for n, (_, _, d) in historial.CATALOGO.items())


HERRAMIENTAS: dict[str, Herramienta] = {h.nombre: h for h in (
    Herramienta("search_docs",
                "Busca en el manual de la mesa de ayuda y en los artículos de soporte de Microsoft. Devuelve fragmentos "
                "con chunk_id, fuente y página para citar, y si la evidencia es suficiente.",
                EntradaBusqueda, search_docs),
    Herramienta("buscar_casos_similares",
                "Busca tickets resueltos parecidos al actual. Sirven como apoyo, no como procedimiento.",
                EntradaCasos, buscar_casos_similares),
    Herramienta("classify",
                "Clasifica un ticket en categoría, prioridad y tipo de solicitud, con confianza por votación.",
                EntradaClasificar, classify),
    Herramienta("query_tickets",
                "Consulta datos exactos del historial de tickets, solo de lectura y con consultas fijas. " + _descripcion_catalogo(),
                EntradaQueryTickets, query_tickets),
    Herramienta("take_action",
                "Solicita una acción sensible para el ticket en curso. Queda pendiente hasta que un técnico N2 la apruebe; "
                "no se ejecuta nada al llamarla.",
                EntradaAccion, take_action),
    Herramienta("escalate",
                "Pasa el ticket en curso a N2 en este momento, con la causa del procedimiento 8.1, el diagnóstico y la "
                "evidencia revisada. Úsala solo si hoy se cumple una de esas causas. Un paso condicional del "
                "procedimiento («si el problema sigue, escale a N2») no es motivo: va en la respuesta como indicación. "
                "Si decides no escalar, no la llames.",
                EntradaEscalar, escalate),
)}

_NO_ESTRICTO = {"title", "default", "pattern", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                "minLength", "maxLength", "minItems", "maxItems", "uniqueItems", "discriminator", "format"}


def _limpiar(nodo):
    """Quita del esquema lo que el modo estricto no admite; Pydantic lo sigue validando.

    También pone primero las propiedades con `const` (el discriminador, como `consulta`). En modo estricto
    el modelo escribe las claves en el orden del esquema: con `consulta` al final, cuando la escribía ya
    había pasado los filtros opcionales y no podía agregarlos. Pedía tiempo_resolucion de RED y ALTA y
    la consulta salía sin filtros (caso H01 de la evaluación del 17 de noviembre).
    """
    if isinstance(nodo, dict):
        limpio = {}
        for clave, valor in nodo.items():
            if clave in _NO_ESTRICTO and not (clave == "format" and valor in ("date", "date-time")):
                continue
            limpio["anyOf" if clave == "oneOf" else clave] = _limpiar(valor)
        if isinstance(limpio.get("properties"), dict):
            props = limpio["properties"]
            limpio["properties"] = {**{k: v for k, v in props.items() if isinstance(v, dict) and "const" in v},
                                    **{k: v for k, v in props.items() if not (isinstance(v, dict) and "const" in v)}}
        if limpio.get("type") == "object":
            limpio["additionalProperties"] = False
        return limpio
    if isinstance(nodo, list):
        return [_limpiar(v) for v in nodo]
    return nodo


def definiciones_api(nombres: list[str]) -> list[dict]:
    """Definiciones para el parámetro `tools` de la API, en orden fijo para no romper la caché."""
    return [{"name": n, "description": HERRAMIENTAS[n].descripcion, "strict": True,
             "input_schema": _limpiar(copy.deepcopy(HERRAMIENTAS[n].entrada.model_json_schema()))}
            for n in nombres]


# ---------------------------------------------------------------- Ejecución con límites

PASAJERAS = (TimeoutFuturo, psycopg.OperationalError, anthropic.APIConnectionError, anthropic.APITimeoutError,
             anthropic.RateLimitError, anthropic.InternalServerError)
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="herramienta")


@dataclass
class ResultadoHerramienta:
    nombre: str
    ok: bool
    contenido: dict | None
    error: str | None
    segundos: float
    intentos: int

    def para_modelo(self) -> str:
        return json.dumps(self.contenido, ensure_ascii=False) if self.ok else f"Error: {self.error}"


def ejecutar(recursos: Recursos, contexto: Contexto, nombre: str, argumentos: dict, permitidas: set[str],
             timeout: float = config.TIMEOUT_HERRAMIENTA_S) -> ResultadoHerramienta:
    inicio = time.perf_counter()

    def fallo(mensaje: str, intentos: int = 0) -> ResultadoHerramienta:
        return ResultadoHerramienta(nombre, False, None, mensaje, round(time.perf_counter() - inicio, 3), intentos)

    if nombre not in HERRAMIENTAS:
        return fallo(f"La herramienta '{nombre}' no existe.")
    if nombre not in permitidas:
        return fallo(f"La herramienta '{nombre}' no está permitida en esta ruta. Permitidas: {', '.join(sorted(permitidas))}.")
    herramienta = HERRAMIENTAS[nombre]
    if contexto.rol not in herramienta.roles:
        return fallo(f"El rol {contexto.rol} no puede usar '{nombre}'.")
    try:
        entrada = herramienta.entrada.model_validate(argumentos)
    except ValidationError as error:
        detalle = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'argumentos'}: {e['msg']}" for e in error.errors())
        return fallo(f"Argumentos inválidos: {detalle}")

    intentos = 0
    while True:
        intentos += 1
        futuro = _POOL.submit(herramienta.funcion, recursos, contexto, entrada)
        try:
            contenido = futuro.result(timeout=timeout)
            return ResultadoHerramienta(nombre, True, contenido, None, round(time.perf_counter() - inicio, 3), intentos)
        except ErrorHerramienta as error:
            return fallo(str(error), intentos)
        except PASAJERAS as error:
            if intentos > config.REINTENTOS_HERRAMIENTA:
                motivo = "tardó más de 10 s" if isinstance(error, TimeoutFuturo) else type(error).__name__
                return fallo(f"El servicio no respondió ({motivo}) después de {intentos} intentos.", intentos)
