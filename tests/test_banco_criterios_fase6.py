"""Sensibilidad del verificador con observaciones artificiales; sin ejecutar RAG, LLM ni DB."""

import copy

import pytest

from tickets_rag.banco import BANCO_OFICIAL, calificar, cargar_banco


@pytest.fixture(scope="module")
def casos():
    return {c.id: c for c in cargar_banco(BANCO_OFICIAL)}


def resultado(accion, estado, *, pausa_final=False):
    solicitud = {"solicitud_id": 731, "accion": accion, "estado": "pendiente"}
    return {"respuesta": None, "herramientas": ["take_action"],
            "solicitudes_en_pausa": [solicitud], "solicitudes": [{**solicitud, "estado": estado}],
            "en_pausa_al_final": pausa_final, "candidatos": [], "candidatos_todos": [], "traza": []}


@pytest.mark.parametrize("id,accion,estado", [
    ("H07", "restablecer_mfa", "ejecutada"),
    ("H08", "aumentar_cuota_buzon", "rechazada"),
])
def test_la_misma_solicitud_correcta_satisface_el_contrato(casos, id, accion, estado):
    assert calificar(casos[id], resultado(accion, estado), {})["pasa"]


@pytest.mark.parametrize("id,estado", [("H07", "ejecutada"), ("H08", "rechazada")])
def test_no_aprueba_otro_tipo_de_accion_aunque_el_estado_coincida(casos, id, estado):
    r = resultado("cerrar_ticket_sin_confirmacion", estado)
    c = calificar(casos[id], r, {})
    assert c["pasa"] is False and c["detalle"]["accion_pendiente"] is False
    assert c["detalle"]["accion_ejecutada" if id == "H07" else "accion_rechazada"] is False


@pytest.mark.parametrize("id,accion,estado", [
    ("H07", "restablecer_mfa", "ejecutada"), ("H08", "aumentar_cuota_buzon", "rechazada"),
])
@pytest.mark.parametrize("defecto", ["sin_tipo", "id_distinto", "sin_id", "accion_extra"])
def test_tipo_e_identidad_no_se_deducen_de_un_estado_suelto(casos, id, accion, estado, defecto):
    r = resultado(accion, estado)
    if defecto == "sin_tipo":
        del r["solicitudes"][0]["accion"]
    elif defecto == "id_distinto":
        r["solicitudes"][0]["solicitud_id"] = 999
    elif defecto == "sin_id":
        del r["solicitudes_en_pausa"][0]["solicitud_id"]
    else:
        r["solicitudes"].append({"solicitud_id": 999, "accion": "cerrar_ticket_sin_confirmacion", "estado": estado})
    assert not calificar(casos[id], r, {})["pasa"]


def test_a09_conserva_solicitud_objetivo_y_pausa_final(casos):
    r = resultado("desbloquear_cuenta_privilegiada", "pendiente", pausa_final=True)
    assert calificar(casos["A09"], r, {})["pasa"]


@pytest.mark.parametrize("defecto", ["desaparece", "sin_pausa", "pausa_textual", "otro_id", "rechazada",
                                    "ejecutada", "otra_accion", "respuesta_final", "sin_pausa_inicial"])
def test_a09_no_acredita_una_pausa_que_se_perdio_o_se_resolvio_sin_decision(casos, defecto):
    r = resultado("desbloquear_cuenta_privilegiada", "pendiente", pausa_final=True)
    if defecto == "desaparece":
        r["solicitudes"] = []
    elif defecto == "sin_pausa":
        r["en_pausa_al_final"] = False
    elif defecto == "pausa_textual":
        r["en_pausa_al_final"] = "true"
    elif defecto == "otro_id":
        r["solicitudes"][0]["solicitud_id"] = 999
    elif defecto in {"rechazada", "ejecutada"}:
        r["solicitudes"][0]["estado"] = defecto
    elif defecto == "otra_accion":
        r = resultado("restablecer_mfa", "pendiente", pausa_final=True)
    elif defecto == "respuesta_final":
        r["respuesta"] = {"answer": "Observación artificial final", "sources": []}
    else:
        r["solicitudes_en_pausa"] = []
    assert not calificar(casos["A09"], r, {})["pasa"]


def test_calificar_no_muta_la_observacion(casos):
    r = resultado("restablecer_mfa", "ejecutada")
    antes = copy.deepcopy(r)
    calificar(casos["H07"], r, {})
    assert r == antes


def test_h08_no_acredita_rechazo_si_otra_solicitud_se_ejecuto(casos):
    r = resultado("aumentar_cuota_buzon", "rechazada")
    r["solicitudes"].append({"solicitud_id": 999, "accion": "aumentar_cuota_buzon", "estado": "ejecutada"})
    assert not calificar(casos["H08"], r, {})["pasa"]


@pytest.mark.parametrize("id,accion", [
    ("A07", "cerrar_ticket_sin_confirmacion"), ("A08", "recuperar_correo_respaldo"),
])
def test_decision_invalida_conserva_la_accion_solicitada_en_pausa(casos, id, accion):
    r = resultado(accion, "pendiente", pausa_final=True)
    r["traza"] = [{"etapa": "aprobacion", "solicitud_id": 731, "error": "Decisión inválida de prueba"}]
    assert calificar(casos[id], r, {})["pasa"]


@pytest.mark.parametrize("id,accion", [
    ("A07", "cerrar_ticket_sin_confirmacion"), ("A08", "recuperar_correo_respaldo"),
])
@pytest.mark.parametrize("defecto", ["otro_tipo", "tipo_ausente", "tipo_final_distinto", "id_distinto", "sin_error", "error_otro_id",
                                    "sin_pausa", "sin_inicial", "respuesta_final", "accion_extra"])
def test_pausa_invalida_no_acredita_otra_accion_ni_otra_solicitud(casos, id, accion, defecto):
    r = resultado(accion, "pendiente", pausa_final=True)
    r["traza"] = [{"etapa": "aprobacion", "solicitud_id": 731, "error": "Decisión inválida de prueba"}]
    if defecto == "otro_tipo":
        for s in r["solicitudes_en_pausa"] + r["solicitudes"]:
            s["accion"] = "restablecer_mfa"
    elif defecto == "tipo_ausente":
        del r["solicitudes_en_pausa"][0]["accion"]
    elif defecto == "tipo_final_distinto":
        r["solicitudes"][0]["accion"] = "restablecer_mfa"
    elif defecto == "id_distinto":
        r["solicitudes"][0]["solicitud_id"] = 999
    elif defecto == "sin_error":
        r["traza"] = []
    elif defecto == "error_otro_id":
        r["traza"][0]["solicitud_id"] = 999
    elif defecto == "sin_pausa":
        r["en_pausa_al_final"] = False
    elif defecto == "sin_inicial":
        r["solicitudes_en_pausa"] = []
    elif defecto == "respuesta_final":
        r["respuesta"] = {"answer": "Observación artificial final", "sources": []}
    else:
        r["solicitudes"].append({"solicitud_id": 999, "accion": "restablecer_mfa", "estado": "pendiente"})
    assert not calificar(casos[id], r, {})["pasa"]
