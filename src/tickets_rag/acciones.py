"""Acciones sensibles simuladas y escalamientos (take_action y escalate).

Ninguna acción toca sistemas reales: solicitar una acción la deja «pendiente», y solo un técnico
N2 puede aprobarla o rechazarla (procedimiento 8.2 del manual). Al aprobarla se marca como
ejecutada en simulación.

El rol `tickets_acciones` puede leer e insertar en estas dos tablas y cambiar el estado de una
solicitud, pero no puede borrar nada ni leer el historial ni los índices.
"""

from __future__ import annotations

import os
from typing import Literal

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from tickets_rag import vectores
from tickets_rag.pii import enmascarar

ROL_ACCIONES = "tickets_acciones"
VARIABLE_CLAVE_ACCIONES = "TICKETS_ACCIONES_PASSWORD"

# Acciones que el manual reserva para la aprobación de N2 (procedimientos 2.1, 2.4, 2.6, 3.2, 3.6 y 8.2)
ACCIONES = (
    "restablecer_contrasena",
    "restablecer_mfa",
    "desbloquear_cuenta_privilegiada",
    "aumentar_cuota_buzon",
    "recuperar_correo_respaldo",
    "cerrar_ticket_sin_confirmacion",
)
Accion = Literal[
    "restablecer_contrasena",
    "restablecer_mfa",
    "desbloquear_cuenta_privilegiada",
    "aumentar_cuota_buzon",
    "recuperar_correo_respaldo",
    "cerrar_ticket_sin_confirmacion",
]

ESQUEMA = f"""
CREATE TABLE solicitudes_accion (
    id bigserial PRIMARY KEY,
    ticket_id text NOT NULL CHECK (ticket_id ~ '^TCK-[0-9]{{4}}-[0-9]{{5}}$'),
    accion text NOT NULL CHECK (accion IN {ACCIONES}),
    motivo text NOT NULL,
    solicitado_por text NOT NULL CHECK (solicitado_por IN ('N1', 'N2')),
    estado text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'ejecutada', 'rechazada')),
    aprobado_por text,
    fecha_solicitud timestamptz NOT NULL DEFAULT now(),
    fecha_resolucion timestamptz,
    UNIQUE (ticket_id, accion)
);
CREATE TABLE escalamientos (
    ticket_id text PRIMARY KEY CHECK (ticket_id ~ '^TCK-[0-9]{{4}}-[0-9]{{5}}$'),
    motivo text NOT NULL,
    fuentes text[] NOT NULL,
    fecha timestamptz NOT NULL DEFAULT now()
);
"""


class ErrorAccion(Exception):
    """Error que se le devuelve al agente o a la persona que aprueba."""


class ErrorPermiso(ErrorAccion):
    pass


def crear_tablas(conexion: psycopg.Connection, clave_acciones: str) -> None:
    """Crea las tablas (borra las anteriores: son solo simulaciones) y el rol de acciones."""
    base = os.environ["POSTGRES_DB"]
    rol = sql.Identifier(ROL_ACCIONES)
    with conexion.transaction():
        conexion.execute("DROP TABLE IF EXISTS solicitudes_accion, escalamientos")
        conexion.execute(ESQUEMA)
        existe = conexion.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROL_ACCIONES,)).fetchone()
        accion = "ALTER" if existe else "CREATE"
        conexion.execute(sql.SQL(f"{accion} ROLE {{}} LOGIN PASSWORD {{}}").format(rol, sql.Literal(clave_acciones)))
        conexion.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '10s'").format(rol))
        conexion.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(base), rol))
        conexion.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(rol))
        conexion.execute(sql.SQL("GRANT SELECT, INSERT ON solicitudes_accion, escalamientos TO {}").format(rol))
        conexion.execute(sql.SQL("GRANT UPDATE (estado, aprobado_por, fecha_resolucion) ON solicitudes_accion TO {}").format(rol))
        conexion.execute(sql.SQL("GRANT USAGE ON SEQUENCE solicitudes_accion_id_seq TO {}").format(rol))


def conectar_acciones() -> psycopg.Connection:
    url = vectores.url_bd(usuario=ROL_ACCIONES, variable_clave=VARIABLE_CLAVE_ACCIONES)
    return psycopg.connect(url, autocommit=True, connect_timeout=10, row_factory=dict_row,
                           options="-c statement_timeout=10000")


def _rol_valido(rol: str) -> None:
    if rol not in ("N1", "N2"):
        raise ErrorPermiso(f"El rol '{rol}' no puede usar esta herramienta.")


def solicitar_accion(conexion: psycopg.Connection, ticket_id: str, accion: str, motivo: str, rol: str) -> dict:
    """Deja la acción pendiente de aprobación. Es idempotente: una sola solicitud por ticket y acción."""
    _rol_valido(rol)
    if accion not in ACCIONES:
        raise ErrorAccion(f"Acción desconocida '{accion}'. Opciones: {', '.join(ACCIONES)}")
    fila = conexion.execute(
        """INSERT INTO solicitudes_accion (ticket_id, accion, motivo, solicitado_por)
           VALUES (%s, %s, %s, %s) ON CONFLICT (ticket_id, accion) DO NOTHING
           RETURNING id, ticket_id, accion, estado""",
        (ticket_id, accion, enmascarar(motivo)[0], rol),
    ).fetchone()
    nueva = fila is not None
    if not nueva:
        fila = conexion.execute(
            "SELECT id, ticket_id, accion, estado FROM solicitudes_accion WHERE ticket_id = %s AND accion = %s",
            (ticket_id, accion),
        ).fetchone()
    return {"solicitud_id": fila["id"], "ticket_id": fila["ticket_id"], "accion": fila["accion"],
            "estado": fila["estado"], "nueva": nueva,
            "nota": "Pendiente de aprobación de un técnico N2. No se ejecuta nada hasta entonces."}


def resolver_solicitud(conexion: psycopg.Connection, solicitud_id: int, aprobada: bool,
                       rol_aprobador: str, aprobador: str) -> dict:
    """La decisión de una persona N2. No es una herramienta del agente: la llama el grafo al reanudar."""
    # Segunda barrera: el grafo ya valida la decisión, pero esta función nunca convierte "false" en True.
    if type(aprobada) is not bool:
        raise ErrorAccion(f"La decisión debe ser true o false (booleano), no {aprobada!r}.")
    if rol_aprobador != "N2":
        raise ErrorPermiso("Solo un técnico N2 puede aprobar o rechazar una acción.")
    fila = conexion.execute(
        """UPDATE solicitudes_accion SET estado = %s, aprobado_por = %s, fecha_resolucion = now()
           WHERE id = %s AND estado = 'pendiente'
           RETURNING id, ticket_id, accion, estado, aprobado_por""",
        ("ejecutada" if aprobada else "rechazada", aprobador, solicitud_id),
    ).fetchone()
    if fila is None:
        raise ErrorAccion(f"La solicitud {solicitud_id} no existe o ya fue resuelta.")
    nota = "Ejecutada en simulación: no se modificó ningún sistema real." if aprobada else "Rechazada por N2."
    return {**fila, "nota": nota}


def escalar(conexion: psycopg.Connection, ticket_id: str, motivo: str, fuentes: list[str], rol: str) -> dict:
    """Pasa el caso a N2 con el motivo y la evidencia. Es idempotente por ticket y el motivo va sin PII."""
    _rol_valido(rol)
    fila = conexion.execute(
        """INSERT INTO escalamientos (ticket_id, motivo, fuentes) VALUES (%s, %s, %s)
           ON CONFLICT (ticket_id) DO NOTHING RETURNING ticket_id""",
        (ticket_id, enmascarar(motivo)[0], fuentes),
    ).fetchone()
    return {"ticket_id": ticket_id, "escalado": True, "nuevo": fila is not None}
