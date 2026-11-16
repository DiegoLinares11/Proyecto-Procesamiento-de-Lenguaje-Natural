"""Historial de tickets en PostgreSQL y catálogo de consultas de solo lectura (query_tickets).

El historial son los 240 tickets de F3 que están en el índice. Los 60 de prueba hacen de tickets
nuevos: todavía no están en el historial, así que ninguna consulta le revela al clasificador la
categoría correcta de un ticket que se usa para evaluarlo.

Seguridad (sección 13 del anteproyecto):
- Los textos se guardan enmascarados y sin el nombre del solicitante.
- query_tickets se conecta con el rol `tickets_lectura`, que solo puede hacer SELECT sobre esta
  tabla. Sus transacciones son de solo lectura y cada consulta se corta a los 10 s.
- No hay SQL libre: el LLM elige una consulta del catálogo y sus parámetros, que se validan con
  Pydantic antes de llegar a la base. Ninguna consulta devuelve más de 100 filas.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from enum import Enum
from typing import Literal

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from tickets_rag import config, vectores
from tickets_rag.pii import enmascarar

TICKETS = config.DATOS / "f3_tickets" / "tickets.jsonl"
ROL_LECTURA = "tickets_lectura"
VARIABLE_CLAVE_LECTURA = "TICKETS_LECTURA_PASSWORD"
MAX_FILAS = 100
TIMEOUT_MS = 10_000

CATEGORIAS = ("ACCESO", "CORREO", "EQUIPOS", "RED", "APLICACIONES", "OTRO")
PRIORIDADES = ("ALTA", "MEDIA", "BAJA")
Categoria = Literal["ACCESO", "CORREO", "EQUIPOS", "RED", "APLICACIONES", "OTRO"]
Prioridad = Literal["ALTA", "MEDIA", "BAJA"]

ESQUEMA = f"""
CREATE TABLE tickets (
    ticket_id text PRIMARY KEY CHECK (ticket_id ~ '^TCK-[0-9]{{4}}-[0-9]{{5}}$'),
    fecha_apertura timestamp NOT NULL,
    fecha_cierre timestamp NOT NULL CHECK (fecha_cierre >= fecha_apertura),
    horas_resolucion numeric GENERATED ALWAYS AS
        (round((extract(epoch FROM fecha_cierre - fecha_apertura) / 3600)::numeric, 1)) STORED,
    estado text NOT NULL,
    categoria text NOT NULL CHECK (categoria IN {CATEGORIAS}),
    categoria_secundaria text CHECK (categoria_secundaria IN {CATEGORIAS}),
    prioridad text NOT NULL CHECK (prioridad IN {PRIORIDADES}),
    escalado boolean NOT NULL,
    departamento text NOT NULL,
    canal text NOT NULL,
    seccion_manual text NOT NULL,
    version_manual text NOT NULL,
    resumen text NOT NULL,
    texto text NOT NULL,
    diagnostico text NOT NULL,
    solucion text NOT NULL
);
CREATE INDEX ON tickets (fecha_apertura);
CREATE INDEX ON tickets (categoria, prioridad);
CREATE INDEX ON tickets (seccion_manual);
"""


# ---------------------------------------------------------------- Carga (rol dueño)

def filas_historial() -> list[tuple]:
    filas = []
    for linea in TICKETS.read_text(encoding="utf-8").splitlines():
        t = json.loads(linea)
        if t["particion"] != "indice":
            continue
        resumen, texto, diagnostico, solucion = (enmascarar(t[c])[0] for c in ("resumen", "texto", "diagnostico", "solucion"))
        filas.append((
            t["ticket_id"], t["fecha_apertura"], t["fecha_cierre"], t["estado"], t["categoria"],
            t["categoria_secundaria"], t["prioridad"], t["escala_a_n2"], t["departamento"], t["canal"],
            t["seccion"], t["version_manual"], resumen, texto, diagnostico, solucion,
        ))
    return filas


def cargar_historial(conexion: psycopg.Connection, clave_lectura: str) -> int:
    """Crea la tabla, la llena y deja al rol de lectura con permiso solo sobre ella."""
    base = os.environ["POSTGRES_DB"]
    with conexion.transaction():
        conexion.execute("DROP TABLE IF EXISTS tickets")
        conexion.execute(ESQUEMA)
        with conexion.cursor() as cur:
            cur.executemany(
                "INSERT INTO tickets (ticket_id, fecha_apertura, fecha_cierre, estado, categoria, categoria_secundaria,"
                " prioridad, escalado, departamento, canal, seccion_manual, version_manual, resumen, texto,"
                " diagnostico, solucion) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                filas_historial(),
            )
        existe = conexion.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROL_LECTURA,)).fetchone()
        accion = "ALTER" if existe else "CREATE"
        rol = sql.Identifier(ROL_LECTURA)
        conexion.execute(sql.SQL(f"{accion} ROLE {{}} LOGIN PASSWORD {{}}").format(rol, sql.Literal(clave_lectura)))
        conexion.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(rol))
        conexion.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = {}").format(rol, sql.Literal(f"{TIMEOUT_MS}ms")))
        conexion.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(base)))
        conexion.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(base), rol))
        conexion.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(rol))
        conexion.execute(sql.SQL("GRANT SELECT ON tickets TO {}").format(rol))
        conexion.execute("ANALYZE tickets")
    return conexion.execute("SELECT count(*) FROM tickets").fetchone()[0]


# ---------------------------------------------------------------- Catálogo (rol de lectura)

class ErrorConsulta(Exception):
    """Error que se le devuelve al agente para que corrija la llamada. Nunca incluye datos de la base."""


class NombreConsulta(str, Enum):
    estado_ticket = "estado_ticket"
    conteo_por_categoria = "conteo_por_categoria"
    tiempo_resolucion = "tiempo_resolucion"
    tickets_por_procedimiento = "tickets_por_procedimiento"
    escalados = "escalados"


class _Parametros(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Rango(_Parametros):
    desde: date = Field(description="Fecha inicial, incluida (AAAA-MM-DD)")
    hasta: date = Field(description="Fecha final, incluida (AAAA-MM-DD)")

    @model_validator(mode="after")
    def rango_valido(self):
        if self.hasta < self.desde:
            raise ValueError("'hasta' no puede ser anterior a 'desde'")
        if (self.hasta - self.desde).days > 366:
            raise ValueError("el rango no puede pasar de 366 días")
        return self


class ParamEstado(_Parametros):
    ticket_id: str = Field(pattern=r"^TCK-\d{4}-\d{5}$", description="Por ejemplo TCK-2026-00123")


class ParamConteo(_Rango):
    pass


class ParamTiempo(_Rango):
    categoria: Categoria | None = None
    prioridad: Prioridad | None = None


class ParamProcedimiento(_Parametros):
    seccion: str = Field(pattern=r"^\d\.\d$", description="Procedimiento del manual, por ejemplo 2.1")
    limite: int = Field(default=10, ge=1, le=20)


class ParamEscalados(_Rango):
    limite: int = Field(default=20, ge=1, le=MAX_FILAS)


# Cada consulta: (modelo de parámetros, SQL fijo con parámetros nombrados, descripción para el agente)
CATALOGO: dict[NombreConsulta, tuple[type[_Parametros], str, str]] = {
    NombreConsulta.estado_ticket: (
        ParamEstado,
        """SELECT ticket_id, fecha_apertura, fecha_cierre, horas_resolucion, estado, categoria, prioridad,
                  escalado, seccion_manual, version_manual, resumen, diagnostico, solucion
           FROM tickets WHERE ticket_id = %(ticket_id)s""",
        "Estado, categoría, prioridad, fechas y solución de un ticket del historial.",
    ),
    NombreConsulta.conteo_por_categoria: (
        ParamConteo,
        """SELECT categoria, count(*) AS total,
                  count(*) FILTER (WHERE prioridad = 'ALTA') AS alta,
                  count(*) FILTER (WHERE escalado) AS escalados
           FROM tickets
           WHERE fecha_apertura >= %(desde)s AND fecha_apertura < %(hasta)s::date + 1
           GROUP BY categoria ORDER BY total DESC, categoria""",
        "Cantidad de tickets por categoría en un rango de fechas, con cuántos fueron de prioridad ALTA y escalados.",
    ),
    NombreConsulta.tiempo_resolucion: (
        ParamTiempo,
        """SELECT count(*) AS tickets,
                  round(avg(horas_resolucion), 1) AS horas_promedio,
                  round((percentile_cont(0.5) WITHIN GROUP (ORDER BY horas_resolucion))::numeric, 1) AS horas_mediana
           FROM tickets
           WHERE fecha_apertura >= %(desde)s AND fecha_apertura < %(hasta)s::date + 1
             AND (%(categoria)s::text IS NULL OR categoria = %(categoria)s)
             AND (%(prioridad)s::text IS NULL OR prioridad = %(prioridad)s)""",
        "Tiempo de resolución promedio y mediano en horas, con filtros opcionales de categoría y prioridad.",
    ),
    NombreConsulta.tickets_por_procedimiento: (
        ParamProcedimiento,
        """SELECT ticket_id, fecha_apertura, version_manual, estado, resumen, solucion
           FROM tickets WHERE seccion_manual = %(seccion)s
           ORDER BY fecha_apertura DESC LIMIT %(limite)s""",
        "Tickets más recientes resueltos con un procedimiento del manual.",
    ),
    NombreConsulta.escalados: (
        ParamEscalados,
        """SELECT ticket_id, fecha_apertura, categoria, prioridad, resumen
           FROM tickets
           WHERE escalado AND fecha_apertura >= %(desde)s AND fecha_apertura < %(hasta)s::date + 1
           ORDER BY fecha_apertura DESC LIMIT %(limite)s""",
        "Tickets escalados a N2 en un rango de fechas.",
    ),
}


def conectar_lectura() -> psycopg.Connection:
    url = vectores.url_bd(usuario=ROL_LECTURA, variable_clave=VARIABLE_CLAVE_LECTURA)
    return psycopg.connect(url, autocommit=True, connect_timeout=10, row_factory=dict_row,
                           options=f"-c statement_timeout={TIMEOUT_MS} -c default_transaction_read_only=on")


def _json(valor):
    if isinstance(valor, (date, datetime)):
        return valor.isoformat(timespec="minutes") if isinstance(valor, datetime) else valor.isoformat()
    if hasattr(valor, "is_finite"):  # Decimal
        return float(valor)
    return valor


def query_tickets(conexion: psycopg.Connection, nombre: str, parametros: dict) -> dict:
    """Ejecuta una consulta del catálogo. Lanza ErrorConsulta si la consulta o los parámetros no son válidos."""
    try:
        consulta = NombreConsulta(nombre)
    except ValueError:
        raise ErrorConsulta(f"Consulta desconocida '{nombre}'. Opciones: {', '.join(c.value for c in NombreConsulta)}") from None
    modelo, sentencia, _ = CATALOGO[consulta]
    try:
        validados = modelo.model_validate(parametros)
    except ValidationError as error:
        detalle = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'parametros'}: {e['msg']}" for e in error.errors())
        raise ErrorConsulta(f"Parámetros inválidos para {consulta.value}: {detalle}") from None
    filas = conexion.execute(sentencia, validados.model_dump()).fetchmany(MAX_FILAS + 1)
    return {
        "consulta": consulta.value,
        "parametros": json.loads(validados.model_dump_json()),
        "filas": [{k: _json(v) for k, v in f.items()} for f in filas[:MAX_FILAS]],
        "truncado": len(filas) > MAX_FILAS,
    }
