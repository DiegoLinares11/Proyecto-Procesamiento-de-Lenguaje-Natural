import pytest

from tickets_rag.ingesta import cargar_chunks
from tickets_rag.lexico import IndiceBM25, tokenizar


def test_tokenizador_conserva_codigos_y_agrega_sus_partes():
    tokens = tokenizar("SIRA me da ERP-401 y Windows 0x80070005")
    assert "erp-401" in tokens and "erp" in tokens and "401" in tokens
    assert "0x80070005" in tokens


def test_tokenizador_ignora_tildes_y_mayusculas():
    assert tokenizar("Contraseña") == tokenizar("contrasena")


@pytest.fixture(scope="module")
def indice():
    return IndiceBM25(cargar_chunks())


def test_n1_nunca_recibe_procedimientos_solo_n2(indice):
    for consulta in ["restablecer MFA", "cuentas privilegiadas svc-", "firewall puertos", "base de datos de producción"]:
        for r in indice.buscar(consulta, rol="N1", top_k=50):
            assert "N1" in r.chunk["roles_permitidos"]


def test_n2_si_recibe_el_procedimiento_restringido(indice):
    secciones = [r.chunk["seccion"] for r in indice.buscar("restablecimiento de MFA", rol="N2")]
    assert "2.4" in secciones


def test_por_defecto_solo_recupera_la_version_vigente(indice):
    resultados = indice.buscar("cliente VPN", rol="N1", top_k=50)
    assert resultados and all(r.chunk["vigente"] for r in resultados)


def test_la_version_anterior_solo_si_se_pide(indice):
    resultados = indice.buscar("cierre sin confirmación días hábiles", rol="N1", version="2026-1")
    assert resultados and all(r.chunk["version"] == "2026-1" for r in resultados)


def test_consulta_sin_terminos_en_comun_no_devuelve_evidencia(indice):
    assert indice.buscar("zzz qqq", rol="N1") == []
