"""Pruebas de la recuperación híbrida, las métricas por unidad y el filtro de permisos en pgvector."""

import pytest

from tickets_rag.evaluacion import calibrar_umbral, evaluar
from tickets_rag.ingesta import cargar_chunks
from tickets_rag.lexico import IndiceBM25, Resultado
from tickets_rag.recuperacion import Configuracion, RecuperadorHibrido


@pytest.fixture(scope="module")
def chunks():
    return cargar_chunks()


def test_rrf_con_una_sola_lista_conserva_el_orden_de_bm25(chunks):
    manual = [c for c in chunks if c["doc_type"] == "manual"]
    cfg = Configuracion(usar_vectores=False, usar_reranker=False, tipos=["manual"])
    hibrido = RecuperadorHibrido(manual, cfg).buscar("Error 0x80070005 al actualizar", rol="N1")
    bm25 = IndiceBM25(manual).buscar("Error 0x80070005 al actualizar", rol="N1")
    assert [r.chunk["chunk_id"] for r in hibrido] == [r.chunk["chunk_id"] for r in bm25]


def test_varios_chunks_de_un_articulo_cuentan_como_una_unidad():
    def chunk(unidad):
        return {"unidad": unidad, "doc_type": "articulo", "roles_permitidos": ["N1"]}

    caso = {"id": "X", "tipo": "f2", "answerable": True, "rol": "N1",
            "expected_sources": [{"unidad": "F2:a"}, {"unidad": "F2:b"}]}
    resultados = [Resultado(chunk(u), 1.0, n) for n, u in enumerate(["F2:a", "F2:a", "F2:z", "F2:b"], start=1)]
    filas, _ = evaluar(lambda c: resultados, [caso])
    assert filas[0]["recall@k"] == 1.0 and filas[0]["reciprocal_rank"] == 1.0


def test_umbral_separa_scores_y_ante_empate_elige_el_mas_bajo():
    r = calibrar_umbral(con_respuesta=[0.9, 0.5, 0.02], sin_respuesta=[0.001, 0.003])
    assert 0.003 < r["tau"] < 0.02 and r["falsas_abstenciones"] == 0 and r["abstenciones_omitidas"] == 0


@pytest.fixture(scope="module")
def conexion():
    from tickets_rag import vectores
    try:
        c = vectores.conectar()
        c.execute("SELECT 1 FROM chunks_bge_m3 LIMIT 1")
        return c
    except Exception:
        pytest.skip("pgvector no está disponible: docker compose up -d e indexar_vectores.py")


def test_busqueda_vectorial_nunca_devuelve_a_n1_un_procedimiento_de_n2(conexion, chunks):
    from tickets_rag import vectores
    from tickets_rag.embeddings import embeber

    roles = {c["chunk_id"]: c["roles_permitidos"] for c in chunks}
    for consulta in ["restablecer MFA de un usuario", "cuentas privilegiadas svc-", "abrir puertos en el firewall"]:
        for chunk_id, _ in vectores.buscar(conexion, "bge-m3", embeber("bge-m3", [consulta])[0], rol="N1", k=50):
            assert "N1" in roles[chunk_id]


def test_busqueda_vectorial_respeta_la_version_pedida(conexion, chunks):
    from tickets_rag import vectores
    from tickets_rag.embeddings import embeber

    version = {c["chunk_id"]: c["version"] for c in chunks}
    ids = vectores.buscar(conexion, "bge-m3", embeber("bge-m3", ["cierre de tickets"])[0], rol="N1", version="2026-1", k=20)
    assert ids and all(version[cid] == "2026-1" for cid, _ in ids)
