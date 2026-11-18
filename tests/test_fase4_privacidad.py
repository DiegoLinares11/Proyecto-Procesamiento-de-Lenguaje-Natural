"""PII introducida por el modelo tampoco llega cruda al checkpoint ni a la respuesta pública."""

import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from tickets_rag import herramientas as H
from tickets_rag.generacion import Generador, SalidaModelo
from tickets_rag.grafo import atender, construir_grafo
from tickets_rag.lexico import Resultado
from tickets_rag.pii import ErrorPII
from tickets_rag.juez import EvaluadorRagas, Juez
from tests.test_api import cliente_con  # noqa: F401
from tests.test_fase3_entrada_estado import guardado
from tests.test_generacion import ClienteFalso
from tests.test_juez import ClienteFalso as ClienteJuezFalso, ragas_real, veredicto  # noqa: F401
from tests.test_grafo import TICKET, ModeloFalso, chunk_manual, chunks, falsas, final, pide  # noqa: F401


def test_nombre_añadido_por_modelo_se_enmascara_antes_de_checkpoint(falsas, chunks, chunk_manual):
    modelo = ModeloFalso(pide(("search_docs", {"query": "Windows"})),
                         final("La solicitante Patricia Robles debe reiniciar Windows.", [chunk_manual["chunk_id"]]))
    grafo = construir_grafo(H.Recursos(chunks=chunks, bm25=None), modelo, InMemorySaver())
    estado, _ = atender(grafo, TICKET, "N1", "Error al actualizar Windows")
    assert "Patricia Robles" not in guardado(grafo)
    assert "[PERSON_REDACTED]" in estado["respuesta"]["answer"]
    assert estado["respuesta"]["needs_human_review"]
    assert any(t.get("pii_en_salida", {}).get("PERSON") for t in estado["traza"])


def test_nombre_en_argumentos_no_llega_a_herramienta_ni_checkpoint(falsas, chunks, chunk_manual):
    modelo = ModeloFalso(pide(("search_docs", {"query": "La solicitante Patricia Robles necesita ayuda con Windows"})),
                         final("Reinicie Windows.", [chunk_manual["chunk_id"]]))
    grafo = construir_grafo(H.Recursos(chunks=chunks, bm25=None), modelo, InMemorySaver())
    atender(grafo, TICKET, "N1", "Error al actualizar Windows")
    assert "Patricia Robles" not in guardado(grafo)
    assert "[PERSON_REDACTED]" in falsas.llamadas["search_docs"][0].query


def test_generacion_sin_grafo_enmascara_salida_y_traza(chunks, chunk_manual):
    class Indice:
        def buscar(self, *_a, **_kw):
            return [Resultado(chunk_manual, 1.0, 1)]

    modelo = ClienteFalso(SalidaModelo(answer="La solicitante Patricia Robles debe reiniciar Windows.",
                                       citas=[chunk_manual["chunk_id"]], sin_evidencia=False))
    respuesta, traza = Generador(Indice(), modelo).responder("Error al actualizar Windows", "N1")
    assert "Patricia Robles" not in json.dumps(traza, ensure_ascii=False)
    assert "[PERSON_REDACTED]" in respuesta.answer and respuesta.needs_human_review
    assert traza["pii_salida"] == {"PERSON": 1}


def test_api_rechaza_sin_ner_con_error_fijo_sin_ecos_del_ticket(cliente_con, monkeypatch):
    def no_disponible(_):
        raise ErrorPII()

    monkeypatch.setattr("tickets_rag.guardrails.enmascarar", no_disponible)
    modelo = ModeloFalso(final("No debe llamarse.", []))
    cliente, motor = cliente_con(modelo)
    with cliente:
        r = cliente.post("/api/tickets", json={"texto": "Soy Patricia Robles y mi correo es privada@correo.example"})
    assert r.status_code == 503
    assert "Patricia" not in r.text and "privada@" not in r.text
    assert modelo.llamadas == [] and list(motor.checkpointer.list(None)) == []


def test_juez_sanea_datos_bilingues_y_comentario_sin_tocar_su_rubrica():
    cliente = ClienteJuezFalso(veredicto(comentario="La solicitante Patricia Robles requiere ayuda."))
    resultado = Juez(cliente).calificar(
        "La solicitante Patricia Robles necesita ayuda", "Debe reiniciar Windows", [], [],
        "La solicitante Patricia Robles debe reiniciar Windows",
        {"F2-c001": "Jennifer Lawrence needs to restart Windows."})
    contenido = cliente.llamadas[0]["mensajes"][0]["content"]
    assert "Patricia Robles" not in contenido and "Jennifer Lawrence" not in contenido
    assert "[PERSON_REDACTED]" in contenido and "Windows" in contenido
    assert "Patricia Robles" not in resultado.comentario


def test_ragas_sanea_datos_segun_idioma_antes_de_construir_prompts(ragas_real):
    cliente = ClienteJuezFalso(
        {"statements": ["Debe reiniciar Windows."]},
        {"statements": [{"statement": "Debe reiniciar Windows.", "reason": "Contexto de prueba", "verdict": 1}]})
    evaluador = EvaluadorRagas(cliente=cliente)
    r = evaluador.evaluar([{
        "pregunta": "La solicitante Patricia Robles necesita ayuda",
        "respuesta": "La solicitante Patricia Robles debe reiniciar Windows.",
        "contextos": ["Jennifer Lawrence needs to restart Windows."],
        "idiomas_contextos": ["en"],
    }])[0]
    assert r["fidelidad"] == 1.0
    prompts = json.dumps([c["mensajes"] for c in cliente.llamadas], ensure_ascii=False)
    assert "Patricia Robles" not in prompts and "Jennifer Lawrence" not in prompts
    assert "[PERSON_REDACTED]" in prompts
