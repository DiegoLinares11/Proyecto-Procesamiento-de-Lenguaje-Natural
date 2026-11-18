"""Aislamiento de fallas por grafo, con el pool real de herramientas y sin modelos ni base de datos."""

import copy
import dataclasses
import threading
from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType, SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from tickets_rag import fallas
from tickets_rag import herramientas as H
from tickets_rag.banco import INSTRUCCION_ENVENENADA
from tickets_rag.grafo import atender, construir_grafo
from tickets_rag.modelo import ErrorModelo
from tests.test_grafo import ModeloFalso, final, pide

CTX = H.Contexto(ticket_id="TCK-2099-00301", rol="N1")


@pytest.fixture
def busqueda(monkeypatch):
    fragmento = {"chunk_id": "F1-c001", "text": "Procedimiento autorizado.", "source": "manual.pdf", "page": 1,
                 "roles_permitidos": ["N1", "N2"], "metadatos": {"etiquetas": ["original"]},
                 "tipo": "manual", "doc_type": "manual", "version": "2026-2", "score": 0.9}
    salida = {"fragmentos": [fragmento, {**copy.deepcopy(fragmento), "chunk_id": "F1-c002", "text": "Segundo fragmento."}],
              "evidencia_suficiente": True, "degradado": False, "meta": {"notas": ["original"]}}
    herramienta = dataclasses.replace(H.HERRAMIENTAS["search_docs"], funcion=lambda *_: salida)
    monkeypatch.setitem(H.HERRAMIENTAS, "search_docs", herramienta)
    # Expone los recursos que realmente captura cada grafo sin construir clientes, índices ni conexiones.
    monkeypatch.setattr(fallas, "construir_grafo", lambda recursos, _cliente, _checkpointer: recursos)
    recursos = H.Recursos(chunks=salida["fragmentos"], bm25=None)
    return SimpleNamespace(recursos=recursos, salida=salida, herramienta=herramienta, original=copy.deepcopy(salida))


def ejecutar(recursos, falla=None):
    with fallas.contexto_de_falla(falla):
        return H.ejecutar(recursos, CTX, "search_docs", {"query": "consulta"}, {"search_docs"}, timeout=4)


def test_solicitudes_normal_y_envenenada_concurren_sin_contaminarse(busqueda, monkeypatch):
    barrera = threading.Barrier(2)
    contexto_listo = threading.Event()
    hilos = []

    def obtener(*_):
        hilos.append(threading.current_thread().name)
        barrera.wait(timeout=3)
        return busqueda.salida

    original = dataclasses.replace(busqueda.herramienta, funcion=obtener)
    monkeypatch.setitem(H.HERRAMIENTAS, "search_docs", original)
    normal = fallas.grafo_con_falla(busqueda.recursos, None, None)
    envenenado = fallas.grafo_con_falla(busqueda.recursos, None, None, "documento_envenenado")

    def atacar():
        with fallas.contexto_de_falla("documento_envenenado"):
            contexto_listo.set()
            return ejecutar(envenenado, "documento_envenenado")

    def consultar():
        assert contexto_listo.wait(timeout=3)
        return ejecutar(normal)

    with ThreadPoolExecutor(max_workers=2) as solicitudes:
        ataque = solicitudes.submit(atacar)
        consulta = solicitudes.submit(consultar)
        r_normal, r_ataque = consulta.result(timeout=5), ataque.result(timeout=5)

    assert r_normal.ok and r_ataque.ok
    assert INSTRUCCION_ENVENENADA not in r_normal.contenido["fragmentos"][0]["text"]
    assert r_ataque.contenido["fragmentos"][0]["text"].endswith(INSTRUCCION_ENVENENADA)
    assert busqueda.salida == busqueda.original
    assert H.HERRAMIENTAS["search_docs"] is original
    assert all(nombre.startswith("herramienta") for nombre in hilos)


def test_resultado_envenenado_se_copia_completo_y_no_muta_el_corpus(busqueda):
    envenenado = fallas.grafo_con_falla(busqueda.recursos, None, None, "documento_envenenado")
    r = ejecutar(envenenado, "documento_envenenado")
    assert r.ok and r.contenido is not busqueda.salida
    assert r.contenido["fragmentos"][1]["text"] == "Segundo fragmento."
    r.contenido["fragmentos"][0]["metadatos"]["etiquetas"].append("cambio")
    r.contenido["meta"]["notas"].append("cambio")
    assert busqueda.salida == busqueda.original
    assert busqueda.recursos.chunks[0]["text"] == "Procedimiento autorizado."


def test_dos_grafos_reales_reciben_solo_su_contexto_en_el_modelo_falso(busqueda, monkeypatch):
    barrera = threading.Barrier(2)

    def obtener(*_):
        barrera.wait(timeout=3)
        return busqueda.salida

    monkeypatch.setitem(H.HERRAMIENTAS, "search_docs", dataclasses.replace(busqueda.herramienta, funcion=obtener))
    monkeypatch.setattr(fallas, "construir_grafo", construir_grafo)
    clasificador = dataclasses.replace(H.HERRAMIENTAS["classify"], funcion=lambda *_: {
        "categoria": "EQUIPOS", "prioridad": "MEDIA", "tipo": "procedimiento", "confianza": {},
        "needs_human_review": False, "costo_usd": 0.0})
    recursos = dataclasses.replace(busqueda.recursos, herramientas_locales=MappingProxyType({"classify": clasificador}))
    modelos = [ModeloFalso(pide(("search_docs", {"query": "procedimiento"})),
                           final("Procedimiento autorizado.", ["F1-c001"])) for _ in range(2)]
    grafos = [fallas.grafo_con_falla(recursos, modelo, InMemorySaver(), falla)
              for modelo, falla in zip(modelos, [None, "documento_envenenado"])]
    with ThreadPoolExecutor(max_workers=2) as solicitudes:
        resultados = [solicitudes.submit(atender, grafo, f"TCK-2099-0040{i}", "N1", "Procedimiento de prueba")
                      for i, grafo in enumerate(grafos)]
        estados = [futuro.result(timeout=5)[0] for futuro in resultados]
    assert all(not estado["respuesta"]["abstained"] for estado in estados)
    # La serialización de tool_result en el grafo refleja el aislamiento que vio cada modelo.
    import json
    contextos = [json.loads(modelo.llamadas[1]["mensajes"][-1]["content"][0]["content"])
                 for modelo in modelos]
    assert INSTRUCCION_ENVENENADA not in contextos[0]["fragmentos"][0]["text"]
    assert contextos[1]["fragmentos"][0]["text"].endswith(INSTRUCCION_ENVENENADA)
    assert busqueda.salida == busqueda.original


def test_nueva_construccion_no_cambia_el_registro_ni_los_recursos_originales(busqueda):
    registro = dict(H.HERRAMIENTAS)
    envenenado = fallas.grafo_con_falla(busqueda.recursos, None, None, "documento_envenenado")
    normal = fallas.grafo_con_falla(busqueda.recursos, None, None)
    assert normal is busqueda.recursos and envenenado is not busqueda.recursos
    assert busqueda.recursos.herramientas_locales is None
    assert H.HERRAMIENTAS == registro
    with pytest.raises(TypeError):
        envenenado.herramientas_locales["search_docs"] = registro["search_docs"]
    assert ejecutar(normal).contenido == busqueda.original


def test_contextos_anidados_no_bloquean_y_la_inyeccion_no_se_duplica(busqueda):
    completado = threading.Event()
    resultados, errores = [], []

    def anidar():
        try:
            with fallas.contexto_de_falla("documento_envenenado"):
                envenenado = fallas.grafo_con_falla(busqueda.recursos, None, None, "documento_envenenado")
                with fallas.contexto_de_falla("documento_envenenado"):
                    reentrante = fallas.grafo_con_falla(envenenado, None, None, "documento_envenenado")
                    resultados.append(ejecutar(reentrante, "documento_envenenado"))
        except Exception as error:
            errores.append(error)
        finally:
            completado.set()

    hilo = threading.Thread(target=anidar, daemon=True)
    hilo.start()
    assert completado.wait(timeout=3), "Los contextos anidados no deben adquirir un candado global"
    hilo.join(timeout=1)
    assert not errores and resultados[0].ok
    assert resultados[0].contenido["fragmentos"][0]["text"].count(INSTRUCCION_ENVENENADA) == 1
    assert H.HERRAMIENTAS["search_docs"] is busqueda.herramienta


def test_excepcion_al_construir_no_deja_simulaciones_globales(busqueda, monkeypatch):
    def fallar(*_):
        raise RuntimeError("Error de construcción de prueba")

    monkeypatch.setattr(fallas, "construir_grafo", fallar)
    with pytest.raises(RuntimeError, match="construcción"):
        with fallas.contexto_de_falla("documento_envenenado"):
            fallas.grafo_con_falla(busqueda.recursos, None, None, "documento_envenenado")
    assert H.HERRAMIENTAS["search_docs"] is busqueda.herramienta
    assert busqueda.recursos.herramientas_locales is None and busqueda.salida == busqueda.original


def test_excepcion_en_una_solicitud_no_afecta_las_siguientes(busqueda, monkeypatch):
    contador = 0

    def obtener(*_):
        nonlocal contador
        contador += 1
        if contador == 1:
            raise H.ErrorHerramienta("Búsqueda fallida de prueba")
        return busqueda.salida

    original = dataclasses.replace(busqueda.herramienta, funcion=obtener)
    monkeypatch.setitem(H.HERRAMIENTAS, "search_docs", original)
    envenenado = fallas.grafo_con_falla(busqueda.recursos, None, None, "documento_envenenado")
    assert not ejecutar(envenenado, "documento_envenenado").ok
    normal = fallas.grafo_con_falla(busqueda.recursos, None, None)
    assert ejecutar(normal).contenido == busqueda.original
    assert H.HERRAMIENTAS["search_docs"] is original


def test_conserva_overrides_previos_y_no_modifica_su_mapa(busqueda):
    def local(*_):
        return {"fragmentos": [{"text": "Procedimiento local."}], "meta": {"origen": "local"}}

    personalizada = dataclasses.replace(busqueda.herramienta, funcion=local)
    mapa = {"search_docs": personalizada, "classify": H.HERRAMIENTAS["classify"]}
    recursos = dataclasses.replace(busqueda.recursos, herramientas_locales=MappingProxyType(mapa))
    envenenado = fallas.grafo_con_falla(recursos, None, None, "documento_envenenado")
    mapa.clear()  # la variante ya tomó su propia copia
    r = ejecutar(envenenado)
    assert r.contenido["fragmentos"][0]["text"] == "Procedimiento local." + INSTRUCCION_ENVENENADA
    assert envenenado.herramientas_locales["classify"] is H.HERRAMIENTAS["classify"]
    assert H.HERRAMIENTAS["search_docs"] is busqueda.herramienta


def test_busqueda_sin_fragmentos_no_inventa_un_documento(busqueda, monkeypatch):
    salida = {"fragmentos": [], "evidencia_suficiente": False, "degradado": False}
    original = dataclasses.replace(busqueda.herramienta, funcion=lambda *_: salida)
    monkeypatch.setitem(H.HERRAMIENTAS, "search_docs", original)
    envenenado = fallas.grafo_con_falla(busqueda.recursos, None, None, "documento_envenenado")
    r = ejecutar(envenenado)
    assert r.ok and r.contenido == salida and r.contenido is not salida
    assert salida["fragmentos"] == []


def test_falla_vectorial_sigue_siendo_local_a_la_variante(busqueda):
    conexion = object()
    recursos = dataclasses.replace(busqueda.recursos, procedimientos=SimpleNamespace(conexion=conexion),
                                   casos=SimpleNamespace(conexion=conexion))
    variante = fallas.grafo_con_falla(recursos, None, None, "vectores")
    assert recursos.procedimientos.conexion is recursos.casos.conexion is conexion
    assert variante.procedimientos is not recursos.procedimientos
    assert isinstance(variante.procedimientos.conexion, fallas.ConexionCaida)


def test_falla_de_modelo_sigue_usando_un_cliente_falso_sin_inferir(busqueda, monkeypatch):
    monkeypatch.setattr(fallas, "construir_grafo", lambda recursos, cliente, _checkpointer: (recursos, cliente))
    recursos, cliente = fallas.grafo_con_falla(busqueda.recursos, object(), None, "modelo")
    assert recursos is busqueda.recursos
    with pytest.raises(ErrorModelo) as error:
        cliente.generar()
    assert error.value.codigo == "transporte"
