"""Pruebas de la API de la demo con el modelo falso y las herramientas falsas. Sin API ni base de datos."""

import json

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from tickets_rag import acciones
from tickets_rag import herramientas as H
from tickets_rag.api import EJEMPLOS, Motor, crear_app
from tickets_rag.lexico import IndiceBM25
from tests.test_grafo import ModeloFalso, chunk_manual, chunks, falsas, final, pide  # noqa: F401


def _eventos(respuesta) -> list[dict]:
    return [json.loads(linea[6:]) for linea in respuesta.text.splitlines() if linea.startswith("data: ")]


@pytest.fixture
def cliente_con(chunks):
    def armar(modelo):
        motor = Motor(H.Recursos(chunks=chunks, bm25=IndiceBM25(chunks)), modelo, InMemorySaver())
        return TestClient(crear_app(motor)), motor
    return armar


def test_un_ticket_manda_cada_paso_y_la_respuesta_con_citas(falsas, cliente_con, chunk_manual):
    cliente, _ = cliente_con(ModeloFalso(pide(("search_docs", {"query": "outlook procesando"})),
                                         final("Abra Outlook en modo seguro.", [chunk_manual["chunk_id"]])))
    with cliente:
        eventos = _eventos(cliente.post("/api/tickets", json={"texto": "Outlook no abre", "rol": "N1"}))
    assert [e["tipo"] for e in eventos][0] == "inicio" and eventos[-1]["tipo"] == "respuesta"
    pasos = [e["nodo"] for e in eventos if e["tipo"] == "paso"]
    assert pasos == ["guardrail_entrada", "clasificar", "agente", "herramientas", "agente", "validar_salida", "responder"]
    pedido = next(e for e in eventos if e.get("nodo") == "agente")["llamadas"]
    assert pedido == [{"nombre": "search_docs", "argumentos": {"query": "outlook procesando"}}]
    candidato = next(e for e in eventos if e.get("nodo") == "herramientas")["traza"][0]["candidatos"][0]
    assert candidato["chunk_id"] == chunk_manual["chunk_id"] and candidato["page"] == chunk_manual["page"]
    assert eventos[-1]["respuesta"]["sources"][0]["chunk_id"] == chunk_manual["chunk_id"]


def test_una_contrasena_no_aparece_en_ningun_evento(falsas, cliente_con):
    cliente, _ = cliente_con(ModeloFalso(final("x", [])))
    with cliente:
        r = cliente.post("/api/tickets", json={"texto": "mi contraseña es Perrito123", "rol": "N1"})
    eventos = _eventos(r)
    assert "Perrito123" not in r.text
    assert eventos[0]["guardrail"]["decision"] == "BLOCK" and eventos[-1]["respuesta"]["abstained"]


def test_los_datos_personales_llegan_enmascarados_a_la_pagina(falsas, cliente_con, chunk_manual):
    cliente, _ = cliente_con(ModeloFalso(pide(("search_docs", {"query": "vpn"})), final("Siga el 5.2.", [chunk_manual["chunk_id"]])))
    with cliente:
        r = cliente.post("/api/tickets", json={"texto": "La VPN no conecta, mi correo es ana@correo.example", "rol": "N1"})
    assert "ana@correo.example" not in r.text and "[EMAIL_REDACTED]" in _eventos(r)[0]["texto_seguro"]


@pytest.fixture
def decisiones(monkeypatch):
    registro = []

    def resolver(conexion, solicitud_id, aprobada, rol, aprobador):
        registro.append((aprobada, rol))
        if rol != "N2":
            raise acciones.ErrorPermiso("Solo un técnico N2 puede aprobar o rechazar una acción.")
        return {"id": solicitud_id, "estado": "ejecutada" if aprobada else "rechazada", "aprobado_por": aprobador,
                "nota": "Ejecutada en simulación." if aprobada else "Rechazada por N2."}

    monkeypatch.setattr(acciones, "resolver_solicitud", resolver)
    return registro


def _accion(cliente_con, falsas, chunk_manual):
    falsas.cfg["tipo"] = "accion"
    cliente, motor = cliente_con(ModeloFalso(pide(("search_docs", {"query": "mfa"})),
                                             pide(("take_action", {"accion": "restablecer_mfa", "motivo": "Perdió el teléfono"})),
                                             final("Se solicitó restablecer el MFA.", [chunk_manual["chunk_id"]])))
    return cliente, motor


@pytest.mark.parametrize("decision, aprueba", [
    ({"aprobada": True, "aprobador": "Técnico N2", "rol": "N2"}, True),
    ({"aprobada": "true", "aprobador": "Técnico N2", "rol": "N2"}, False),
    ({"aprobada": True, "aprobador": "Agente N1", "rol": "N1"}, False),
])
def test_la_accion_se_pausa_y_solo_n2_con_un_booleano_la_aprueba(falsas, cliente_con, chunk_manual, decisiones, decision, aprueba):
    cliente, _ = _accion(cliente_con, falsas, chunk_manual)
    with cliente:
        eventos = _eventos(cliente.post("/api/tickets", json={"texto": "Perdí el teléfono, restablezcan mi MFA", "rol": "N1"}))
        pausa = eventos[-1]
        assert pausa["tipo"] == "pausa" and pausa["solicitudes"][0]["accion"] == "restablecer_mfa"
        final_ = _eventos(cliente.post(f"/api/tickets/{pausa['hilo']}/decision", json=decision))[-1]
    assert final_["tipo"] == "respuesta"
    respuesta = final_["respuesta"]["answer"]
    assert ("Ejecutada en simulación" in respuesta) == aprueba
    if not aprueba:
        assert "sigue pendiente" in respuesta


def test_decidir_sobre_un_hilo_que_no_existe_da_404(falsas, cliente_con):
    cliente, _ = cliente_con(ModeloFalso(final("x", [])))
    with cliente:
        assert cliente.post("/api/tickets/no-existe/decision", json={"aprobada": True}).status_code == 404


def test_la_api_caida_se_ve_como_respuesta_degradada(falsas, cliente_con):
    cliente, _ = cliente_con(ModeloFalso(final("x", [])))
    with cliente:
        eventos = _eventos(cliente.post("/api/tickets", json={"texto": "Error 0x80070005 al actualizar", "rol": "N1",
                                                              "falla": "modelo"}))
    assert [e["nodo"] for e in eventos if e["tipo"] == "paso"][-1] == "degradar"
    assert next(e for e in eventos if e.get("nodo") == "agente")["error_modelo"].startswith("APIConnectionError")
    assert eventos[-1]["respuesta"]["needs_human_review"] and eventos[-1]["respuesta"]["sources"]


def test_un_n1_no_puede_leer_un_fragmento_de_n2(cliente_con, chunks, chunk_manual):
    cliente, _ = cliente_con(ModeloFalso(final("x", [])))
    restringido = next(c["chunk_id"] for c in chunks if c["roles_permitidos"] == ["N2"])
    with cliente:
        assert cliente.get(f"/api/fragmentos/{restringido}?rol=N1").status_code == 403
        assert cliente.get(f"/api/fragmentos/{restringido}?rol=N2").status_code == 200
        f = cliente.get(f"/api/fragmentos/{chunk_manual['chunk_id']}").json()
        assert f["texto"] == chunk_manual["text"] and f["url_pdf"].endswith(f"#page={chunk_manual['page']}")
        assert cliente.get("/api/fragmentos/F9-c999").status_code == 404


def test_solo_sirve_los_pdf_del_corpus(cliente_con):
    cliente, _ = cliente_con(ModeloFalso(final("x", [])))
    with cliente:
        assert cliente.get("/api/pdf/manual_mesa_ayuda_v2026-2.pdf").headers["content-type"] == "application/pdf"
        assert cliente.get("/api/pdf/..%2F.env").status_code == 404
        assert cliente.get("/api/pdf/.env").status_code == 404


def test_los_ejemplos_cubren_los_seis_puntos_de_la_demo():
    grupos = {e["grupo"] for e in EJEMPLOS}
    assert {"Consulta nominal", "Trazabilidad de citas", "Abstención", "Herramientas", "Seguridad",
            "Fallas y degradación"} <= grupos
