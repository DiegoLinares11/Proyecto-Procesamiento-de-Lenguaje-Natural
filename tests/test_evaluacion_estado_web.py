"""El progreso web es un snapshot público, no un supervisor ni un evaluador."""

import json
import os

import pytest

from tickets_rag.evaluacion_estado_web import ErrorEstadoEvaluacion, obtener_progreso_evaluacion


def guardar(raiz, nombre, datos, *, marca=1_800_000_000):
    ruta = raiz / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    os.utime(ruta, (marca, marca))
    return ruta


@pytest.fixture
def progreso(tmp_path):
    carpeta = "resultados/codex_suscripcion/evaluacion/banco"
    manifiesto = {"estado": "en_curso", "huella": {"no_publicar": "datos privados"}}
    parcial = {
        "estado": "incompleto", "no_son_metricas_finales": True,
        "generaciones_completas": {"agente": 42, "rag": 23, "linea_base": 10},
        "generaciones_planeadas": {"agente": 42, "rag": 23, "linea_base": 23},
    }
    guardar(tmp_path, f"{carpeta}/manifiesto_evaluacion.json", manifiesto)
    guardar(tmp_path, f"{carpeta}/resumen_parcial.json", parcial, marca=1_800_000_010)
    return tmp_path, carpeta, parcial


def interrupcion(raiz, parcial, *, marca=1_800_000_020, **cambios):
    registro = {
        "estado_observado": "ejecución interrumpida; proceso evaluador no activo",
        "generaciones_completas": parcial["generaciones_completas"],
        "generaciones_pendientes": 13, "juez_ragas_completo": False,
        "operaciones_sin_desenlace": [{"archivo": "dato privado", "caso": "R11"}],
        **cambios,
    }
    return guardar(raiz, "resultados/cierre_tecnico/interrupcion_ultima.json", registro, marca=marca)


def test_sin_archivos_no_crea_directorios(tmp_path):
    estado = obtener_progreso_evaluacion(tmp_path)
    assert estado["estado"] == "sin_datos"
    assert estado["generaciones"] is None and estado["actualizado_utc"] is None
    assert estado["metricas_finales_disponibles"] is False
    assert list(tmp_path.iterdir()) == []


def test_manifiesto_en_curso_no_afirma_ejecucion_activa(progreso):
    raiz, _, _ = progreso
    estado = obtener_progreso_evaluacion(raiz)
    assert estado["estado"] == "por_completar"
    assert estado["interrupcion_confirmada"] is False
    assert estado["generaciones"] == {
        "completas": 75, "planeadas": 88, "pendientes": 13,
        "por_sistema": {"agente": {"completas": 42, "planeadas": 42},
                        "rag": {"completas": 23, "planeadas": 23},
                        "linea_base": {"completas": 10, "planeadas": 23}},
    }


def test_interrupcion_posterior_y_coherente_sin_metricas_ni_datos_privados(progreso):
    raiz, carpeta, parcial = progreso
    interrupcion(raiz, parcial)
    guardar(raiz, f"{carpeta}/.progreso/ignorado.json", {"credencial": "privada"})
    antes = {p: p.read_bytes() for p in raiz.rglob("*") if p.is_file()}
    estado = obtener_progreso_evaluacion(raiz)
    assert estado["estado"] == "interrumpida" and estado["interrupcion_confirmada"] is True
    assert estado["calificacion"] == "pendiente" and estado["metricas_finales_disponibles"] is False
    assert estado["solo_lectura"] is True
    assert "privad" not in json.dumps(estado)
    assert "sistemas" not in estado and "casos_que_pasan" not in estado
    assert antes == {p: p.read_bytes() for p in raiz.rglob("*") if p.is_file()}


@pytest.mark.parametrize("marca,cambios", [
    (1_799_999_000, {}),
    (1_800_000_020, {"generaciones_completas": {"agente": 42, "rag": 23, "linea_base": 9}}),
    (1_800_000_020, {"generaciones_pendientes": 12}),
    (1_800_000_020, {"juez_ragas_completo": True}),
    (1_800_000_020, {"estado_observado": "evaluación en curso"}),
])
def test_registro_viejo_o_ajeno_no_acredita_interrupcion(progreso, marca, cambios):
    raiz, _, parcial = progreso
    interrupcion(raiz, parcial, marca=marca, **cambios)
    assert obtener_progreso_evaluacion(raiz)["estado"] == "por_completar"


def test_estado_trabajo_antiguo_no_reemplaza_el_registro_coherente(progreso):
    raiz, _, parcial = progreso
    interrupcion(raiz, parcial)
    guardar(raiz, "resultados/cierre_tecnico/estado_trabajo.json", {
        "actualizacion": "2020-01-01T00:00:00+00:00", "banco": {"estado": "en curso", "pid": 123},
    })
    assert obtener_progreso_evaluacion(raiz)["estado"] == "interrumpida"


def test_cierre_final_coherente_prevalece_sobre_interrupcion(progreso):
    raiz, carpeta, parcial = progreso
    interrupcion(raiz, parcial)
    guardar(raiz, f"{carpeta}/resumen.json", {
        "estado": "completo", "sistemas": {"agente": {}, "rag": {}, "linea_base": {}},
    }, marca=1_800_000_030)
    # Un resumen suelto no acredita que la corrida cerró.
    assert obtener_progreso_evaluacion(raiz)["estado"] == "por_completar"
    guardar(raiz, f"{carpeta}/manifiesto_evaluacion.json", {"estado": "completo"}, marca=1_800_000_040)
    estado = obtener_progreso_evaluacion(raiz)
    assert estado["estado"] == "completa" and estado["metricas_finales_disponibles"] is True
    assert estado["interrupcion_confirmada"] is False
    assert estado["generaciones"] is None  # El parcial anterior no es el avance final.


@pytest.mark.parametrize("valor", [True, -1, 24, 1.5, "10", None])
def test_rechaza_conteos_invalidos_sin_fabricar_resultados(progreso, valor):
    raiz, carpeta, parcial = progreso
    parcial["generaciones_completas"]["linea_base"] = valor
    guardar(raiz, f"{carpeta}/resumen_parcial.json", parcial)
    with pytest.raises(ErrorEstadoEvaluacion):
        obtener_progreso_evaluacion(raiz)


def test_json_corrupto_da_error_y_sidecar_corrupto_solo_quita_confirmacion(progreso):
    raiz, carpeta, _ = progreso
    ruta = guardar(raiz, "resultados/cierre_tecnico/interrupcion_ultima.json", {})
    ruta.write_text("{", encoding="utf-8")
    assert obtener_progreso_evaluacion(raiz)["estado"] == "por_completar"
    (raiz / carpeta / "resumen_parcial.json").write_text("{", encoding="utf-8")
    with pytest.raises(ErrorEstadoEvaluacion):
        obtener_progreso_evaluacion(raiz)


def test_no_busca_corridas_preliminares_ni_historicas(tmp_path):
    for carpeta in ("resultados/evaluacion/banco", "resultados/codex_suscripcion/evaluacion/banco_cpu_preliminar"):
        guardar(tmp_path, f"{carpeta}/resumen.json", {"estado": "completo", "sistemas": {}})
    assert obtener_progreso_evaluacion(tmp_path)["estado"] == "sin_datos"
