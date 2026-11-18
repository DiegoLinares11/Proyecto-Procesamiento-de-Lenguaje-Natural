"""Pruebas de los cuatro fallos que encontró Diederich en la revisión del 17 de noviembre.

Cada prueba reproduce el fallo con el modelo falso y comprueba la corrección:
1. Una aprobación que no sea exactamente el booleano true no aprueba nada ("false" aprobaba).
2. El texto original nunca queda guardado en los checkpoints, tampoco al entrar por LangGraph Studio.
3. Si la API del modelo falla, el grafo responde de forma controlada en vez de reventar.
4. El sistema no anuncia un escalamiento que no se pudo registrar.
"""

import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from tickets_rag import acciones
from tickets_rag import herramientas as H
from tickets_rag.grafo import atender, construir_grafo, reanudar
from tickets_rag.modelo import ErrorModelo
from tests.test_grafo import TICKET, ModeloFalso, accion_pendiente, chunk_manual, chunks, falsas, final, grafo_con, pide  # noqa: F401


# ---------------------------------------------------------------- 1. Aprobación estricta

@pytest.mark.parametrize("valor", ["false", "true", 1, 0, "sí", None])
def test_aprobacion_que_no_es_booleano_no_aprueba(accion_pendiente, valor):
    estado = reanudar(accion_pendiente.grafo, accion_pendiente.cfg, aprobada=valor, aprobador="Técnico N2", rol="N2")
    assert accion_pendiente.decisiones == []  # ni siquiera llega a resolver la solicitud
    assert estado.get("__interrupt__") and estado.get("respuesta") is None
    assert any("sigue pendiente" in n for n in estado["notas_accion"])
    assert any("aprobación inválida" in m for m in estado["revision"])


def test_false_booleano_rechaza(accion_pendiente):
    estado = reanudar(accion_pendiente.grafo, accion_pendiente.cfg, aprobada=False, aprobador="Técnico N2", rol="N2")
    assert accion_pendiente.decisiones == [(41, False, "N2")]
    assert "Rechazada" in estado["respuesta"]["answer"]


def test_aprobador_vacio_no_cuenta(accion_pendiente):
    estado = reanudar(accion_pendiente.grafo, accion_pendiente.cfg, aprobada=True, aprobador="   ", rol="N2")
    assert accion_pendiente.decisiones == [] and estado.get("__interrupt__") and estado.get("respuesta") is None


@pytest.mark.parametrize("decision", ["sí", True, {"aprobada": True, "aprobador": "N2", "rol": "N2", "extra": 1}])
def test_reanudar_directo_con_algo_que_no_es_la_decision_no_aprueba(accion_pendiente, decision):
    # Así reanuda LangGraph Studio: manda el JSON tal cual, sin pasar por reanudar()
    estado = accion_pendiente.grafo.invoke(Command(resume=decision), accion_pendiente.cfg)
    assert accion_pendiente.decisiones == [] and estado.get("__interrupt__") and estado.get("respuesta") is None


def test_resolver_solicitud_tambien_rechaza_lo_que_no_es_booleano():
    # Segunda barrera, en la función que escribe en la base: falla antes de tocar la conexión
    with pytest.raises(acciones.ErrorAccion, match="booleano"):
        acciones.resolver_solicitud(None, 41, "false", "N2", "Técnico N2")


# ---------------------------------------------------------------- 2. Checkpoints sin texto original

def _todo_lo_guardado(checkpointer) -> str:
    """Todo lo que el checkpointer escribió: estados, escrituras pendientes y metadatos."""
    partes = []
    for tupla in checkpointer.list(None):
        partes.append(json.dumps(tupla.checkpoint, default=str, ensure_ascii=False))
        partes.append(json.dumps(tupla.metadata, default=str, ensure_ascii=False))
        partes.append(json.dumps(tupla.pending_writes or [], default=str, ensure_ascii=False))
    return " ".join(partes)


def test_entrada_tipo_studio_no_guarda_el_texto_original(falsas, chunks, chunk_manual):
    modelo = ModeloFalso(pide(("search_docs", {"query": "vpn"})), final("Siga el 5.2.", [chunk_manual["chunk_id"]]))
    checkpointer = InMemorySaver()
    grafo = construir_grafo(H.Recursos(chunks=chunks, bm25=None), modelo, checkpointer)
    cfg = {"configurable": {"thread_id": "studio-1"}}
    grafo.invoke({"ticket_id": TICKET, "rol": "N1", "texto": "La VPN no conecta, mi correo es ana@correo.example"}, cfg)
    grafo.invoke({"ticket_id": TICKET, "rol": "N1", "texto": "mi contraseña es Perrito123"},
                 {"configurable": {"thread_id": "studio-2"}})
    guardado = _todo_lo_guardado(checkpointer)
    assert "ana@correo.example" not in guardado and "Perrito123" not in guardado
    assert "[EMAIL_REDACTED]" in guardado  # sí se guardó la versión enmascarada


def test_camino_normal_no_guarda_el_texto_original_en_ningun_checkpoint(falsas, chunks, chunk_manual):
    modelo = ModeloFalso(pide(("search_docs", {"query": "vpn"})), final("Siga el 5.2.", [chunk_manual["chunk_id"]]))
    checkpointer = InMemorySaver()
    grafo = construir_grafo(H.Recursos(chunks=chunks, bm25=None), modelo, checkpointer)
    atender(grafo, TICKET, "N1", "La VPN no conecta, mi teléfono es 5555-1234")
    assert "5555-1234" not in _todo_lo_guardado(checkpointer)


# ---------------------------------------------------------------- 3. Falla de la API

class ModeloCaido:
    def __init__(self, error):
        self.error = error

    def generar(self, **kwargs):
        raise self.error


@pytest.mark.parametrize("error", [
    ErrorModelo("transporte", transitorio=True),
    ErrorModelo("timeout", transitorio=True),
])
def test_si_la_api_falla_responde_de_forma_controlada(falsas, chunks, error):
    recursos = H.Recursos(chunks=chunks, bm25=H.IndiceBM25(chunks))
    grafo = construir_grafo(recursos, ModeloCaido(error), InMemorySaver())
    estado, _ = atender(grafo, TICKET, "N1", "Error 0x80070005 al instalar actualizaciones")
    r = estado["respuesta"]
    assert r["needs_human_review"] and "no está disponible" in r["answer"]
    # Responde con resultados léxicos (anteproyecto, sección 8), filtrados por rol
    assert r["sources"] and all(s["chunk_id"].startswith(("F1", "F2")) for s in r["sources"])
    roles = {c["chunk_id"]: c["roles_permitidos"] for c in chunks}
    assert all("N1" in roles[s["chunk_id"]] for s in r["sources"])


# ---------------------------------------------------------------- 4. Escalamiento confirmado

def test_no_anuncia_escalamiento_si_no_se_pudo_registrar(falsas, chunks, monkeypatch):
    import dataclasses

    def caida(recursos, contexto, entrada):
        raise H.ErrorHerramienta("la base de datos no respondió")

    monkeypatch.setitem(H.HERRAMIENTAS, "escalate", dataclasses.replace(H.HERRAMIENTAS["escalate"], funcion=caida))
    falsas.cfg["suficiente"] = False
    modelo = ModeloFalso(pide(("search_docs", {"query": "impresora 3D"})), final("No hay evidencia.", [], sin_evidencia=True))
    estado, _ = atender(grafo_con(modelo, chunks), TICKET, "N1", "¿Cómo configuro la impresora 3D?")
    r = estado["respuesta"]
    assert "escalé" not in r["answer"].lower() and "no se pudo" in r["answer"].lower()
    assert "escalate" not in (r["tool_used"] or "")
    assert any("escalamiento" in m for m in estado["revision"])


def test_el_modelo_no_puede_decir_que_escalo_si_no_llamo_a_escalate(falsas, chunks, chunk_manual):
    modelo = ModeloFalso(pide(("search_docs", {"query": "vpn"})),
                         final("Ya escalé el ticket a N2. Siga el 5.2.", [chunk_manual["chunk_id"]]),
                         final("Siga el procedimiento 5.2.", [chunk_manual["chunk_id"]]))
    estado, _ = atender(grafo_con(modelo, chunks), TICKET, "N1", "La VPN no conecta")
    assert len(modelo.llamadas) == 3  # la primera respuesta no pasa la validación y se reintenta
    assert "no pasó la validación" in modelo.llamadas[2]["mensajes"][-1]["content"]
    assert "escalé" not in estado["respuesta"]["answer"].lower()
