"""Prepara PostgreSQL para las herramientas: historial de tickets, tablas de acciones y roles.

Uso:
    docker compose up -d
    uv run python scripts/preparar_bd.py

Crea dos roles con permisos mínimos:
- tickets_lectura: solo SELECT sobre el historial (query_tickets).
- tickets_acciones: inserta solicitudes y escalamientos y cambia su estado (take_action, escalate).

Si al .env le faltan sus claves, las genera al azar y las agrega sin mostrarlas. Las tablas de
acciones se vuelven a crear vacías en cada corrida.
"""

from __future__ import annotations

import os
import secrets

from tickets_rag import config, vectores
from tickets_rag.acciones import VARIABLE_CLAVE_ACCIONES, crear_tablas
from tickets_rag.historial import VARIABLE_CLAVE_LECTURA, cargar_historial


def clave(variable: str) -> str:
    config.cargar_entorno()
    if not os.environ.get(variable):
        ruta = config.RAIZ / ".env"
        texto = ruta.read_text(encoding="utf-8")
        nueva = secrets.token_urlsafe(24)
        ruta.write_text(texto.rstrip("\n") + f"\n{variable}={nueva}\n", encoding="utf-8")
        os.environ[variable] = nueva
        print(f"{variable} agregada al .env (clave aleatoria, no se muestra)")
    return os.environ[variable]


def main() -> None:
    clave_lectura, clave_acciones = clave(VARIABLE_CLAVE_LECTURA), clave(VARIABLE_CLAVE_ACCIONES)
    with vectores.conectar() as conexion:
        total = cargar_historial(conexion, clave_lectura)
        crear_tablas(conexion, clave_acciones)
    print(f"Historial: {total} tickets. Tablas de acciones y escalamientos vacías. Roles listos.")


if __name__ == "__main__":
    main()
