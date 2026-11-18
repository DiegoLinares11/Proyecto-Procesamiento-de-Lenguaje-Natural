"""La caché conserva lo observado aunque el pool termine después del timeout.

Todos los recuperadores/efectos son falsos; no se cargan pesos, NER, SQL ni LLM.
"""

import copy
import dataclasses
import json
import threading
from collections import Counter
from concurrent.futures import Future, TimeoutError as TimeoutFuturo
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickets_rag import herramientas as H
from tickets_rag.evaluacion_progreso import ClientePersistente, ErrorProgreso, ProgresoEvaluacion, recursos_con_memoria
from tickets_rag.modelo import ErrorModelo


def cliente(progreso):
    return ClientePersistente(progreso, ("agente", "R01", "generacion"),
                              generador_falso=lambda **k: pytest.fail("No debe llamar al modelo"))


def recursos(funcion, nombre="search_docs"):
    return H.Recursos(chunks=[], bm25=None, clasificador=SimpleNamespace(cliente=None),
        herramientas_locales={nombre: dataclasses.replace(H.HERRAMIENTAS[nombre], funcion=funcion)})


def ejecutar(r, *, nombre="search_docs", argumentos=None, timeout=.1):
    return H.ejecutar(r, H.Contexto("TCK-2099-00001", "N1"), nombre,
                     argumentos or {"query": "consulta ficticia"}, {nombre}, timeout=timeout)


def test_timeout_observado_permanece_igual_tras_exito_tardio_y_reinicio(tmp_path, monkeypatch):
    monkeypatch.setattr(H.config, "REINTENTOS_HERRAMIENTA", 1)
    liberar, completados = threading.Event(), threading.Event()
    conteos, mutex = Counter(), threading.Lock()
    def recuperador_falso(*args):
        with mutex:
            conteos["iniciados"] += 1
        assert liberar.wait(3)
        with mutex:
            conteos["terminados"] += 1
            if conteos["terminados"] == 1:
                completados.set()
        return {"fragmentos": [{"text": "resultado tardío ficticio"}]}
    base = recursos(recuperador_falso)
    salida = tmp_path / "eval"
    with ProgresoEvaluacion(salida, {}) as p:
        local = recursos_con_memoria(base, p, "agente", "R01", cliente(p))
        try:
            observado = ejecutar(local)
            assert observado.ok is False and observado.intentos == 2
            assert conteos["iniciados"] == 1  # dos ventanas de espera sobre el mismo worker
            guardado = {f.name: f.read_bytes() for f in p.privado.glob("*.json")}
        finally:
            liberar.set()
        assert completados.wait(2)
        assert {f.name: f.read_bytes() for f in p.privado.glob("*.json")} == guardado
        assert len(guardado) == 1  # ningún journal interno del worker de recuperación
        dato = json.loads(next(iter(guardado.values())))
        assert dato["claves"][0] == "herramienta_observada"
        assert dato["resultado"]["observacion"] == dataclasses.asdict(observado)
    with ProgresoEvaluacion(salida, {}, reanudar=True) as p:
        local = recursos_con_memoria(base, p, "agente", "R01", cliente(p))
        replay = ejecutar(local)
        assert dataclasses.asdict(replay) == dataclasses.asdict(observado)
    assert conteos == {"iniciados": 1, "terminados": 1}


def test_sql_timeout_incierto_no_duplica_efecto_y_no_se_rehabilita_por_exito_tardio(tmp_path, monkeypatch):
    monkeypatch.setattr(H.config, "REINTENTOS_HERRAMIENTA", 1)
    liberar, terminado = threading.Event(), threading.Event()
    conteos = Counter()
    def sql_falso(*args):
        conteos["SQL"] += 1
        assert liberar.wait(3)
        terminado.set()
        return {"solicitud_id": 9, "estado": "pendiente", "nueva": True}
    base = recursos(sql_falso, "take_action")
    argumentos = {"accion": "restablecer_mfa", "motivo": "prueba ficticia"}
    salida = tmp_path / "eval"
    with ProgresoEvaluacion(salida, {}) as p:
        # Esperar el guard durable, no solo el retorno de la función SQL falsa.
        guardar = p.guardar
        def registrar(claves, registro):
            guardar(claves, registro)
            if claves[0] == "efecto_herramienta" and registro.get("estado") == "completo":
                efecto_guardado.set()
        efecto_guardado = threading.Event()
        p.guardar = registrar
        local = recursos_con_memoria(base, p, "agente", "R01", cliente(p))
        try:
            with pytest.raises(ErrorProgreso) as error:
                ejecutar(local, nombre="take_action", argumentos=argumentos)
            assert error.value.causa == "sql_incierto"
            observacion = next(f for f in p.privado.glob("*.json") if json.loads(f.read_text())["claves"][0] == "herramienta_observada")
            antes = observacion.read_bytes()
            assert json.loads(antes)["resultado"]["efecto_incierto"] is True
        finally:
            liberar.set()
        assert terminado.wait(2) and efecto_guardado.wait(2)
        assert observacion.read_bytes() == antes
    with ProgresoEvaluacion(salida, {}, reanudar=True) as p:
        local = recursos_con_memoria(base, p, "agente", "R01", cliente(p))
        with pytest.raises(ErrorProgreso) as error:
            ejecutar(local, nombre="take_action", argumentos=argumentos)
        assert error.value.causa == "sql_incierto"
    assert conteos["SQL"] == 1


def test_hook_preserva_overrides_runtime_de_inyeccion_y_falla_vectorial(tmp_path, monkeypatch):
    from tickets_rag import fallas
    monkeypatch.setattr(fallas, "construir_grafo", lambda r, *a: r)
    original = {"fragmentos": [{"text": "fuente ficticia original"}], "degradado": False}
    vistas = []
    def busqueda(r, *args):
        salida = copy.deepcopy(original)
        caida = isinstance(r.procedimientos.conexion, fallas.ConexionCaida)
        vistas.append(caida)
        salida["degradado"] = caida
        return salida
    base = recursos(busqueda)
    base.procedimientos = SimpleNamespace(conexion="conexion ficticia")
    base.casos = SimpleNamespace(conexion="conexion ficticia")
    registro_global = dict(H.HERRAMIENTAS)
    with ProgresoEvaluacion(tmp_path / "eval", {}) as p:
        local = recursos_con_memoria(base, p, "agente", "R01", cliente(p))
        envenenado = fallas.grafo_con_falla(local, None, None, "documento_envenenado")
        resultado = ejecutar(envenenado)
        assert resultado.ok and fallas.INSTRUCCION_ENVENENADA in resultado.contenido["fragmentos"][0]["text"]
        otro = recursos_con_memoria(base, p, "agente", "H09", cliente(p))
        caido = fallas.grafo_con_falla(otro, None, None, "vectores")
        resultado = ejecutar(caido)
        assert resultado.ok and resultado.contenido["degradado"] is True
    assert vistas == [False, True] and H.HERRAMIENTAS == registro_global
    assert original["fragmentos"][0]["text"] == "fuente ficticia original"
    assert base.procedimientos.conexion == "conexion ficticia" and base.ejecutor_observado is None


def test_validacion_y_permisos_se_observan_sin_ejecutar_efecto(tmp_path):
    def no_debe_ejecutar(*args):
        pytest.fail("Validación de H.ejecutar debe seguir antes de ejecutar SQL")
    base = recursos(no_debe_ejecutar, "take_action")
    with ProgresoEvaluacion(tmp_path / "eval", {}) as p:
        local = recursos_con_memoria(base, p, "agente", "R01", cliente(p))
        args = {"accion": "accion_inexistente", "motivo": "prueba"}
        observado = ejecutar(local, nombre="take_action", argumentos=args)
        replay = ejecutar(local, nombre="take_action", argumentos=args)
        assert not observado.ok and observado.intentos == 0
        assert dataclasses.asdict(observado) == dataclasses.asdict(replay)
        assert not any(json.loads(f.read_text())["claves"][0] == "efecto_herramienta" for f in p.privado.glob("*.json"))


def test_clasificador_cuota_no_queda_como_envelope_completo_ni_omite_guard_al_reanudar(tmp_path):
    from tests.test_evaluacion_progreso import llamar, resultado
    pagos, cortar = [], [True]
    def clasificar(r, *args):
        return {"votos": [llamar(r.clasificador.cliente).parsed_output.numero for _ in range(5)]}
    base = recursos(clasificar, "classify")
    for reanudar in (False, True):
        with ProgresoEvaluacion(tmp_path / "eval", {}, reanudar=reanudar) as p:
            def falso(**kwargs):
                if len(pagos) == 3 and cortar[0]:
                    cortar[0] = False
                    raise ErrorModelo("cuota")
                c.marcar_envio();pagos.append(len(pagos)+1)
                return resultado(pagos[-1])
            c = ClientePersistente(p, ("agente", "R01", "generacion"), generador_falso=falso)
            local = recursos_con_memoria(base, p, "agente", "R01", c)
            if not reanudar:
                with pytest.raises(ErrorModelo) as error:
                    ejecutar(local, nombre="classify", argumentos={"text": "ficticio"})
                assert error.value.codigo == "cuota"
                registros = [json.loads(f.read_text()) for f in p.privado.glob("*.json")]
                observado = next(r for r in registros if r["claves"][0] == "herramienta_observada")
                assert observado["estado"] == "incompleto"
            else:
                r = ejecutar(local, nombre="classify", argumentos={"text": "ficticio"})
                assert r.ok and r.contenido["votos"] == [1, 2, 3, 4, 5]
    assert pagos == [1, 2, 3, 4, 5]


def test_future_terminado_con_excepcion_pasajera_si_permita_nueva_ejecucion(monkeypatch):
    import psycopg
    monkeypatch.setattr(H.config, "REINTENTOS_HERRAMIENTA", 1)
    llamadas = []
    def pasajera(*args):
        llamadas.append(1)
        if len(llamadas) == 1:
            raise psycopg.OperationalError("ficticio")
        return {"ok": True}
    r = ejecutar(recursos(pasajera))
    assert r.ok and r.intentos == 2 and llamadas == [1, 1]


def test_future_en_cola_se_cancela_al_agotar_presupuesto(monkeypatch):
    pendiente = Future()
    envios = []
    class Pool:
        def submit(self, *args):
            envios.append(1)
            return pendiente
    monkeypatch.setattr(H, "_POOL", Pool())
    monkeypatch.setattr(H.config, "REINTENTOS_HERRAMIENTA", 1)
    r = ejecutar(recursos(lambda *a: pytest.fail("No debe iniciar un worker en cola")), timeout=.01)
    assert not r.ok and r.intentos == 2 and pendiente.cancelled()
    assert envios == [1]


def test_exito_justo_tras_timeout_no_se_lanza_de_nuevo(monkeypatch):
    class TerminaEnLimite(Future):
        def __init__(self):
            super().__init__();self.esperas = 0
        def result(self, timeout=None):
            self.esperas += 1
            if self.esperas == 1:
                self.set_result({"ok": True})
                raise TimeoutFuturo()
            return super().result(timeout=timeout)
    futuro, envios = TerminaEnLimite(), []
    class Pool:
        def submit(self, *args):
            envios.append(1)
            return futuro
    monkeypatch.setattr(H, "_POOL", Pool())
    monkeypatch.setattr(H.config, "REINTENTOS_HERRAMIENTA", 1)
    r = ejecutar(recursos(lambda *args: None))
    assert r.ok and r.intentos == 2 and futuro.esperas == 2 and envios == [1]
