"""Pruebas de las dos fallas que encontró la evaluación con el banco borrador (17 de noviembre).

H01: el agente pedía tiempo_resolucion de RED y ALTA y la consulta salía sin filtros, cinco veces. En modo
     estricto el modelo escribe las claves en el orden del esquema, y `consulta` iba al final: cuando la
     escribía ya había pasado los filtros opcionales. Comprobado con la API: con `consulta` al final, 0 de 3
     llamadas traían los filtros; con `consulta` primero, 3 de 3.
H06: query_tickets decía truncado = false aunque la consulta se hubiera cortado en su `limite`, y el modelo
     afirmó que no había más tickets (devolvió 20 de 25).
"""

from types import SimpleNamespace

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


# ---------------------------------------------------------------- Escalamientos innecesarios

# Motivos reales de la evaluación: el modelo llamaba a escalate para decir que no escalaba
MOTIVOS_FALSOS = ["placeholder", "No procede escalar: el procedimiento 4.3 se resuelve en N1.",
                  "No corresponde escalar, se responde con los pasos del manual", "x"]


@pytest.fixture
def escalamientos(monkeypatch, chunks):
    registrados = []
    monkeypatch.setattr(H.acciones, "escalar",
                        lambda conexion, ticket_id, motivo, fuentes, rol: registrados.append(motivo) or
                        {"ticket_id": ticket_id, "escalado": True, "nuevo": True})
    return SimpleNamespace(registrados=registrados, recursos=H.Recursos(chunks=chunks, bm25=None))


@pytest.mark.parametrize("motivo", MOTIVOS_FALSOS)
def test_un_motivo_que_dice_que_no_hay_que_escalar_no_escala(escalamientos, motivo):
    r = H.ejecutar(escalamientos.recursos, H.Contexto(TICKET, "N1"), "escalate",
                   {"causa": "pasos_agotados", "motivo": motivo}, {"escalate"})
    assert not r.ok and "no llames a escalate" in r.error
    assert escalamientos.registrados == []  # se rechaza antes de escribir en la base


def test_escalar_exige_una_causa_del_procedimiento_8_1(escalamientos):
    sin_causa = H.ejecutar(escalamientos.recursos, H.Contexto(TICKET, "N1"), "escalate",
                           {"motivo": "El usuario ya reinició y sigue la pantalla azul"}, {"escalate"})
    assert not sin_causa.ok and "causa" in sin_causa.error
    ok = H.ejecutar(escalamientos.recursos, H.Contexto(TICKET, "N1"), "escalate",
                    {"causa": "pasos_agotados", "motivo": "El usuario ya reinició y sigue la pantalla azul"}, {"escalate"})
    assert ok.ok and escalamientos.registrados == ["[pasos_agotados] El usuario ya reinició y sigue la pantalla azul"]
    # La causa va primero en el esquema, por lo que aprendimos con query_tickets
    esquema = H.definiciones_api(["escalate"])[0]["input_schema"]
    assert list(esquema["properties"])[0] == "causa" and "causa" in esquema["required"]


def test_el_modelo_no_puede_usar_la_causa_reservada_para_la_abstencion(falsas, chunks, chunk_manual):
    modelo = ModeloFalso(pide(("search_docs", {"query": "outlook"})),
                         pide(("escalate", {"causa": "sin_evidencia", "motivo": "No encontré el procedimiento exacto"})),
                         final("Siga el 3.1.", [chunk_manual["chunk_id"]]))
    estado, _ = atender(grafo_con(modelo, chunks), TICKET, "N1", "Outlook no abre")
    rechazo = modelo.llamadas[2]["messages"][-1]["content"][0]
    assert rechazo["is_error"] and "la usa el sistema" in rechazo["content"]
    assert "escalate" not in falsas.llamadas and "escalate" not in (estado["respuesta"]["tool_used"] or "")


def test_la_abstencion_sigue_escalando_con_su_causa(falsas, chunks):
    falsas.cfg["suficiente"] = False
    modelo = ModeloFalso(pide(("search_docs", {"query": "impresora 3D"})), final("No hay evidencia.", [], sin_evidencia=True))
    estado, _ = atender(grafo_con(modelo, chunks), TICKET, "N1", "¿Cómo configuro la impresora 3D?")
    assert [e.causa for e in falsas.llamadas["escalate"]] == ["sin_evidencia"]
    assert "Lo escalé a N2" in estado["respuesta"]["answer"]
