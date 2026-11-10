"""Pruebas de la generación con un cliente falso: no llaman a la API ni gastan tokens."""

from types import SimpleNamespace

import pytest

from tickets_rag.contrato import Respuesta
from tickets_rag.generacion import GeneradorLineaBase, SalidaModelo
from tickets_rag.ingesta import cargar_chunks
from tickets_rag.lexico import IndiceBM25


class ClienteFalso:
    """Devuelve las salidas en orden y guarda lo que recibió."""

    def __init__(self, *salidas: SalidaModelo) -> None:
        self.salidas = list(salidas)
        self.llamadas = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.llamadas.append(kwargs)
        return SimpleNamespace(
            parsed_output=self.salidas.pop(0),
            stop_reason="end_turn",
            model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
        )


@pytest.fixture(scope="module")
def indice():
    # Solo el manual: estas pruebas revisan la lógica del generador, no la recuperación.
    return IndiceBM25([c for c in cargar_chunks() if c["doc_type"] == "manual"])


def chunk_de(indice, seccion):
    return next(c for c in indice.chunks if c["vigente"] and c["seccion"] == seccion)


def test_sin_resultados_se_abstiene_sin_llamar_al_modelo(indice):
    cliente = ClienteFalso()
    respuesta, traza = GeneradorLineaBase(indice, cliente).responder("zzz qqq", rol="N1")
    assert respuesta.abstained and respuesta.needs_human_review
    assert cliente.llamadas == [] and traza["motivo_abstencion"] == "sin_resultados"


def test_fuente_y_pagina_salen_de_los_metadatos(indice):
    chunk = chunk_de(indice, "4.5")
    cliente = ClienteFalso(SalidaModelo(answer="Use el Centro de Software.", citas=[chunk["chunk_id"]], sin_evidencia=False))
    respuesta, _ = GeneradorLineaBase(indice, cliente).responder("Error 0x80070005 al actualizar", rol="N1")
    assert not respuesta.abstained
    assert respuesta.sources[0].page == chunk["page"] and respuesta.sources[0].source == chunk["source"]
    Respuesta.model_validate_json(respuesta.model_dump_json())


def test_cita_inventada_se_reintenta_y_luego_se_abstiene(indice):
    inventada = SalidaModelo(answer="...", citas=["F9-c999"], sin_evidencia=False)
    cliente = ClienteFalso(inventada, inventada)
    respuesta, traza = GeneradorLineaBase(indice, cliente).responder("Error 0x80070005 al actualizar", rol="N1")
    assert len(cliente.llamadas) == 2
    assert respuesta.abstained and traza["motivo_abstencion"] == "citas_invalidas"


def test_el_texto_que_ve_el_modelo_va_enmascarado(indice):
    chunk = chunk_de(indice, "2.1")
    cliente = ClienteFalso(SalidaModelo(answer="ok", citas=[chunk["chunk_id"]], sin_evidencia=False))
    GeneradorLineaBase(indice, cliente).responder("Olvidé la contraseña, mi correo es ana@correo.example", rol="N1")
    enviado = cliente.llamadas[0]["messages"][0]["content"]
    assert "ana@correo.example" not in enviado and "[EMAIL_REDACTED]" in enviado


def test_el_modelo_puede_declarar_que_no_hay_evidencia(indice):
    cliente = ClienteFalso(SalidaModelo(answer="No hay evidencia.", citas=[], sin_evidencia=True))
    # «impresora» sí aparece en el manual, así que BM25 devuelve fragmentos y decide el modelo.
    respuesta, traza = GeneradorLineaBase(indice, cliente).responder("¿Cómo configuro la impresora 3D?", rol="N1")
    assert respuesta.abstained and traza["motivo_abstencion"] == "modelo_sin_evidencia"
