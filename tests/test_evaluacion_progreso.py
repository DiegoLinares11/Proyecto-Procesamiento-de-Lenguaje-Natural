"""Replay con modelos falsos; no inferencias, conexiones SQL ni secretos reales."""

import copy
import dataclasses
import json
import os
from collections import Counter

import pytest
from pydantic import BaseModel

from tickets_rag.evaluacion_progreso import (
    ClientePersistente, ErrorProgreso, ProgresoEvaluacion, evaluar_incremental, recursos_con_memoria,
)
from tickets_rag.modelo import Bloque, ErrorModelo, ResultadoModelo, UsoModelo


class Valor(BaseModel):
    numero: int


def resultado(n):
    valor = Valor(numero=n)
    return ResultadoModelo("gpt-6.2-sol", UsoModelo(input_tokens=10, output_tokens=2),
                           [Bloque("text", text=valor.model_dump_json())], valor)


def llamar(cliente, texto="dato fijo"):
    return cliente.generar(modelo="gpt-6.2-sol", sistema="RUBRICA_PRIVADA_NO_GUARDAR",
                            mensajes=[{"role": "user", "content": texto}], esquema=Valor,
                            permitir_herramientas=False, esfuerzo="low")


def test_cinco_votos_identicos_son_independientes_y_reanudar_voto4_no_repite_los3(tmp_path):
    pagos, bloqueo = [], [True]
    salida = tmp_path / "evaluacion"
    huella = {"banco": "fijo", "config": {"votos": 5}}
    def crear(progreso):
        def falso(**kwargs):
            if len(pagos) == 3 and bloqueo[0]:
                bloqueo[0] = False
                raise ErrorModelo("cuota")  # preflight: no se llamó marcar_envio
            c.marcar_envio()
            pagos.append(len(pagos) + 1)
            return resultado(pagos[-1])
        c = ClientePersistente(progreso, ("agente", "R01", "generacion"), generador_falso=falso)
        return c
    with pytest.raises(ErrorModelo, match="cuota"):
        with ProgresoEvaluacion(salida, huella) as p:
            c = crear(p)
            for _ in range(5):
                llamar(c)
    assert pagos == [1, 2, 3]
    with ProgresoEvaluacion(salida, huella, reanudar=True) as p:
        c = crear(p)
        votos = [llamar(c) for _ in range(5)]
        assert [r.parsed_output.numero for r in votos] == [1, 2, 3, 4, 5]
        assert sum(r.usage.input_tokens for r in votos) == 50  # uso original, no cero del replay
        p.terminar()
    assert pagos == [1, 2, 3, 4, 5]
    registros = [json.loads(f.read_text()) for f in (salida / ".progreso").glob("*.json")]
    modelos = [r for r in registros if r["claves"][0] == "modelo"]
    assert len(modelos) == 5 and len({r["peticion_sha256"] for r in modelos}) == 1
    assert {r["claves"][-1] for r in modelos} == {"0", "1", "2", "3", "4"}
    assert all(r["estado"] == "completo" for r in modelos)


def test_llamada_enviada_sin_resultado_no_se_reintenta(tmp_path):
    salida = tmp_path / "evaluacion"
    pagos = []
    with pytest.raises(KeyboardInterrupt):
        with ProgresoEvaluacion(salida, {}) as p:
            def falso(**kwargs):
                c.marcar_envio(); pagos.append(1)
                raise KeyboardInterrupt  # corte del proceso, sin error definitivo del proveedor
            c = ClientePersistente(p, ("agente", "R01", "generacion"), generador_falso=falso)
            llamar(c)
    with ProgresoEvaluacion(salida, {}, reanudar=True) as p:
        c = ClientePersistente(p, ("agente", "R01", "generacion"), generador_falso=lambda **k: pytest.fail("Repite inferencia ambigua"))
        with pytest.raises(ErrorProgreso) as error:
            llamar(c)
        assert error.value.causa == "envio_incierto"
    assert pagos == [1]


@pytest.mark.parametrize("codigo", ["timeout", "transporte", "formato"])
def test_fallo_definitivo_se_reproduce_sin_inferir_y_permite_continuar(tmp_path, codigo):
    pagos = []
    for reanudar in (False, True):
        with ProgresoEvaluacion(tmp_path / "eval", {}, reanudar=reanudar) as p:
            def falso(**kwargs):
                c.marcar_envio(); pagos.append(kwargs["mensajes"])
                if len(pagos) == 1:
                    raise ErrorModelo(codigo, transitorio=True)
                return resultado(7)
            c = ClientePersistente(p, ("agente", "R01", "generacion"), generador_falso=falso)
            with pytest.raises(ErrorModelo) as error:
                llamar(c)
            assert error.value.codigo == codigo
            c.comprobar()  # el grafo puede producir su fallback, o realizar su siguiente llamada válida
            assert llamar(c, "siguiente paso").parsed_output.numero == 7
            fallos = p.fallos_modelo()
            assert len(fallos) == 1 and fallos[0]["codigo"] == codigo
            assert fallos[0]["tokens"] is None and fallos[0]["reintentada"] is False
            if not reanudar:
                original = fallos
            else:
                assert fallos == original  # conserva latencia original, no la duración del replay
    assert len(pagos) == 2


def test_fallback_tras_timeout_es_etapa_completa_y_siguiente_caso_sigue(tmp_path):
    pagos = []
    def factory(p, ambito):
        def falso(**k):
            c.marcar_envio();pagos.append(ambito)
            if ambito[1] == "R01":
                raise ErrorModelo("timeout")
            return resultado(2)
        c = ClientePersistente(p, ambito, generador_falso=falso)
        return c
    def generar(s, id, c):
        try:
            valor = llamar(c).parsed_output.numero
            return {"segundos": 0.0, "valor": valor}
        except ErrorModelo as error:
            if error.codigo != "timeout":
                raise
            return {"segundos": 0.0, "degradado": True, "error_modelo": "timeout"}
    with ProgresoEvaluacion(tmp_path / "eval", {}) as p:
        filas = evaluar_incremental(p, {"agente": ["R01", "R02"]}, generar, lambda *a: {}, cliente_factory=factory)
        assert filas["agente"][0]["degradado"] and filas["agente"][1]["valor"] == 2
    with ProgresoEvaluacion(tmp_path / "eval", {}, reanudar=True) as p:
        assert evaluar_incremental(p, {"agente": ["R01", "R02"]}, lambda *a: pytest.fail(), lambda *a: pytest.fail()) == filas
    assert len(pagos) == 2


def test_cambio_de_peticion_en_el_mismo_ordinal_se_rechaza_antes_de_inferir(tmp_path):
    salida = tmp_path / "evaluacion"
    with ProgresoEvaluacion(salida, {}) as p:
        c = ClientePersistente(p, ("rag", "R01", "generacion"), generador_falso=lambda **k: resultado(1))
        llamar(c, "original")
    with ProgresoEvaluacion(salida, {}, reanudar=True) as p:
        c = ClientePersistente(p, ("rag", "R01", "generacion"), generador_falso=lambda **k: pytest.fail())
        with pytest.raises(ErrorProgreso) as error:
            llamar(c, "otra evidencia")
        assert error.value.causa == "cambio_peticion"


@pytest.mark.parametrize("cambio", [{"banco": "otro"}, {"modelo": "otro"}, {"config": "otra"}, {"codigo": "otra"}])
def test_fingerprint_distinto_no_mezcla_ni_sobrescribe_resultados(tmp_path, cambio):
    salida = tmp_path / "evaluacion"
    huella = {"banco": "uno", "modelo": "gpt", "config": "uno", "codigo": "uno"}
    with ProgresoEvaluacion(salida, huella):
        pass
    antes = (salida / "manifiesto_evaluacion.json").read_bytes()
    with pytest.raises(ErrorProgreso):
        with ProgresoEvaluacion(salida, {**huella, **cambio}, reanudar=True):
            pytest.fail()
    assert (salida / "manifiesto_evaluacion.json").read_bytes() == antes


def test_salida_anterior_y_lote_simultaneo_no_se_sobrescriben(tmp_path):
    antigua = tmp_path / "antigua"
    antigua.mkdir(); (antigua / "historico.json").write_text("conservar")
    with pytest.raises(ErrorProgreso):
        with ProgresoEvaluacion(antigua, {}):
            pytest.fail()
    assert (antigua / "historico.json").read_text() == "conservar"
    nueva = tmp_path / "nueva"
    with ProgresoEvaluacion(nueva, {}):
        with pytest.raises(ErrorProgreso) as error:
            with ProgresoEvaluacion(nueva, {}, reanudar=True):
                pytest.fail()
        assert error.value.causa == "ocupado"


def test_cache_privada_no_guarda_prompt_y_conserva_permisos(tmp_path):
    with ProgresoEvaluacion(tmp_path / "eval", {}) as p:
        c = ClientePersistente(p, ("rag", "R01", "generacion"), generador_falso=lambda **k: resultado(1))
        llamar(c, "TEXTO_PRIVADO_DEL_PROMPT_QUE_NO_PERSISTE")
        archivos = list(p.privado.glob("*.json"))
        assert archivos
        assert all("TEXTO_PRIVADO" not in f.read_text() and "RUBRICA_PRIVADA" not in f.read_text() for f in archivos)
        if os.name != "nt":
            assert p.privado.stat().st_mode & 0o777 == 0o700
            assert all(f.stat().st_mode & 0o777 == 0o600 for f in archivos)


def test_error_seguro_y_corrupcion_no_revelan_mensajes_ni_reutilizan_cache(tmp_path):
    salida = tmp_path / "eval"
    with pytest.raises(RuntimeError):
        with ProgresoEvaluacion(salida, {}) as p:
            p.etapa("rag", "R01", "generacion", lambda: (_ for _ in ()).throw(RuntimeError("SECRETO_NO_IMPRIMIR")))
    assert "SECRETO_NO_IMPRIMIR" not in (salida / "manifiesto_evaluacion.json").read_text()
    with ProgresoEvaluacion(salida, {}, reanudar=True) as p:
        c = ClientePersistente(p, ("rag", "R01", "generacion"), generador_falso=lambda **k: resultado(1))
        llamar(c)
        ruta = next(f for f in p.privado.glob("*.json") if json.loads(f.read_text())["claves"][0] == "modelo")
        r = json.loads(ruta.read_text());r["resultado"]["model"] = "otro";ruta.write_text(json.dumps(r))
    with ProgresoEvaluacion(salida, {}, reanudar=True) as p:
        c = ClientePersistente(p, ("rag", "R01", "generacion"), generador_falso=lambda **k: pytest.fail())
        with pytest.raises(ErrorProgreso):
            llamar(c)


def test_tres_sistemas_juez_y_ragas_reanudan_etapas_sin_repetir_ninguna_inferencia(tmp_path):
    salida = tmp_path / "eval"
    plan = {s: ["R01", "R02"] for s in ("agente", "rag", "linea_base")}
    pagos, callbacks, publicaciones, cortar = [], Counter(), [], [True]
    def factory(p, ambito):
        def falso(**kwargs):
            if ambito == ("agente", "R01", "ragas") and sum(a == ambito for a in pagos) == 1 and cortar[0]:
                cortar[0] = False
                raise ErrorModelo("cuota")
            c.marcar_envio(); pagos.append(ambito)
            return resultado(sum(a == ambito for a in pagos))
        c = ClientePersistente(p, ambito, generador_falso=falso)
        return c
    def generar(s, id, c):
        callbacks[(s, id, "generacion")] += 1
        return {"segundos": 0.0, "dato": llamar(c).parsed_output.numero, "contextos": {"doc": "contenido"}}
    def medir(s, id, f):
        callbacks[(s, id, "metricas")] += 1
        return {"metricas": {"medida": 1}}
    def juzgar(s, id, f, c):
        callbacks[(s, id, "juez")] += 1
        return {"medida": llamar(c).parsed_output.numero}
    def ragas(s, id, f, c):
        callbacks[(s, id, "ragas")] += 1
        return {"partes": [llamar(c).parsed_output.numero for _ in range(2)]}
    kwargs = dict(juzgar=juzgar, ragas=ragas, publicar=lambda f: publicaciones.append(copy.deepcopy(f)), cliente_factory=factory)
    with pytest.raises(ErrorModelo):
        with ProgresoEvaluacion(salida, {"plan": plan}) as p:
            evaluar_incremental(p, plan, generar, medir, **kwargs)
    assert len(pagos) == 8  # seis generaciones, un juez, primera parte de Ragas
    with ProgresoEvaluacion(salida, {"plan": plan}, reanudar=True) as p:
        filas = evaluar_incremental(p, plan, generar, medir, **kwargs)
        p.terminar()
    assert len(pagos) == 24  # seis generaciones + seis jueces + doce subllamadas Ragas
    assert all(callbacks[(s, id, "generacion")] == callbacks[(s, id, "metricas")] == 1 for s in plan for id in plan[s])
    assert filas["agente"][0]["ragas"]["partes"] == [1, 2]
    assert len(publicaciones) > 20 and all(len(fs) == 2 for fs in filas.values())
    with ProgresoEvaluacion(salida, {"plan": plan}, reanudar=True) as p:
        assert evaluar_incremental(p, plan, lambda *a: pytest.fail(), lambda *a: pytest.fail(),
                                   juzgar=lambda *a: pytest.fail(), ragas=lambda *a: pytest.fail()) == filas


def test_replay_classify_avanza_votos_omitidos_y_no_repite_herramientas_sql(tmp_path):
    from tickets_rag import herramientas as H
    from types import SimpleNamespace
    conteos = Counter()
    contexto = H.Contexto("TCK-2099-00001", "N1")
    recursos = H.Recursos(chunks=[], bm25=None, clasificador=SimpleNamespace(cliente=None))
    originales = dict(H.HERRAMIENTAS)
    def crear_clasificador(r, ctx, entrada):
        conteos["classify"] += 1
        return {"votos": [llamar(r.clasificador.cliente).parsed_output.numero for _ in range(5)]}
    def accion(r, ctx, entrada):
        conteos["SQL"] += 1
        return {"solicitud_id": 99, "nueva": True}
    recursos.herramientas_locales = {
        "classify": dataclasses.replace(H.HERRAMIENTAS["classify"], funcion=crear_clasificador),
        "take_action": dataclasses.replace(H.HERRAMIENTAS["take_action"], funcion=accion)}
    for reanudar in (False, True):
        with ProgresoEvaluacion(tmp_path / "eval", {}, reanudar=reanudar) as p:
            def falso(**k):
                c.marcar_envio();conteos["LLM"] += 1
                return resultado(conteos["LLM"])
            c = ClientePersistente(p, ("agente", "R01", "generacion"), generador_falso=falso)
            local = recursos_con_memoria(recursos, p, "agente", "R01", c)
            clas = H.ejecutar(local, contexto, "classify", {"text": "prueba"}, {"classify"})
            assert clas.ok and clas.contenido["votos"] == [1, 2, 3, 4, 5]
            assert llamar(c).parsed_output.numero == 6  # mismo prompt: el ordinal5 se conserva tras omitir classify
            accion_observada = H.ejecutar(local, contexto, "take_action", {"accion": "restablecer_mfa", "motivo": "prueba"}, {"take_action"})
            assert accion_observada.ok and accion_observada.contenido == {"solicitud_id": 99, "nueva": True}
    assert conteos == {"classify": 1, "SQL": 1, "LLM": 6}
    assert H.HERRAMIENTAS == originales and recursos.clasificador.cliente is None


def test_sql_incierto_no_se_repite_y_aprobacion_completa_se_reutiliza(tmp_path):
    llamadas = []
    with ProgresoEvaluacion(tmp_path / "eval", {}) as p:
        def cortar():
            llamadas.append(1)
            raise RuntimeError("fallo privado")
        with pytest.raises(RuntimeError):
            p.operacion(("aprobacion", "agente", "H07"), {}, cortar)
        with pytest.raises(ErrorProgreso) as error:
            p.operacion(("aprobacion", "agente", "H07"), {}, lambda: pytest.fail())
        assert error.value.causa == "sql_incierto"
        assert p.operacion(("aprobacion", "agente", "H08"), {}, lambda: {"estado": "rechazada"}) == {"estado": "rechazada"}
    with ProgresoEvaluacion(tmp_path / "eval", {}, reanudar=True) as p:
        assert p.operacion(("aprobacion", "agente", "H08"), {}, lambda: pytest.fail()) == {"estado": "rechazada"}
    assert llamadas == [1]
