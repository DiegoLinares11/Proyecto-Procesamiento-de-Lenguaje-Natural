"""Ciclo GPU→juez con módulos/procesos falsos; sin pesos, red, LLM o BD."""

import ast
import copy
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_evaluar_banco_reanudar import cli  # noqa: F401
from tickets_rag.evaluacion_progreso import ErrorProgreso, ProgresoEvaluacion, evaluar_incremental
from tickets_rag.modelo import ErrorModelo


def test_preflight_ragas_es_otro_proceso_sin_claves_ni_import_parent(cli, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "NO_HEREDAR")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "NO_HEREDAR")
    anteriores = {n for n in sys.modules if n == "ragas" or n.startswith("ragas.")}
    llamadas = []
    def ejecutar(args, **kwargs):
        llamadas.append((args, kwargs))
        assert args[0] == sys.executable and args[1] == "-c"
        assert "ragas.metrics.collections" in args[2]
        assert kwargs["env"]["RAGAS_DO_NOT_TRACK"] == "true"
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        assert all("API_KEY" not in k for k in kwargs["env"])
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        assert 0 < kwargs["timeout"] <= 60 and kwargs.get("shell") is not True
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(cli.subprocess, "run", ejecutar)
    cli.verificar_dependencia_ragas()
    assert len(llamadas) == 1
    assert anteriores == {n for n in sys.modules if n == "ragas" or n.startswith("ragas.")}


@pytest.mark.parametrize("modo", ["timeout", "retorno", "oserror"])
def test_preflight_falla_sanitizado_antes_de_inferencias(cli, monkeypatch, modo):
    def ejecutar(*args, **kwargs):
        if modo == "timeout":
            raise subprocess.TimeoutExpired("SECRETO_NO_COPIAR", 60, stderr="SECRETO_NO_COPIAR")
        if modo == "oserror":
            raise OSError("SECRETO_NO_COPIAR")
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(cli.subprocess, "run", ejecutar)
    with pytest.raises(ErrorProgreso) as error:
        cli.verificar_dependencia_ragas()
    assert error.value.causa == "dependencia_ragas" and "SECRETO" not in str(error.value)


def test_imports_juez_y_ragas_solo_en_callbacks_no_preflight_parent(cli):
    arbol = ast.parse(Path(cli.__file__).read_text())
    imports = []
    def recorrer(nodo, pila=()):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            pila = (*pila, nodo.name)
        if isinstance(nodo, ast.ImportFrom) and nodo.module and (nodo.module.startswith("ragas") or nodo.module == "tickets_rag.juez"):
            imports.append((nodo.module, pila))
        for hijo in ast.iter_child_nodes(nodo):
            recorrer(hijo, pila)
    recorrer(arbol)
    assert imports and all(pila[-1] in {"juzgar", "evaluar_ragas"} for _, pila in imports)


def modulos_falsos(monkeypatch, eventos):
    def cache(nombre):
        return SimpleNamespace(cache_clear=lambda: eventos.append("cache:" + nombre))
    emb = SimpleNamespace(DISPOSITIVO="mps", modelo_embeddings=cache("embeddings"), reranker=cache("reranker"))
    torch = SimpleNamespace(mps=SimpleNamespace(synchronize=lambda: eventos.append("sincronizar"),
                                                empty_cache=lambda: eventos.append("vaciar_mps")))
    monkeypatch.setitem(sys.modules, "tickets_rag.embeddings", emb)
    monkeypatch.setitem(sys.modules, "torch", torch)


def test_liberar_antes_juez_y_resumen_sin_cambiar_huella(cli, monkeypatch, tmp_path):
    eventos = []
    modulos_falsos(monkeypatch, eventos)
    monkeypatch.setattr(cli.gc, "collect", lambda: eventos.append("gc"))
    conexion = SimpleNamespace(close=lambda: eventos.append("cerrar_conexion"))
    recursos = {"agente": SimpleNamespace(conexion_vectores=conexion, conexion_lectura=conexion, conexion_acciones=None)}
    generadores = {"rag": SimpleNamespace(indice=SimpleNamespace(conexion=conexion))}
    conexiones = {"metricas": conexion}
    huella = {"modelo": "fijo", "dispositivo": "mps", "config": {"tau": .0045}}
    original = copy.deepcopy(huella)
    with ProgresoEvaluacion(tmp_path / "eval", huella) as p:
        def generar(*a):
            eventos.append("generar")
            return {"segundos": 0.0}
        def juzgar(*a):
            eventos.append("importar_juez")
            assert not recursos and not generadores and not conexiones
            return {"valor": 1}
        filas = evaluar_incremental(p, {"agente": ["R01", "R02"]}, generar, lambda *a: {}, juzgar=juzgar,
            antes_calificar=lambda: cli.liberar_recursos_evaluacion(p, recursos, generadores, conexiones))
        eventos.append("resumen")
        assert len(filas["agente"]) == 2
        assert p.huella == huella == original
        assert p.manifiesto["transiciones_calificacion"][-1]["drenado"] is True
    assert eventos.count("cerrar_conexion") == 1
    assert max(i for i, e in enumerate(eventos) if e == "generar") < eventos.index("cerrar_conexion")
    assert eventos.index("sincronizar") < eventos.index("cache:embeddings") < eventos.index("gc")
    assert eventos.index("gc") < eventos.index("vaciar_mps") < eventos.index("importar_juez") < eventos.index("resumen")


def test_reanudar_generaciones_completas_no_carga_pesos_y_si_prepara_calificacion(tmp_path):
    eventos, corte = [], [True]
    plan = {"agente": ["R01"], "rag": ["R01"]}
    def generar(s, *a):
        eventos.append("generar:" + s)
        return {"segundos": 0.0}
    def juzgar(*a):
        if corte[0]:
            corte[0] = False
            raise ErrorModelo("cuota")
        eventos.append("juez")
        return {"valor": 1}
    with pytest.raises(ErrorModelo):
        with ProgresoEvaluacion(tmp_path / "eval", {"fijo": True}) as p:
            evaluar_incremental(p, plan, generar, lambda *a: {}, juzgar=juzgar,
                                antes_calificar=lambda: eventos.append("liberar"))
    with ProgresoEvaluacion(tmp_path / "eval", {"fijo": True}, reanudar=True) as p:
        evaluar_incremental(p, plan, lambda *a: pytest.fail("Generación ya completa"), lambda *a: pytest.fail(),
            preparar=lambda *a: pytest.fail("No cargar pesos al reanudar"), juzgar=juzgar,
            antes_calificar=lambda: eventos.append("liberar"))
    assert eventos == ["generar:agente", "generar:rag", "liberar", "liberar", "juez", "juez"]


def test_worker_tardio_bloquea_liberacion_e_import_juez_con_espera_acotada(cli, monkeypatch, tmp_path):
    liberar, iniciado = threading.Event(), threading.Event()
    eventos = []
    modulos_falsos(monkeypatch, eventos)
    monkeypatch.setattr(cli.config, "TIMEOUT_HERRAMIENTA_S", .01)
    with ProgresoEvaluacion(tmp_path / "eval", {}) as p:
        def worker():
            with p.trabajo_herramienta("agente", "R01", "search_docs"):
                iniciado.set()
                liberar.wait(2)
        hilo = threading.Thread(target=worker)
        hilo.start();assert iniciado.wait(1)
        try:
            with pytest.raises(ErrorProgreso) as error:
                evaluar_incremental(p, {"agente": ["R01"]}, lambda *a: {"segundos": 0.0}, lambda *a: {},
                    juzgar=lambda *a: eventos.append("NO_IMPORTAR_JUEZ"),
                    antes_calificar=lambda: cli.liberar_recursos_evaluacion(p, {}, {}, {}))
            assert error.value.causa == "recursos_ocupados"
            estado = p.manifiesto["transiciones_calificacion"][-1]
            assert not estado["drenado"] and estado["limite_s"] == .02
            assert estado["activos"] == [{"sistema": "agente", "id": "R01", "herramienta": "search_docs"}]
            assert not eventos  # no cache_clear, sincronización GPU ni importación del juez
        finally:
            liberar.set();hilo.join(timeout=1)
        assert not hilo.is_alive() and p.esperar_herramientas(0)["drenado"]
