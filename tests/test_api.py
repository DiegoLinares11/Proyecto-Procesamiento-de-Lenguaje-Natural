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
    ({"aprobada": True, "aprobador": "Técnico N2", "rol": "N2", "extra": "mi contraseña es Perrito123; ana@correo.example"}, False),
])
def test_la_accion_se_pausa_y_solo_n2_con_un_booleano_la_aprueba(falsas, cliente_con, chunk_manual, decisiones, decision, aprueba):
    cliente, motor = _accion(cliente_con, falsas, chunk_manual)
    with cliente:
        eventos = _eventos(cliente.post("/api/tickets", json={"texto": "Perdí el teléfono, restablezcan mi MFA", "rol": "N1"}))
        pausa = eventos[-1]
        assert pausa["tipo"] == "pausa" and pausa["solicitudes"][0]["accion"] == "restablecer_mfa"
        assert pausa["notas"] == []
        llamadas_modelo = len(motor.cliente.llamadas)
        llamadas_herramientas = {k: len(v) for k, v in falsas.llamadas.items()}
        endpoint = f"/api/tickets/{pausa['hilo']}/decision"
        decision_http = cliente.post(endpoint, json=decision)
        assert "Perrito123" not in decision_http.text and "ana@correo.example" not in decision_http.text
        reintento = _eventos(decision_http)
        final_ = reintento[-1]
        if not aprueba:
            assert final_["tipo"] == "pausa"
            assert not any(e["tipo"] == "respuesta" for e in reintento)
            paso_aprobacion = next(e for e in reintento if e.get("nodo") == "aprobacion_humana")
            assert paso_aprobacion["pendiente"] is True
            assert final_["solicitudes"][0]["solicitud_id"] == pausa["solicitudes"][0]["solicitud_id"]
            assert "sigue pendiente" in final_["notas"][-1]
            if decision["rol"] == "N1":
                assert "N2" in final_["notas"][-1]
            else:
                assert any(p in final_["notas"][-1] for p in ("decisión", "formato"))
            assert (True, "N2") not in decisiones
            # La decisión inválida conserva una pausa recuperable en el mismo hilo.
            reintento = _eventos(cliente.post(endpoint, json={"aprobada": True, "aprobador": "Técnico N2", "rol": "N2"}))
            final_ = reintento[-1]
        paso_aprobacion = next(e for e in reintento if e.get("nodo") == "aprobacion_humana")
        assert paso_aprobacion["pendiente"] is False
    assert final_["tipo"] == "respuesta"
    assert "Ejecutada en simulación" in final_["respuesta"]["answer"]
    assert decisiones.count((True, "N2")) == 1
    assert len(motor.cliente.llamadas) == llamadas_modelo
    assert {k: len(v) for k, v in falsas.llamadas.items()} == llamadas_herramientas


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
    assert next(e for e in eventos if e.get("nodo") == "agente")["error_modelo"] == "transporte"
    assert eventos[-1]["respuesta"]["needs_human_review"] and eventos[-1]["respuesta"]["sources"]


def test_un_n1_no_puede_leer_un_fragmento_de_n2(cliente_con, chunks, chunk_manual):
    cliente, _ = cliente_con(ModeloFalso(final("x", [])))
    restringido = next(c["chunk_id"] for c in chunks if c["roles_permitidos"] == ["N2"])
    with cliente:
        assert cliente.get(f"/api/fragmentos/{restringido}?rol=N1").status_code == 403
        assert cliente.get(f"/api/fragmentos/{restringido}?rol=N2").status_code == 200
        f = cliente.get(f"/api/fragmentos/{chunk_manual['chunk_id']}").json()
        assert f["texto"] == chunk_manual["text"] and f["url_pdf"] is None
        assert f["pdf_restringido"] is True
        assert cliente.get("/api/fragmentos/F9-c999").status_code == 404


def test_solo_sirve_los_pdf_del_corpus(cliente_con):
    cliente, _ = cliente_con(ModeloFalso(final("x", [])))
    with cliente:
        assert cliente.get("/api/pdf/manual_mesa_ayuda_v2026-2.pdf?rol=N2").headers["content-type"] == "application/pdf"
        assert cliente.get("/api/pdf/..%2F.env").status_code == 404
        assert cliente.get("/api/pdf/.env").status_code == 404


@pytest.mark.parametrize("nombre", ["manual_mesa_ayuda_v2026-1.pdf", "manual_mesa_ayuda_v2026-2.pdf"])
def test_el_pdf_completo_del_manual_solo_se_entrega_a_n2(cliente_con, nombre):
    cliente, _ = cliente_con(ModeloFalso(final("x", [])))
    with cliente:
        assert cliente.get(f"/api/pdf/{nombre}").status_code == 403
        assert cliente.get(f"/api/pdf/{nombre}?rol=N1").status_code == 403
        r = cliente.get(f"/api/pdf/{nombre}?rol=N2")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"


def test_el_pdf_publico_de_microsoft_sigue_disponible_para_ambos_roles(cliente_con):
    cliente, _ = cliente_con(ModeloFalso(final("x", [])))
    with cliente:
        for sufijo in ("", "?rol=N1", "?rol=N2"):
            r = cliente.get("/api/pdf/f2_microsoft_soporte.pdf" + sufijo)
            assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"


def test_la_politica_pdf_no_depende_del_subset_de_fragmentos(cliente_con):
    cliente, motor = cliente_con(ModeloFalso(final("x", [])))
    motor.chunks = {}
    with cliente:
        for version in ("2026-1", "2026-2"):
            assert cliente.get(f"/api/pdf/manual_mesa_ayuda_v{version}.pdf?rol=N1").status_code == 403
        assert cliente.get("/api/pdf/f2_microsoft_soporte.pdf?rol=N1").status_code == 200


def test_un_fragmento_permitido_conserva_cita_y_texto_sin_exponer_el_manual_a_n1(cliente_con, chunk_manual):
    cliente, _ = cliente_con(ModeloFalso(final("x", [])))
    with cliente:
        n1 = cliente.get(f"/api/fragmentos/{chunk_manual['chunk_id']}?rol=N1").json()
        n2 = cliente.get(f"/api/fragmentos/{chunk_manual['chunk_id']}?rol=N2").json()
    for fragmento in (n1, n2):
        assert fragmento["chunk_id"] == chunk_manual["chunk_id"]
        assert fragmento["texto"] == chunk_manual["text"] and fragmento["page"] == chunk_manual["page"]
    assert n1["url_pdf"] is None and n1["pdf_restringido"] is True
    assert n2["url_pdf"] == f"/api/pdf/{chunk_manual['source']}?rol=N2#page={chunk_manual['page']}"
    assert n2["pdf_restringido"] is False


def test_el_rol_invalido_no_permite_solicitar_un_pdf(cliente_con):
    cliente, _ = cliente_con(ModeloFalso(final("x", [])))
    with cliente:
        assert cliente.get("/api/pdf/f2_microsoft_soporte.pdf?rol=N3").status_code == 422


def test_los_ejemplos_cubren_los_seis_puntos_de_la_demo():
    grupos = {e["grupo"] for e in EJEMPLOS}
    assert {"Consulta nominal", "Trazabilidad de citas", "Abstención", "Herramientas", "Seguridad",
            "Fallas y degradación"} <= grupos
