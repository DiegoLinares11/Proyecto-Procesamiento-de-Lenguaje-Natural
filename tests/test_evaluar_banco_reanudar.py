"""Integración del CLI con dobles locales; no conexiones, NER ni inferencias reales."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickets_rag.evaluacion_progreso import ErrorProgreso, ProgresoEvaluacion, evaluar_incremental
from tickets_rag.modelo import ErrorModelo


@pytest.fixture
def cli():
    ruta = Path(__file__).parents[1] / "scripts/evaluar_banco.py"
    spec = importlib.util.spec_from_file_location("evaluar_banco_reanudar_pruebas", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class Filas:
    def __init__(self, filas):
        self.filas = filas
    def fetchone(self):
        return self.filas[0]
    def __iter__(self):
        return iter(self.filas)


class Conexion:
    def __init__(self, *, ocupados=0, vector="[0.1,0.2]", historial="texto_ficticio", dbname="DB_PRIVADA"):
        self.ocupados, self.vector, self.historial = ocupados, vector, historial
        self.info = SimpleNamespace(host="HOST_PRIVADO", port=5433, dbname=dbname)
        self.consultas = []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def execute(self, sql, *args):
        self.consultas.append(sql)
        assert not any(verbo in sql.upper() for verbo in ("DELETE", "INSERT", "UPDATE", "TRUNCATE"))
        if "count(*)" in sql:
            return Filas([(self.ocupados,)])
        if "FROM tickets t" in sql:
            return Filas([(json.dumps({"id": 1, "texto": self.historial}),)])
        if "FROM chunks_bge_m3" in sql:
            return Filas([(json.dumps({"id": "F1-01", "embedding": self.vector}),)])
        if "pg_extension" in sql:
            return Filas([("0.8.0",)])
        if "server_version" in sql:
            return Filas([("17.7",)])
        if "pg_database" in sql:
            return Filas([(16384,)])
        return Filas([])


def test_espacio_acciones_solo_lectura_y_reanudar_no_borra_ni_consulta(cli, monkeypatch, tmp_path):
    conexion = Conexion()
    monkeypatch.setattr(cli.psycopg, "connect", lambda *a, **k: conexion)
    with ProgresoEvaluacion(tmp_path / "eval", {}) as progreso:
        cli.preparar_acciones_evaluacion(progreso)
        assert len(conexion.consultas) == 2
        registro = progreso.obtener("infra", "agente", "espacio_acciones")
        assert registro["resultado"]["historial_borrado"] is False
    monkeypatch.setattr(cli.psycopg, "connect", lambda *a, **k: pytest.fail("No consultar al reanudar"))
    with ProgresoEvaluacion(tmp_path / "eval", {}, reanudar=True) as progreso:
        cli.preparar_acciones_evaluacion(progreso)


def test_namespace_ocupado_bloquea_sin_borrar(cli, monkeypatch, tmp_path):
    conexion = Conexion(ocupados=1)
    monkeypatch.setattr(cli.psycopg, "connect", lambda *a, **k: conexion)
    with ProgresoEvaluacion(tmp_path / "eval", {}) as progreso:
        with pytest.raises(ErrorProgreso) as error:
            cli.preparar_acciones_evaluacion(progreso)
        assert error.value.causa == "sql_incierto"
        assert len(conexion.consultas) == 1


def test_huella_bd_cambia_con_vector_e_historia_sin_exportar_contenido(cli, monkeypatch):
    conexiones, opciones = [], []
    datos = {"vector": "[0.1,0.2]", "historial": "CUERPO_PRIVADO_NO_EXPORTAR"}
    monkeypatch.setattr(cli.vectores, "url_bd", lambda: "postgres://USUARIO_SECRETO:CLAVE_SECRETA@HOST_PRIVADO/db")
    def conectar(*args, **kwargs):
        opciones.append(kwargs)
        conexion = Conexion(**datos);conexiones.append(conexion)
        return conexion
    monkeypatch.setattr(cli.psycopg, "connect", conectar)
    original = cli.huella_base_datos()
    assert original["vectores_bge_m3"]["registros"] == original["historial"]["registros"] == 1
    datos["vector"] = "[0.2,0.1]"
    cambiado_vector = cli.huella_base_datos()
    assert original["vectores_bge_m3"] != cambiado_vector["vectores_bge_m3"]
    assert original["historial"] == cambiado_vector["historial"]
    datos["historial"] = "otro cuerpo"
    cambiado_historial = cli.huella_base_datos()
    assert cambiado_vector["historial"] != cambiado_historial["historial"]
    datos["dbname"] = "OTRA_DB_PRIVADA"
    otra_base = cli.huella_base_datos()
    assert cambiado_historial["vectores_bge_m3"] == otra_base["vectores_bge_m3"]
    assert cambiado_historial["identidad_bd_sha256"] != otra_base["identidad_bd_sha256"]
    assert all(o["options"] == "-c default_transaction_read_only=on" for o in opciones)
    assert all("REPEATABLE READ READ ONLY" in c.consultas[0] for c in conexiones)
    assert all("ORDER BY" in q for q in conexiones[0].consultas if q.startswith("SELECT row_to_json"))
    assert not any(s in json.dumps(original) for s in ("CUERPO_PRIVADO", "USUARIO_SECRETO", "CLAVE_SECRETA", "HOST_PRIVADO"))


def test_huella_incluye_hardware_modelos_codigo_y_corpus_sin_cargar_pesos(cli, monkeypatch, tmp_path):
    torch = SimpleNamespace(get_num_threads=lambda: 4, get_num_interop_threads=lambda: 1,
                            get_float32_matmul_precision=lambda: "highest")
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "tickets_rag.embeddings", SimpleNamespace(
        DISPOSITIVO="cpu", PRECISION="float32", PRECISION_RERANKER="float32", LOTE_EMBEDDINGS=16, LOTE_RERANKER=32, VACIAR_CACHE_MPS=False))
    hf = SimpleNamespace(try_to_load_from_cache=lambda *a: str(tmp_path / "snapshots" / "revision_fija" / "config.json"))
    monkeypatch.setitem(sys.modules, "huggingface_hub", hf)
    monkeypatch.setattr(cli, "huella_base_datos", lambda: {"vectores": {"sha256": "vector_fijo", "registros": 564}})
    monkeypatch.setattr(cli, "sha256_archivo", lambda p: hashlib.sha256(str(p).encode()).hexdigest())
    casos = [SimpleNamespace(id="R01")]
    banco = cli.config.EVALUACION / "banco.jsonl"
    huella = cli.huella_evaluacion(banco, casos, ["agente"], {"agente"}, [{"chunk_id": "uno", "text": "contenido"}])
    assert huella["hardware"]["dispositivo"] == "cpu" and huella["hardware"]["dtype_embeddings"] == "float32"
    assert huella["hardware"]["dtype_reranker"] == "float32"
    assert huella["hardware"]["torch_hilos"] == 4
    assert huella["cuota_maxima_porcentaje"] == 80 and huella["concurrencia"] == 1
    assert set(huella["modelos"]) == {"generador", "clasificador", "juez"}
    assert "src/tickets_rag/banco.py" in huella["archivos_sha256"]
    assert all(v == "revision_fija" for v in huella["hf_revisiones_config_local"].values())
    torch.get_num_threads = lambda: 2
    otra = cli.huella_evaluacion(banco, casos, ["agente"], {"agente"}, [{"chunk_id": "uno", "text": "contenido"}])
    assert huella != otra and otra["hardware"]["torch_hilos"] == 2
    monkeypatch.setitem(sys.modules, "tickets_rag.embeddings", SimpleNamespace(
        DISPOSITIVO="mps", PRECISION="float16", PRECISION_RERANKER="float32", LOTE_EMBEDDINGS=4, LOTE_RERANKER=4, VACIAR_CACHE_MPS=True))
    mixta = cli.huella_evaluacion(banco, casos, ["agente"], {"agente"}, [{"chunk_id": "uno", "text": "contenido"}])
    assert mixta["hardware"]["dtype_embeddings"] == "float16"
    assert mixta["hardware"]["dtype_reranker"] == "float32"
    assert huella["hardware"]["vaciar_cache_mps"] is False and mixta["hardware"]["vaciar_cache_mps"] is True
    assert mixta != otra


@pytest.mark.parametrize("codigo", ["timeout", "transporte", "formato"])
def test_generador_fallido_no_inventa_abstencion_metricas_ni_tokens(cli, codigo):
    contador = []
    def responder(*a, **k):
        contador.append(1);raise ErrorModelo(codigo)
    caso = cli.cargar_banco(cli.BANCO_OFICIAL)[0]
    fila = cli.correr_generador(caso, SimpleNamespace(responder=responder), {})
    assert fila["respuesta"] is None and fila["ejecucion_fallida"] is True and fila["error_modelo"] == codigo
    assert fila["uso"] == [] and "desconocido" in fila["uso_tokens_estado"]
    fila["metricas"] = cli.metricas_caso(caso, fila, {}, None)
    fila["contrato_valido"] = False
    assert all(v is None for v in fila["metricas"].values())
    resumen = cli.resumir("rag", [{"id": caso.id, **fila}], {caso.id: caso})
    assert resumen["ejecuciones_fallidas"] == 1 and resumen["casos_abstencion_medidos"] == 0
    assert resumen["abstencion_correcta"] is resumen["validez_contrato"] is None
    assert resumen["fidelidad"] is resumen["recall_at_5"] is None
    assert contador == [1]


def test_generador_cuota_propaga(cli):
    def responder(*a, **k):
        raise ErrorModelo("cuota")
    caso = cli.cargar_banco(cli.BANCO_OFICIAL)[0]
    with pytest.raises(ErrorModelo) as error:
        cli.correr_generador(caso, SimpleNamespace(responder=responder), {})
    assert error.value.codigo == "cuota"


def test_calentamiento_fuera_de_latencia_y_no_se_repite_al_reanudar(monkeypatch, tmp_path):
    from tickets_rag import evaluacion_progreso as modulo
    reloj = [0.0]
    monkeypatch.setattr(modulo.time, "perf_counter", lambda: reloj[0])
    def preparar(*args):
        reloj[0] += 100
    def generar(*args):
        reloj[0] += 3
        return {"segundos": 3.0}
    with ProgresoEvaluacion(tmp_path / "eval", {}) as p:
        filas = evaluar_incremental(p, {"rag": ["R01"]}, generar, lambda *a: {}, preparar=preparar)
        assert filas["rag"][0]["segundos"] == 3.0
    with ProgresoEvaluacion(tmp_path / "eval", {}, reanudar=True) as p:
        evaluar_incremental(p, {"rag": ["R01"]}, lambda *a: pytest.fail(), lambda *a: pytest.fail(),
                            preparar=lambda *a: pytest.fail("Calentamiento innecesario"))


def test_jsonl_publico_no_exporta_contextos_y_se_reemplaza_entero(cli, tmp_path):
    cli.guardar_filas(tmp_path, {"agente": [{"id": "R01", "contextos": {"uno": "NO_EXPORTAR_CONTEXTO"}, "respuesta": None}]})
    ruta = tmp_path / "casos_agente.jsonl"
    assert "NO_EXPORTAR" not in ruta.read_text() and len(ruta.read_text().splitlines()) == 1
    cli.guardar_filas(tmp_path, {"agente": [{"id": "R02"}]})
    assert json.loads(ruta.read_text()) == {"id": "R02"}
    assert not list(tmp_path.glob("*.tmp"))


def test_aprobacion_resuelta_se_reutiliza_sin_resolver_sql_nuevamente(cli, monkeypatch, tmp_path):
    caso = next(c for c in cli.cargar_banco(cli.BANCO_OFICIAL) if c.id == "H07")
    aprobaciones = []
    solicitud = {"solicitud_id": 9, "accion": "restablecer_mfa", "estado": "pendiente"}
    class Grafo:
        def __init__(self):
            self.estado = SimpleNamespace(next=("aprobar",), values={"solicitudes": [solicitud], "respuesta": None})
        def stream(self, entrada, *a, **k):
            if isinstance(entrada, cli.Command):
                aprobaciones.append(1)
                self.estado = SimpleNamespace(next=(), values={"solicitudes": [{**solicitud, "estado": "ejecutada"}], "respuesta": None})
            yield {"paso": {}}
        def get_state(self, *a):
            return self.estado
    monkeypatch.setattr(cli, "grafo_con_falla", lambda *a: Grafo())
    cliente = SimpleNamespace(comprobar=lambda: None)
    respuestas = []
    for reanudar in (False, True):
        with ProgresoEvaluacion(tmp_path / "eval", {}, reanudar=reanudar) as p:
            respuestas.append(cli.correr_agente(caso, None, cliente, None, progreso=p))
    assert aprobaciones == [1] and json.dumps(respuestas[0], sort_keys=True) == json.dumps(respuestas[1], sort_keys=True)
    assert respuestas[0]["solicitudes"][0]["estado"] == "ejecutada"
