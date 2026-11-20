"""Fallos de congelación y oráculos del banco: no ejecutan un modelo ni una DB."""

import json
import shutil

import pytest

from tickets_rag import config
from tickets_rag.banco import BANCO_OFICIAL, cargar_banco, cumple_criterio
from tickets_rag.banco_revision import normalizar_pregunta, validar_contenido, validar_oficial
from tickets_rag.ingesta import cargar_chunks


@pytest.fixture
def casos():
    return cargar_banco(BANCO_OFICIAL)


def test_banco_congelado_se_verifica_sin_acreditar_revision_humana():
    resumen = validar_oficial()
    assert resumen["casos"] == 42 and resumen["inferencias_ejecutadas"] == 0
    manifiesto = json.loads(BANCO_OFICIAL.with_suffix(".manifiesto.json").read_text(encoding="utf-8"))
    assert resumen["revision_humana"] == manifiesto["revision_humana"]
    assert resumen["mide_desempeno"] is False


@pytest.mark.parametrize("defecto", ["duplicado", "sin_caso", "pagina", "rol", "sin_abstencion", "fuente", "herramienta"])
def test_un_banco_con_oraculos_inconsistentes_no_se_acepta(casos, defecto):
    if defecto == "duplicado":
        casos[1] = casos[1].model_copy(update={"question": casos[0].question.swapcase()})
    elif defecto == "sin_caso":
        casos.pop()
    elif defecto == "pagina":
        casos[0] = casos[0].model_copy(update={"expected_pages": [999]})
    elif defecto == "rol":
        casos[0] = casos[0].model_copy(update={"rol": "N0"})
    elif defecto == "sin_abstencion":
        i = next(i for i, c in enumerate(casos) if not c.answerable)
        casos[i] = casos[i].model_copy(update={"criterio": ["sin_cita_sql"]})
    elif defecto == "fuente":
        fuentes = [f.model_copy(update={"doc_id": "F1-inexistente"}) for f in casos[0].expected_sources]
        casos[0] = casos[0].model_copy(update={"expected_sources": fuentes})
    else:
        casos[0] = casos[0].model_copy(update={"herramientas_esperadas": ["sql_libre"]})
    with pytest.raises(ValueError):
        validar_contenido(casos, cargar_chunks(), [])


def test_no_reutiliza_literalmente_desarrollo_ni_f3(casos):
    with pytest.raises(ValueError, match="repite literalmente"):
        validar_contenido(casos, cargar_chunks(), [casos[0].question])
    assert normalizar_pregunta("¿REVISÓ   la conexión?") == normalizar_pregunta("reviso la conexion")


def test_aprobacion_invalida_debe_ejercitarse_y_conservar_la_misma_pausa(casos):
    caso = next(c for c in casos if c.id == "A07")
    solicitud = {"solicitud_id": 7, "accion": "cerrar_ticket_sin_confirmacion", "estado": "pendiente"}
    valida = {"respuesta": None, "solicitudes_en_pausa": [solicitud],
              "solicitudes": [dict(solicitud)], "en_pausa_al_final": True,
              "traza": [{"etapa": "aprobacion", "solicitud_id": 7, "error": "rol no autorizado"}]}
    assert cumple_criterio("confirmacion_invalida_sigue_pendiente", caso, valida, {})
    for cambio in ({"solicitudes_en_pausa": []}, {"solicitudes": []}, {"en_pausa_al_final": False}, {"traza": []},
                   {"solicitudes": [{**solicitud, "solicitud_id": 8}]},
                   {"solicitudes": [{**solicitud, "estado": "ejecutada"}]}):
        assert not cumple_criterio("confirmacion_invalida_sigue_pendiente", caso, {**valida, **cambio}, {})


def test_manifiesto_no_puede_omitir_las_referencias_requeridas(tmp_path):
    banco = tmp_path / BANCO_OFICIAL.name
    shutil.copy2(BANCO_OFICIAL, banco)
    meta = json.loads(BANCO_OFICIAL.with_suffix(".manifiesto.json").read_text())
    meta["referencias_sha256"] = {}
    banco.with_suffix(".manifiesto.json").write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="Faltan hashes"):
        validar_oficial(banco, raiz=config.RAIZ)


@pytest.mark.parametrize("archivo", ["banco", "referencia", "revision"])
def test_no_se_recalcula_el_hash_al_modificar_un_conjunto_congelado(tmp_path, archivo):
    manifiesto = BANCO_OFICIAL.with_suffix(".manifiesto.json")
    datos = json.loads(manifiesto.read_text())
    copia = tmp_path / BANCO_OFICIAL.name
    shutil.copy2(BANCO_OFICIAL, copia)
    shutil.copy2(manifiesto, copia.with_suffix(".manifiesto.json"))
    for relativo in [*datos["referencias_sha256"], datos["revision_casos"]["archivo"]]:
        destino = tmp_path / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config.RAIZ / relativo, destino)
    objetivo = {"banco": copia, "referencia": tmp_path / next(iter(datos["referencias_sha256"])),
                "revision": tmp_path / datos["revision_casos"]["archivo"]}[archivo]
    objetivo.write_bytes(objetivo.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="(?i)cambi|coincide"):
        validar_oficial(copia, raiz=tmp_path, chunks=cargar_chunks())
