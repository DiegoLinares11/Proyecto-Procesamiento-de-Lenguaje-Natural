"""Contrato GET del progreso, sin inicializar atención ni ejecutar modelos."""

import json
from contextlib import contextmanager

from fastapi.testclient import TestClient

from tickets_rag import api


def test_consultar_progreso_no_inicia_motor_ni_escribe(tmp_path, monkeypatch):
    monkeypatch.setattr(api.config, "RAIZ", tmp_path)
    monkeypatch.setattr(api, "BANCO_OFICIAL", tmp_path / "evaluacion/banco.jsonl")
    monkeypatch.setattr(api, "BANCO_BORRADOR", tmp_path / "evaluacion/banco_borrador.jsonl")
    llamadas = []

    @contextmanager
    def motor_prohibido():
        llamadas.append("motor")
        raise AssertionError("No debe preparar recursos al consultar resultados")
        yield  # pragma: no cover

    monkeypatch.setattr(api, "_motor_produccion", motor_prohibido)
    with TestClient(api.crear_app()) as cliente:
        for _ in range(2):
            respuesta = cliente.get("/api/evaluacion/progreso")
            assert respuesta.status_code == 200
            assert respuesta.headers["cache-control"] == "no-store"
            assert respuesta.json()["estado"] == "sin_datos"
        assert cliente.post("/api/evaluacion/progreso", json={}).status_code == 405
    assert llamadas == [] and list(tmp_path.iterdir()) == []


def test_error_de_archivo_es_503_sin_publicar_contenido(tmp_path, monkeypatch):
    monkeypatch.setattr(api.config, "RAIZ", tmp_path)
    banco = tmp_path / "evaluacion/banco.jsonl"
    banco.parent.mkdir()
    banco.write_text("", encoding="utf-8")
    monkeypatch.setattr(api, "BANCO_OFICIAL", banco)
    carpeta = tmp_path / "resultados/codex_suscripcion/evaluacion/banco"
    carpeta.mkdir(parents=True)
    (carpeta / "resumen_parcial.json").write_text('{"dato_privado":', encoding="utf-8")
    with TestClient(api.crear_app()) as cliente:
        respuesta = cliente.get("/api/evaluacion/progreso")
    assert respuesta.status_code == 503
    assert "dato_privado" not in respuesta.text


def test_endpoint_anterior_conserva_metricas_historicas(tmp_path, monkeypatch):
    monkeypatch.setattr(api.config, "RAIZ", tmp_path)
    monkeypatch.setattr(api.config, "RESULTADOS", tmp_path / "resultados")
    monkeypatch.setattr(api.config, "RESULTADOS_SUSCRIPCION", tmp_path / "resultados/codex_suscripcion")
    banco = tmp_path / "evaluacion/banco.jsonl"
    banco.parent.mkdir()
    banco.write_text("", encoding="utf-8")
    monkeypatch.setattr(api, "BANCO_OFICIAL", banco)
    carpeta = tmp_path / "resultados/evaluacion/banco"
    carpeta.mkdir(parents=True)
    historico = {"casos": 42, "sistemas": {"agente": {"ataques_bloqueados": .75, "costo_promedio_usd": .013}}}
    (carpeta / "resumen.json").write_text(json.dumps(historico), encoding="utf-8")
    with TestClient(api.crear_app()) as cliente:
        resultados = cliente.get("/api/evaluacion").json()
        progreso = cliente.get("/api/evaluacion/progreso").json()
    assert resultados["sistemas"] == historico["sistemas"] and resultados["historico"] is True
    assert progreso["estado"] == "sin_datos" and progreso["metricas_finales_disponibles"] is False
