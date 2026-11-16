"""Pruebas del historial en PostgreSQL y del catálogo query_tickets. Se saltan si la base no está."""

import json

import psycopg
import pytest

from tickets_rag.historial import TICKETS, ErrorConsulta, conectar_lectura, query_tickets


@pytest.fixture(scope="module")
def conexion():
    try:
        c = conectar_lectura()
        c.execute("SELECT 1 FROM tickets LIMIT 1")
        return c
    except Exception:
        pytest.skip("Historial no disponible: docker compose up -d y scripts/preparar_bd.py")


def tickets_f3():
    return [json.loads(l) for l in TICKETS.read_text(encoding="utf-8").splitlines()]


def test_el_historial_tiene_solo_los_tickets_del_indice(conexion):
    filas = query_tickets(conexion, "conteo_por_categoria", {"desde": "2026-01-01", "hasta": "2026-12-31"})["filas"]
    assert sum(f["total"] for f in filas) == sum(t["particion"] == "indice" for t in tickets_f3())
    prueba = next(t for t in tickets_f3() if t["particion"] == "prueba")
    assert query_tickets(conexion, "estado_ticket", {"ticket_id": prueba["ticket_id"]})["filas"] == []


def test_los_textos_del_historial_van_enmascarados(conexion):
    textos = " ".join(str(v) for f in conexion.execute("SELECT texto, diagnostico, solucion FROM tickets").fetchall() for v in f.values())
    for t in tickets_f3():
        for dato in t["pii_sembrada"]:
            assert dato["valor"] not in textos


def test_el_rol_es_de_solo_lectura_aunque_desactive_el_modo_de_sesion(conexion):
    assert conexion.execute("SHOW statement_timeout").fetchone()["statement_timeout"] == "10s"
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        conexion.execute("DELETE FROM tickets")
    # Un usuario puede apagar el modo de solo lectura de su sesión: los permisos son la segunda barrera.
    conexion.execute("SET default_transaction_read_only = off")
    try:
        for sentencia in ("DELETE FROM tickets", "UPDATE tickets SET estado = 'x'", "CREATE TABLE x (a int)",
                          "SELECT 1 FROM chunks_bge_m3 LIMIT 1"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conexion.execute(sentencia)
    finally:
        conexion.execute("SET default_transaction_read_only = on")


@pytest.mark.parametrize("nombre, parametros, mensaje", [
    ("borrar_todo", {}, "Consulta desconocida"),
    ("estado_ticket", {"ticket_id": "1; DROP TABLE tickets"}, "ticket_id"),
    ("estado_ticket", {"ticket_id": "TCK-2026-00001", "sql": "SELECT 1"}, "Extra inputs"),
    ("escalados", {"desde": "2026-05-01", "hasta": "2026-01-01"}, "anterior"),
    ("escalados", {"desde": "2026-01-01", "hasta": "2026-03-01", "limite": 500}, "limite"),
    ("conteo_por_categoria", {"desde": "2024-01-01", "hasta": "2026-01-01"}, "366"),
    ("tiempo_resolucion", {"desde": "2026-01-01", "hasta": "2026-12-31", "categoria": "VARIOS"}, "categoria"),
])
def test_parametros_fuera_de_rango_no_llegan_a_la_base(conexion, nombre, parametros, mensaje):
    with pytest.raises(ErrorConsulta, match=mensaje):
        query_tickets(conexion, nombre, parametros)


def test_consultas_del_catalogo(conexion):
    ticket = next(t for t in tickets_f3() if t["particion"] == "indice")
    fila = query_tickets(conexion, "estado_ticket", {"ticket_id": ticket["ticket_id"]})["filas"][0]
    assert fila["categoria"] == ticket["categoria"] and fila["prioridad"] == ticket["prioridad"]
    recientes = query_tickets(conexion, "tickets_por_procedimiento", {"seccion": "5.2", "limite": 3})["filas"]
    assert len(recientes) == 3 and recientes[0]["fecha_apertura"] >= recientes[-1]["fecha_apertura"]
    tiempo = query_tickets(conexion, "tiempo_resolucion", {"desde": "2026-01-01", "hasta": "2026-12-31", "prioridad": "ALTA"})
    assert tiempo["filas"][0]["tickets"] > 0
