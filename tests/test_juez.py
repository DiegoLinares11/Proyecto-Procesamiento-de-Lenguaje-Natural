"""Juez y métricas reales de Ragas con salidas estructuradas falsas: sin inferencias ni claves de API."""

import threading
from types import SimpleNamespace

import pytest

from tickets_rag.juez import EvaluadorRagas, Juez, Veredicto, _numero
from tickets_rag.modelo import ErrorModelo


class ClienteFalso:
    def __init__(self, *salidas, stop_reason="end_turn"):
        self.salidas = list(salidas)
        self.stop_reason = stop_reason
        self.llamadas = []
        self.hilos = []

    def generar(self, **kwargs):
        self.llamadas.append(kwargs)
        self.hilos.append(threading.get_ident())
        salida = self.salidas.pop(0)
        if isinstance(salida, Exception):
            raise salida
        valor = kwargs["esquema"].model_validate(salida) if isinstance(salida, dict) else salida
        return SimpleNamespace(parsed_output=valor, model="modelo-prueba", stop_reason=self.stop_reason,
                               usage=SimpleNamespace(input_tokens=100, output_tokens=10,
                                                     cache_read_input_tokens=5, cache_creation_input_tokens=2))


def veredicto(**cambios):
    base = {"hechos": [{"indice": 1, "presente": True}, {"indice": 2, "presente": False}],
            "hechos_incorrectos": [{"indice": 1, "presente": True}],
            "citas": [{"chunk_id": "F1-c001", "sustenta": True}], "relevancia": 4,
            "comentario": "La respuesta omite el segundo hecho."}
    return {**base, **cambios}


def calificar(cliente):
    return Juez(cliente, modelo="modelo-prueba").calificar(
        "¿Qué hago?", "Aplique los dos pasos", ["Primer hecho", "Segundo hecho"], ["Un hecho incorrecto"],
        "Respuesta de prueba", {"F1-c001": "Primer hecho", "F1-c002": "Segundo hecho"})


def test_juez_usa_el_cliente_configurado_y_registra_tokens_sin_costo_de_api():
    cliente = ClienteFalso(veredicto())
    r = calificar(cliente)
    assert (r.cobertura, r.incorrectos, r.precision_citas, r.relevancia) == (0.5, 1, 0.5, 0.75)
    assert r.costo_usd == 0.0
    assert r.detalle["uso"]["tokens_entrada"] == 100  # la lectura de caché se conserva aparte
    assert r.detalle["uso"]["tokens_cache_lectura"] == 5
    assert r.detalle["uso"]["tokens_salida"] == 10
    assert r.detalle["uso"]["modelo"] == "modelo-prueba"
    llamada = cliente.llamadas[0]
    assert llamada["esquema"] is Veredicto and llamada["permitir_herramientas"] is False
    assert llamada["esfuerzo"] == "medium"
    assert "api_key" not in llamada and "provider" not in llamada


@pytest.mark.parametrize("stop_reason", ["refusal", "end_turn"])
def test_juez_sin_veredicto_no_reporta_cero_hechos_incorrectos(stop_reason):
    r = calificar(ClienteFalso(None, stop_reason=stop_reason))
    assert r.cobertura is r.incorrectos is r.precision_citas is r.relevancia is None
    assert r.costo_usd == 0.0 and r.detalle["error"] == "veredicto_invalido"
    assert r.detalle["uso"]["tokens_entrada"] == 100


def test_error_del_cliente_no_se_confunde_con_evaluacion_exitosa():
    r = calificar(ClienteFalso(ErrorModelo("Error sanitizado de prueba")))
    assert r.incorrectos is None and r.cobertura is None
    assert r.detalle["error"] == "ErrorModelo"
    assert r.detalle["codigo_modelo"] == "transporte"
    assert r.detalle["uso"]["tokens_entrada"] is None
    assert r.costo_usd == 0.0


@pytest.mark.parametrize("codigo", ["cuota", "autenticacion", "configuracion", "modelo"])
def test_bloqueos_del_juez_se_propagan_para_detener_el_benchmark(codigo):
    cliente = ClienteFalso(ErrorModelo(codigo))
    with pytest.raises(ErrorModelo) as error:
        calificar(cliente)
    assert error.value.codigo == codigo and len(cliente.llamadas) == 1


@pytest.mark.parametrize("valor", [None, float("nan"), float("inf"), -1, 2, "no es un número"])
def test_scores_no_definidos_son_none_en_lugar_de_cero(valor):
    assert _numero(valor) is None


def test_score_cero_es_un_resultado_medido():
    assert _numero(0) == 0.0


@pytest.mark.parametrize("concurrencia", [0, -1, True, 1.5])
def test_concurrencia_invalida_se_rechaza(concurrencia):
    with pytest.raises(ValueError, match="entero positivo"):
        EvaluadorRagas(cliente=ClienteFalso(), concurrencia=concurrencia)


def test_suscripcion_no_encola_evaluaciones_paralelas():
    with pytest.raises(ValueError, match="concurrencia=1"):
        EvaluadorRagas(cliente=ClienteFalso(), concurrencia=2)


def test_sin_contextos_no_hay_llamadas_ni_scores_inventados():
    cliente = ClienteFalso()
    evaluador = EvaluadorRagas(cliente=cliente)
    r = evaluador.evaluar([{"pregunta": "¿Qué hago?", "respuesta": "Sin evidencia", "contextos": []}])[0]
    assert r["fidelidad"] is r["precision_contexto"] is None
    assert r["error_ragas"] is None and r["uso"]["llamadas"] == 0
    assert cliente.llamadas == []


def test_ragas_desactiva_su_telemetria_incluso_si_el_entorno_la_habilita(monkeypatch):
    monkeypatch.setenv("RAGAS_DO_NOT_TRACK", "false")
    EvaluadorRagas(cliente=ClienteFalso())
    import os
    assert os.environ["RAGAS_DO_NOT_TRACK"] == "true"


@pytest.fixture
def ragas_real(monkeypatch):
    pytest.importorskip("ragas.metrics.collections")
    import ragas.llms.base

    def prohibido(*args, **kwargs):
        pytest.fail("Las métricas no deben crear clientes de proveedores de API")

    monkeypatch.setattr(ragas.llms.base, "llm_factory", prohibido)


def item(**cambios):
    return {"pregunta": "¿Cuál es la política de MFA?", "respuesta": "Solo N2 restablece MFA. N1 lo solicita.",
            "contextos": ["Solo N2 restablece MFA.", "El correo tiene 50 GB.", "N1 solicita el cambio."],
            "contextos_top5": ["Solo N2 restablece MFA.", "El correo tiene 50 GB.", "N1 solicita el cambio."],
            "referencia": "N1 solicita el restablecimiento, pero solo N2 lo ejecuta.", **cambios}


def salidas_ragas():
    return [{"statements": ["Solo N2 restablece MFA.", "N1 lo solicita."]},
            {"statements": [{"statement": "Solo N2 restablece MFA.", "reason": "El contexto lo dice", "verdict": 1},
                            {"statement": "N1 lo solicita.", "reason": "No se sustenta en esta prueba", "verdict": 0}]},
            {"reason": "Útil", "verdict": 1}, {"reason": "Ruido", "verdict": 0}, {"reason": "Útil", "verdict": 1}]


def test_ragas_real_calcula_fidelidad_y_precision_con_el_adaptador(ragas_real):
    cliente = ClienteFalso(*salidas_ragas())
    evaluador = EvaluadorRagas(modelo="modelo-prueba", cliente=cliente)
    r = evaluador.evaluar([item()])[0]
    # Son los algoritmos de Ragas: fidelidad 1/2 y AP = (1 + 2/3) / 2.
    assert r["fidelidad"] == 0.5 and r["precision_contexto"] == 0.833
    assert r["error_ragas"] is None
    assert evaluador.costo_usd == 0.0 and r["uso"]["costo_api_incremental_usd"] == 0.0
    assert r["uso"]["llamadas"] == 5 and r["uso"]["tokens_entrada"] == evaluador.tokens_entrada == 500
    assert r["uso"]["modelos"] == ["modelo-prueba"]
    assert evaluador.tokens_salida == 50
    assert all(c["permitir_herramientas"] is False for c in cliente.llamadas)
    assert all(hilo != threading.get_ident() for hilo in cliente.hilos)  # generar corre mediante to_thread


def test_ragas_es_secuencial_por_defecto_y_conserva_orden(ragas_real):
    cliente = ClienteFalso(*salidas_ragas(), *salidas_ragas())
    evaluador = EvaluadorRagas(modelo="modelo-prueba", cliente=cliente)
    resultados = evaluador.evaluar([item(), item(pregunta="Segunda pregunta")])
    assert evaluador.concurrencia == 1 and len(resultados) == 2
    assert [c["esquema"].__name__ for c in cliente.llamadas] == [
        "StatementGeneratorOutput", "NLIStatementOutput", "ContextPrecisionOutput", "ContextPrecisionOutput", "ContextPrecisionOutput"] * 2


def test_error_en_fidelidad_no_impide_medir_precision(ragas_real):
    cliente = ClienteFalso(ErrorModelo("No copie aquí texto ni secretos"), {"reason": "Útil", "verdict": 1})
    evaluador = EvaluadorRagas(cliente=cliente)
    r = evaluador.evaluar([item(contextos_top5=["Solo N2 restablece MFA."])])[0]
    assert r["fidelidad"] is None and r["precision_contexto"] == 1.0
    assert r["error_ragas"] == "fidelidad: ErrorModelo"
    assert r["codigos_error_modelo"] == ["transporte"]
    assert "secretos" not in r["error_ragas"]
    assert r["uso"]["tokens_entrada"] is None  # no se inventa el consumo de la llamada fallida


def test_ragas_sin_afirmaciones_reporta_score_no_definido(ragas_real):
    cliente = ClienteFalso({"statements": []})
    r = EvaluadorRagas(cliente=cliente).evaluar([item(referencia=None, contextos_top5=[])])[0]
    assert r["fidelidad"] is None and r["precision_contexto"] is None
    assert r["error_ragas"] == "fidelidad: resultado no definido"


@pytest.mark.parametrize("codigo", ["cuota", "autenticacion", "configuracion", "modelo"])
def test_bloqueo_se_propaga_y_detiene_el_lote_sin_inferencias_adicionales(ragas_real, codigo):
    cliente = ClienteFalso(ErrorModelo(codigo))
    with pytest.raises(ErrorModelo) as error:
        EvaluadorRagas(cliente=cliente).evaluar([item(), item(), item()])
    assert error.value.codigo == codigo
    assert len(cliente.llamadas) == 1
