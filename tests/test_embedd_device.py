"""Contrato de hardware sin descargar pesos, cargar modelos ni usar red."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tickets_rag import config  # Resolver .env antes de aislar las variables de cada prueba.


@pytest.fixture
def cargar(monkeypatch):
    def importar(*, cuda=False, mps=True, entorno=None, fallo=False):
        for n in ("TICKETS_DISPOSITIVO", "TICKETS_PRECISION", "TICKETS_PRECISION_RERANKER", "TICKETS_LOTE_EMBEDDINGS", "TICKETS_LOTE_RERANKER", "TICKETS_VACIAR_CACHE_MPS"):
            monkeypatch.delenv(n, raising=False)
        for n, v in (entorno or {}).items():
            monkeypatch.setenv(n, v)
        llamadas = []

        class Modelo:
            def __init__(self, nombre, **kwargs):
                llamadas.append(("cargar", nombre, kwargs))
                if fallo:
                    raise RuntimeError("Fallo del dispositivo solicitado")
                self.nombre = nombre
                self.model = self
                self.max_seq_length = None

            def half(self):
                llamadas.append(("half", self.nombre))
                return self

            def encode(self, textos, **kwargs):
                llamadas.append(("encode", textos, kwargs))
                dim = 1024 if "bge-m3" in self.nombre else 384
                r = np.zeros((len(textos), dim), dtype=np.float16)
                r[:, :2] = [0.6, 0.8]
                return r

            def predict(self, pares, **kwargs):
                llamadas.append(("predict", pares, kwargs))
                return np.array([-3, 0, 3][:len(pares)], dtype=np.float16)

        class Identidad:
            pass

        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: cuda),
                                backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps)),
                                mps=SimpleNamespace(synchronize=lambda: llamadas.append(("sync",)),
                                                    empty_cache=lambda: llamadas.append(("empty_cache",))),
                                float16="dtype_float16", float32="dtype_float32", nn=SimpleNamespace(Identity=Identidad))
        monkeypatch.setitem(sys.modules, "torch", torch)
        monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=Modelo, CrossEncoder=Modelo))
        spec = importlib.util.spec_from_file_location("embeddings_dispositivo_test", Path(__file__).parents[1] / "src/tickets_rag/embeddings.py")
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        modulo.gc = SimpleNamespace(collect=lambda: llamadas.append(("gc",)))
        return modulo, llamadas, torch
    return importar


def test_cpu_por_defecto_se_conserva_aunque_mps_exista(cargar):
    e, llamadas, _ = cargar()
    assert (e.DISPOSITIVO, e.PRECISION, e.LOTE_EMBEDDINGS, e.LOTE_RERANKER) == ("cpu", "float32", 16, 32)
    bge = e.modelo_embeddings("bge-m3")
    assert bge.max_seq_length == 512 and e.modelo_embeddings("bge-m3") is bge
    mini = e.modelo_embeddings("minilm")
    assert mini.max_seq_length == 128
    e.reranker()
    cargas = [c for c in llamadas if c[0] == "cargar"]
    assert cargas == [("cargar", "BAAI/bge-m3", {"device": "cpu"}),
                      ("cargar", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", {"device": "cpu"}),
                      ("cargar", "BAAI/bge-reranker-v2-m3", {"max_length": 512, "device": "cpu"})]
    assert not any(c[0] == "half" for c in llamadas)


def test_cuda_anterior_mantiene_half_y_lotes(cargar):
    e, llamadas, _ = cargar(cuda=True)
    assert e.DISPOSITIVO == "cuda" and e.PRECISION == "float16"
    assert (e.LOTE_EMBEDDINGS, e.LOTE_RERANKER) == (16, 32)
    e.modelo_embeddings("bge-m3"); e.reranker()
    assert sum(c[0] == "half" for c in llamadas) == 2
    assert all("model_kwargs" not in c[2] for c in llamadas if c[0] == "cargar")


def test_mps_float16_se_carga_directo_sin_copia_half_posterior(cargar):
    e, llamadas, t = cargar(entorno={"TICKETS_DISPOSITIVO": "mps", "TICKETS_PRECISION": "float16"})
    assert (e.DISPOSITIVO, e.PRECISION, e.LOTE_EMBEDDINGS, e.LOTE_RERANKER) == ("mps", "float16", 4, 4)
    bge = e.modelo_embeddings("bge-m3"); e.reranker()
    assert bge.max_seq_length == 512
    assert all(c[2]["model_kwargs"] == {"dtype": t.float16} for c in llamadas if c[0] == "cargar")
    assert not any(c[0] == "half" for c in llamadas)


def test_mps_sin_precision_no_se_vuelve_float16_silenciosamente(cargar):
    e, llamadas, t = cargar(entorno={"TICKETS_DISPOSITIVO": "mps"})
    assert e.PRECISION == "float32"
    e.reranker()
    assert llamadas[0][2]["model_kwargs"] == {"dtype": t.float32}


def test_mps_mixto_carga_dtypes_por_clase_directamente(cargar):
    e, llamadas, t = cargar(entorno={"TICKETS_DISPOSITIVO": "mps", "TICKETS_PRECISION": "float16", "TICKETS_PRECISION_RERANKER": "float32"})
    assert e.PRECISION == "float16" and e.PRECISION_RERANKER == "float32"
    e.modelo_embeddings("bge-m3"); e.reranker()
    assert llamadas[0][2]["model_kwargs"] == {"dtype": t.float16}
    assert llamadas[1][2]["model_kwargs"] == {"dtype": t.float32}
    assert not any(c[0] == "half" for c in llamadas)


def test_reranker_precision_vacia_hereda_y_cuda_legacy_permanece(cargar):
    e, llamadas, _ = cargar(cuda=True, entorno={"TICKETS_PRECISION_RERANKER": "  "})
    assert e.PRECISION_RERANKER == e.PRECISION == "float16"
    e.modelo_embeddings("bge-m3"); e.reranker()
    assert sum(c[0] == "half" for c in llamadas) == 2


def test_cuda_reranker_float32_no_cambia_half_legacy_embeddings(cargar):
    e, llamadas, t = cargar(cuda=True, entorno={"TICKETS_PRECISION_RERANKER": "float32"})
    e.modelo_embeddings("bge-m3"); e.reranker()
    assert llamadas[0][2] == {"device": "cuda"}
    assert ("half", "BAAI/bge-m3") in llamadas
    assert llamadas[-1][2]["model_kwargs"] == {"dtype": t.float32}


def test_cpu_explicito_y_lotes_configurados_anulan_cuda_disponible(cargar):
    e, _, _ = cargar(cuda=True, entorno={"TICKETS_DISPOSITIVO": "cpu", "TICKETS_LOTE_EMBEDDINGS": "2", "TICKETS_LOTE_RERANKER": "3"})
    assert (e.DISPOSITIVO, e.PRECISION, e.LOTE_EMBEDDINGS, e.LOTE_RERANKER) == ("cpu", "float32", 2, 3)


def test_campos_env_vacios_mantienen_lotes_predeterminados(cargar):
    e, _, _ = cargar(entorno={"TICKETS_DISPOSITIVO": "mps", "TICKETS_LOTE_EMBEDDINGS": "", "TICKETS_LOTE_RERANKER": "  "})
    assert (e.LOTE_EMBEDDINGS, e.LOTE_RERANKER) == (4, 4)


@pytest.mark.parametrize("entorno,cuda,mps,error", [
    ({"TICKETS_DISPOSITIVO": "mps"}, False, False, RuntimeError),
    ({"TICKETS_DISPOSITIVO": "cuda"}, False, True, RuntimeError),
    ({"TICKETS_DISPOSITIVO": "auto"}, False, True, ValueError),
    ({"TICKETS_PRECISION": "bfloat16"}, False, True, ValueError),
    ({"TICKETS_PRECISION_RERANKER": "bfloat16"}, False, True, ValueError),
    ({"TICKETS_PRECISION_RERANKER": "float16"}, False, True, ValueError),
    ({"TICKETS_DISPOSITIVO": "cpu", "TICKETS_PRECISION": "float16"}, False, True, ValueError),
    ({"TICKETS_LOTE_EMBEDDINGS": "0"}, False, True, ValueError),
    ({"TICKETS_LOTE_RERANKER": "129"}, False, True, ValueError),
    ({"TICKETS_LOTE_RERANKER": "4.0"}, False, True, ValueError),
])
def test_configuracion_invalida_o_dispositivo_ausente_no_hace_fallback(cargar, entorno, cuda, mps, error):
    with pytest.raises(error):
        cargar(cuda=cuda, mps=mps, entorno=entorno)


def test_vectores_y_sigmoide_conservan_contrato_float32(cargar):
    e, llamadas, t = cargar(entorno={"TICKETS_DISPOSITIVO": "mps", "TICKETS_PRECISION": "float16"})
    v = e.embeber("bge-m3", ["control independiente"])
    assert v.shape == (1, 1024) and v.dtype == np.float32 and np.isfinite(v).all()
    assert np.allclose(np.linalg.norm(v, axis=1), 1, atol=2e-3)
    encoded = next(c for c in llamadas if c[0] == "encode")
    assert encoded[2] == {"batch_size": 4, "normalize_embeddings": True, "convert_to_numpy": True, "show_progress_bar": False}
    scores = e.puntuar("consulta", ["a", "b", "c"])
    esperado = (1 / (1 + np.exp(-np.array([-3, 0, 3], dtype=np.float64)))).astype(np.float32)
    np.testing.assert_array_equal(scores, esperado)
    predict = next(c for c in llamadas if c[0] == "predict")
    assert predict[2]["batch_size"] == 4 and isinstance(predict[2]["activation_fn"], t.nn.Identity)
    assert np.isfinite(scores).all() and scores.dtype == np.float32


def test_override_lote_y_entrada_vacia_no_cargan_reranker(cargar):
    e, llamadas, _ = cargar()
    r = e.puntuar("consulta", [])
    assert r.dtype == np.float32 and r.shape == (0,) and not llamadas
    e.embeber("minilm", ["caso"], lote=2)
    assert next(c for c in llamadas if c[0] == "encode")[2]["batch_size"] == 2
    for invalido in (0, -1, 129, True, "4"):
        with pytest.raises(ValueError):
            e.embeber("minilm", ["caso"], lote=invalido)


def test_fallo_al_cargar_mps_se_propaga_sin_reintentar_cpu(cargar):
    e, llamadas, _ = cargar(entorno={"TICKETS_DISPOSITIVO": "mps", "TICKETS_PRECISION": "float16"}, fallo=True)
    with pytest.raises(RuntimeError, match="dispositivo solicitado"):
        e.reranker()
    assert len(llamadas) == 1 and llamadas[0][2]["device"] == "mps"


@pytest.mark.parametrize("valor,esperado", [("", False), ("false", False), (" true ", True), ("TRUE", True)])
def test_cache_mps_opcional_booleano_estricto(cargar, valor, esperado):
    e, _, _ = cargar(entorno={"TICKETS_VACIAR_CACHE_MPS": valor})
    assert e.VACIAR_CACHE_MPS is esperado


@pytest.mark.parametrize("valor", ["1", "0", "yes", "no", "activar"])
def test_cache_mps_rechaza_booleano_ambiguo(cargar, valor):
    with pytest.raises(ValueError, match="true o false"):
        cargar(entorno={"TICKETS_VACIAR_CACHE_MPS": valor})


def test_cache_false_no_recolecta_ni_sincroniza_mps(cargar):
    e, llamadas, _ = cargar(entorno={"TICKETS_DISPOSITIVO": "mps", "TICKETS_PRECISION": "float16"})
    assert e.VACIAR_CACHE_MPS is False
    e.embeber("bge-m3", ["control"]); e.puntuar("consulta", ["texto"])
    assert not any(c[0] in {"gc", "sync", "empty_cache"} for c in llamadas)


def test_cache_true_recolecta_despues_de_carga_sin_descargar_modelos(cargar):
    e, llamadas, _ = cargar(entorno={"TICKETS_DISPOSITIVO": "mps", "TICKETS_PRECISION": "float16", "TICKETS_PRECISION_RERANKER": "float32", "TICKETS_VACIAR_CACHE_MPS": "true"})
    bge = e.modelo_embeddings("bge-m3"); rerank = e.reranker()
    assert [c[0] for c in llamadas] == ["cargar", "gc", "sync", "empty_cache", "cargar", "gc", "sync", "empty_cache"]
    assert e.modelo_embeddings("bge-m3") is bge and e.reranker() is rerank
    assert len(llamadas) == 8
    assert llamadas[0][2]["model_kwargs"]["dtype"] == "dtype_float16"
    assert llamadas[4][2]["model_kwargs"]["dtype"] == "dtype_float32"


def test_encode_se_convierte_numpy_antes_de_sync_y_empty_cache(cargar, monkeypatch):
    e, llamadas, _ = cargar(entorno={"TICKETS_DISPOSITIVO": "mps", "TICKETS_VACIAR_CACHE_MPS": "true"})
    modelo = e.modelo_embeddings("bge-m3"); llamadas.clear()
    class CpuArray(np.ndarray):
        def astype(self, *args, **kwargs):
            llamadas.append(("numpy_cpu",))
            return super().astype(*args, **kwargs)
    def encode(*args, **kwargs):
        assert kwargs["convert_to_numpy"] is True
        llamadas.append(("encode",))
        return np.array([[1, 0]], dtype=np.float16).view(CpuArray)
    monkeypatch.setattr(modelo, "encode", encode)
    r = e.embeber("bge-m3", ["control"])
    assert r.dtype == np.float32
    assert llamadas == [("encode",), ("numpy_cpu",), ("sync",), ("empty_cache",)]


def test_predict_numpy_sigmoide_inalterada_y_cache_posterior(cargar):
    e, llamadas, _ = cargar(entorno={"TICKETS_DISPOSITIVO": "mps", "TICKETS_VACIAR_CACHE_MPS": "true"})
    r = e.puntuar("consulta", ["a", "b", "c"])
    p = next(c for c in llamadas if c[0] == "predict")
    assert p[2]["convert_to_numpy"] is True
    np.testing.assert_array_equal(r, (1 / (1 + np.exp(-np.array([-3, 0, 3], dtype=np.float64)))).astype(np.float32))
    assert llamadas[-2:] == [("sync",), ("empty_cache",)]


@pytest.mark.parametrize("operacion", ["encode", "predict"])
def test_cache_se_vacia_tambien_si_la_inferencia_falla(cargar, monkeypatch, operacion):
    e, llamadas, _ = cargar(entorno={"TICKETS_DISPOSITIVO": "mps", "TICKETS_VACIAR_CACHE_MPS": "true"})
    modelo = e.modelo_embeddings("bge-m3") if operacion == "encode" else e.reranker()
    llamadas.clear()
    def fallar(*args, **kwargs):
        llamadas.append(("fallo",))
        raise RuntimeError("Error de operación local")
    monkeypatch.setattr(modelo, operacion, fallar)
    with pytest.raises(RuntimeError, match="operación local"):
        if operacion == "encode":
            e.embeber("bge-m3", ["control"])
        else:
            e.puntuar("consulta", ["texto"])
    assert llamadas == [("fallo",), ("sync",), ("empty_cache",)]


def test_sync_fallida_no_vacia_cache_anticipadamente(cargar, monkeypatch):
    e, llamadas, t = cargar(entorno={"TICKETS_DISPOSITIVO": "mps", "TICKETS_VACIAR_CACHE_MPS": "true"})
    def fallar():
        llamadas.append(("fallo_sync",))
        raise RuntimeError("No se pudo sincronizar")
    monkeypatch.setattr(t.mps, "synchronize", fallar)
    with pytest.raises(RuntimeError, match="sincronizar"):
        e.puntuar("consulta", ["texto"])
    assert llamadas[-1] == ("fallo_sync",) and ("empty_cache",) not in llamadas


@pytest.mark.parametrize("cuda", [False, True])
def test_cache_mps_no_actua_en_cpu_o_cuda(cargar, cuda):
    e, llamadas, _ = cargar(cuda=cuda, entorno={"TICKETS_VACIAR_CACHE_MPS": "true"})
    e.embeber("bge-m3", ["control"]); e.puntuar("consulta", ["texto"])
    assert not any(c[0] in {"gc", "sync", "empty_cache"} for c in llamadas)
