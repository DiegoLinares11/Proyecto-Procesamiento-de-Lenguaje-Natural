"""Captura por HTTP sin base de datos, inferencias ni textos humanos reales."""

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from tickets_rag import api
from tickets_rag.captura_manuales import CapturaManuales


class EvaluacionFalsa:
    def __init__(self):
        self.inicios = 0

    def estado(self):
        return {"estado": "sin_iniciar", "progreso": {"completados": 0, "total": 20}}

    def iniciar(self):
        self.inicios += 1
        return {"estado": "ejecutando", "progreso": {"completados": 0, "total": 20}}


@pytest.fixture
def captura_http(tmp_path, monkeypatch):
    llamadas = []

    @contextmanager
    def motor_no_disponible():
        llamadas.append("motor")
        raise RuntimeError("secreto de prueba que no debe publicarse")
        yield  # pragma: no cover

    monkeypatch.setattr(api, "_motor_produccion", motor_no_disponible)
    almacenamiento = CapturaManuales(carpeta=tmp_path / "manuales")
    evaluacion = EvaluacionFalsa()
    with TestClient(api.crear_app(captura=almacenamiento, evaluacion_manuales=evaluacion), base_url="http://127.0.0.1") as cliente:
        yield cliente, llamadas, evaluacion, almacenamiento


def payload(snapshot):
    return {k: snapshot[k] for k in ("revision", "tickets", "autoria")}


def test_api_captura_inicia_sin_modelos_ni_postgresql(captura_http):
    cliente, llamadas, evaluacion, _ = captura_http
    salud = cliente.get("/api/salud").json()
    estado = cliente.get("/api/tickets-manuales").json()
    assert salud["captura_disponible"] and not salud["atencion_inicializada"]
    assert estado["estado"] == "borrador" and len(estado["tickets"]) == 20
    assert all(t["texto"] == "" for t in estado["tickets"])
    assert cliente.get("/api/tickets-manuales/evaluacion").status_code == 200
    assert cliente.get("/api/tickets-manuales").headers["cache-control"] == "no-store"
    assert llamadas == [] and evaluacion.inicios == 0


def test_guardar_y_recargar_no_atiende_el_ticket_y_rechaza_conflictos(captura_http):
    cliente, llamadas, evaluacion, _ = captura_http
    viejo = payload(cliente.get("/api/tickets-manuales").json())
    viejo["tickets"][0].update(texto="  PRUEBA AUTOMÁTICA: redacción conservada.\n", categoria="RED", prioridad="MEDIA")
    nuevo = cliente.put("/api/tickets-manuales", json=viejo)
    assert nuevo.status_code == 200
    assert nuevo.json()["revision"] > viejo["revision"]
    assert cliente.get("/api/tickets-manuales").json()["tickets"][0]["texto"] == viejo["tickets"][0]["texto"]
    assert cliente.put("/api/tickets-manuales", json=viejo).status_code == 409
    assert llamadas == [] and evaluacion.inicios == 0


def test_incompletos_no_se_congelan_y_errores_no_copian_textos(captura_http):
    cliente, llamadas, _, almacenamiento = captura_http
    estado = cliente.get("/api/tickets-manuales").json()
    for accion in ("validar", "congelar"):
        respuesta = cliente.post(f"/api/tickets-manuales/{accion}", json={"revision": estado["revision"]})
        assert respuesta.status_code == 422
    assert not (almacenamiento.carpeta / "congelado").exists()
    malo = payload(estado)
    malo["extra"] = "dato privado de prueba"
    respuesta = cliente.put("/api/tickets-manuales", json=malo)
    assert respuesta.status_code == 422 and "dato privado de prueba" not in respuesta.text
    respuesta = cliente.put("/api/tickets-manuales", json=[{"texto": "dato privado de prueba"}])
    assert respuesta.status_code == 422 and "dato privado de prueba" not in respuesta.text
    assert llamadas == []


def test_falla_del_motor_no_inhabilita_la_captura(captura_http):
    cliente, llamadas, _, _ = captura_http
    respuesta = cliente.post("/api/tickets", json={"texto": "fixture de atención"})
    assert respuesta.status_code == 503 and "secreto de prueba" not in respuesta.text
    assert llamadas == ["motor"]
    assert cliente.get("/api/tickets-manuales").status_code == 200


def test_evaluacion_solo_arranca_con_post_explicito(captura_http):
    cliente, _, evaluacion, _ = captura_http
    for _ in range(3):
        cliente.get("/api/tickets-manuales/evaluacion")
    assert evaluacion.inicios == 0
    assert cliente.post("/api/tickets-manuales/evaluacion", json={}).json()["estado"] == "ejecutando"
    assert evaluacion.inicios == 1


@pytest.mark.parametrize("headers", [{"Origin": "https://sitio-ajeno.example"}, {"Origin": "null"},
                                     {"Sec-Fetch-Site": "cross-site"}, {"Host": "sitio-ajeno.example"}])
def test_otro_sitio_no_puede_disparar_evaluacion(captura_http, headers):
    cliente, llamadas, evaluacion, _ = captura_http
    respuesta = cliente.post("/api/tickets-manuales/evaluacion", json={}, headers=headers)
    assert respuesta.status_code == 403
    assert evaluacion.inicios == 0 and llamadas == []


def test_formularios_no_pueden_iniciar_inferencias_y_vite_local_si(captura_http):
    cliente, _, evaluacion, _ = captura_http
    assert cliente.post("/api/tickets-manuales/evaluacion", content="{}").status_code == 415
    assert evaluacion.inicios == 0
    respuesta = cliente.post("/api/tickets-manuales/evaluacion", json={}, headers={"Origin": "http://localhost:5173"})
    assert respuesta.status_code == 200 and evaluacion.inicios == 1
