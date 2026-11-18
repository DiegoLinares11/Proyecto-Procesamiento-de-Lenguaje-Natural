"""Pruebas de las dos fallas que encontró la evaluación con el banco borrador (17 de noviembre).

H01: el agente pedía tiempo_resolucion de RED y ALTA y la consulta salía sin filtros, cinco veces. En modo
     estricto el modelo escribe las claves en el orden del esquema, y `consulta` iba al final: cuando la
     escribía ya había pasado los filtros opcionales. Comprobado con la API: con `consulta` al final, 0 de 3
     llamadas traían los filtros; con `consulta` primero, 3 de 3.
H06: query_tickets decía truncado = false aunque la consulta se hubiera cortado en su `limite`, y el modelo
     afirmó que no había más tickets (devolvió 20 de 25).
"""

import psycopg
import pytest

from tickets_rag import herramientas as H
from tickets_rag.grafo import atender
from tickets_rag.historial import conectar_lectura, query_tickets
from tests.test_grafo import TICKET, ModeloFalso, chunks, falsas, final, grafo_con, pide, chunk_manual  # noqa: F401


# ---------------------------------------------------------------- H01

def _objetos(nodo):
    if isinstance(nodo, dict):
        if isinstance(nodo.get("properties"), dict):
            yield nodo
        for v in nodo.values():
            yield from _objetos(v)
    elif isinstance(nodo, list):
        for v in nodo:
            yield from _objetos(v)


def test_el_discriminador_va_primero_para_que_el_modelo_pueda_poner_los_filtros():
    esquema = H.definiciones_api(["query_tickets"])[0]["input_schema"]
    ramas = esquema["$defs"]
    assert set(ramas) == {"QEstado", "QConteo", "QTiempo", "QProcedimiento", "QEscalados"}
    for nombre, rama in ramas.items():
        assert next(iter(rama["properties"])) == "consulta", f"{nombre}: consulta no va primero"
    # Los filtros siguen siendo opcionales y quedan después del discriminador
    assert list(ramas["QTiempo"]["properties"]) == ["consulta", "desde", "hasta", "categoria", "prioridad"]


def test_en_ningun_esquema_queda_un_discriminador_despues_de_otra_propiedad():
    for definicion in H.definiciones_api(list(H.HERRAMIENTAS)):
        for objeto in _objetos(definicion["input_schema"]):
            claves = list(objeto["properties"])
            con_const = [i for i, k in enumerate(claves) if "const" in objeto["properties"][k]]
            assert con_const == list(range(len(con_const))), f"{definicion['name']}: {claves}"


CONSULTA = {"peticion": {"consulta": "tiempo_resolucion", "desde": "2026-01-01", "hasta": "2026-06-30"}}


def test_una_llamada_repetida_no_se_ejecuta_ni_gasta_otra_consulta(falsas, chunks):
    falsas.cfg["tipo"] = "datos"
    modelo = ModeloFalso(pide(("query_tickets", CONSULTA)), pide(("query_tickets", CONSULTA)),
                         final("El promedio fue de 3.3 horas.", ["sql-1"]))
    estado, _ = atender(grafo_con(modelo, chunks), TICKET, "N1", "Tiempo promedio de RED ALTA en el primer semestre")
    assert len(falsas.llamadas["query_tickets"]) == 1
    repetida = modelo.llamadas[2]["messages"][-1]["content"][0]
    assert repetida["is_error"] and "misma llamada" in repetida["content"]
    assert not estado["respuesta"]["abstained"]


def test_dos_llamadas_identicas_en_el_mismo_turno_se_ejecutan_una_vez(falsas, chunks):
    falsas.cfg["tipo"] = "datos"
    modelo = ModeloFalso(pide(("query_tickets", CONSULTA), ("query_tickets", CONSULTA)),
                         final("El promedio fue de 3.3 horas.", ["sql-1"]))
    atender(grafo_con(modelo, chunks), TICKET, "N1", "Tiempo promedio de RED ALTA en el primer semestre")
    assert len(falsas.llamadas["query_tickets"]) == 1
    resultados = modelo.llamadas[1]["messages"][-1]["content"]
    assert [r["is_error"] for r in resultados] == [False, True]


# ---------------------------------------------------------------- H06

@pytest.fixture(scope="module")
def conexion():
    try:
        c = conectar_lectura()
    except (psycopg.OperationalError, KeyError):
        pytest.skip("Historial no disponible: docker compose up -d y scripts/preparar_bd.py")
    yield c
    c.close()


RANGO = {"desde": "2026-01-01", "hasta": "2026-10-31"}


def test_truncado_cuando_la_consulta_se_corta_en_su_limite(conexion):
    completa = query_tickets(conexion, "escalados", {**RANGO, "limite": 100})
    total = len(completa["filas"])
    assert total > 20 and not completa["truncado"] and "nota" not in completa
    cortada = query_tickets(conexion, "escalados", {**RANGO, "limite": 20})
    assert len(cortada["filas"]) == 20 and cortada["truncado"]
    assert "límite mayor" in cortada["nota"]
    # Con el límite justo, no hay más filas: no está truncado
    exacta = query_tickets(conexion, "escalados", {**RANGO, "limite": total})
    assert len(exacta["filas"]) == total and not exacta["truncado"]


def test_truncado_tambien_en_tickets_por_procedimiento(conexion):
    pocos = query_tickets(conexion, "tickets_por_procedimiento", {"seccion": "2.1", "limite": 1})
    assert len(pocos["filas"]) == 1 and pocos["truncado"]
