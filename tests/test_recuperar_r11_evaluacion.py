"""Recuperación auditada sólo en fixtures: nunca se ejecuta una inferencia."""

import hashlib
import json
import os
import stat

import pytest

from scripts import recuperar_r11_evaluacion as recuperacion


def digest(dato):
    return hashlib.sha256(json.dumps(dato, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def guardar(ruta, dato):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(dato, ensure_ascii=False, indent=2) + "\n").encode()
    ruta.write_bytes(raw)
    return raw


def registro(journal, claves, **datos):
    if datos.get("estado") == "completo":
        datos["resultado_sha256"] = digest(datos["resultado"])
    ruta = journal / (digest(claves) + ".json")
    guardar(ruta, {**datos, "claves": claves})
    return ruta


@pytest.fixture
def corrida(tmp_path):
    carpeta = tmp_path / "resultados/codex_suscripcion/evaluacion/banco"
    journal = carpeta / ".progreso"
    journal.mkdir(parents=True)
    (journal / ".lock").touch()
    fuente = tmp_path / "fuente_congelada.py"
    fuente.write_bytes(b"# FIXTURE, no es un evaluador real\n")
    huella = {"archivos_sha256": {fuente.name: hashlib.sha256(fuente.read_bytes()).hexdigest()}}
    huella_sha = digest(huella)
    guardar(carpeta / "manifiesto_evaluacion.json", {"estado": "en_curso", "huella": huella, "huella_sha256": huella_sha})
    guardar(carpeta / "resumen_parcial.json", {"estado": "incompleto", "no_son_metricas_finales": True,
                                               "generaciones_completas": recuperacion.COMPLETADAS,
                                               "generaciones_planeadas": recuperacion.PLANEADAS})
    for sistema, total in recuperacion.COMPLETADAS.items():
        for i in range(1, total + 1):
            caso = f"F{i:02d}"
            for etapa in ("generacion", "metricas"):
                registro(journal, ["etapa", sistema, caso, etapa], estado="completo", resultado={"fixture": i})
            registro(journal, ["modelo", sistema, caso, "generacion", digest([sistema, caso]), "0"],
                     estado="completo", resultado={"fixture": i})
    modelo = registro(journal, recuperacion.CLAVES_MODELO, estado="iniciado", enviada=True,
                      modelo="gpt-6.2-sol", peticion_sha256=recuperacion.PETICION_ESPERADA,
                      inicio_utc="2026-11-18T17:54:03.246781+00:00")
    etapa = registro(journal, recuperacion.CLAVES_ETAPA, estado="iniciado", tiempo_activo_s=0.0)
    registro(journal, ["orden_modelo", "linea_base", "R11", "generacion", "0"],
             estado="declarado", peticion_sha256=recuperacion.PETICION_ESPERADA)
    return {"raiz": tmp_path, "carpeta": carpeta, "journal": journal, "fuente": fuente,
            "huella": huella_sha, "modelo": modelo, "etapa": etapa}


def archivos(raiz):
    return {p.relative_to(raiz): p.read_bytes() for p in raiz.rglob("*") if p.is_file()}


def ejecutar(corrida, *, aplicar=False):
    return recuperacion.preparar_recuperacion(corrida["raiz"], aplicar=aplicar, huella_esperada=corrida["huella"])


def test_preflight_no_escribe_y_no_habilita_reintento(corrida):
    antes = archivos(corrida["raiz"])
    estado = ejecutar(corrida)
    assert estado["estado"] == "verificado" and estado["aplicado"] is False
    assert estado["generaciones_conservadas"] == 75 and estado["modelos_completos_conservados"] == 75
    assert antes == archivos(corrida["raiz"])
    assert corrida["modelo"].exists()


def test_aplicar_respalda_bytes_y_retira_exclusivamente_modelo_original(corrida):
    antes = archivos(corrida["raiz"])
    modelo_raw, etapa_raw = corrida["modelo"].read_bytes(), corrida["etapa"].read_bytes()
    estado = ejecutar(corrida, aplicar=True)
    assert estado["estado"] == "preparado" and estado["aplicado"] is True
    assert not corrida["modelo"].exists() and corrida["etapa"].read_bytes() == etapa_raw
    for relativa, raw in antes.items():
        if relativa != corrida["modelo"].relative_to(corrida["raiz"]):
            assert (corrida["raiz"] / relativa).read_bytes() == raw
    respaldo = corrida["journal"] / recuperacion.CARPETA_RESPALDO
    assert (respaldo / "modelo_original.json").read_bytes() == modelo_raw
    assert (respaldo / "etapa_original.json").read_bytes() == etapa_raw
    auditoria = json.loads((respaldo / "auditoria.json").read_bytes())
    assert auditoria["intento_previo"] == {"numero": 1, "estado": "sin_desenlace_no_adjudicado", "tokens": None,
                                           "tokens_estado": "desconocidos", "duracion_s": None, "duracion_estado": "desconocida"}
    assert auditoria["continuacion"]["numero_intento_auditado"] == 2
    assert auditoria["continuacion"]["maximo_reintentos"] == 1
    assert auditoria["sin_efectos_sql"] is True
    assert auditoria["copias"]["modelo_original.json"]["sha256"] == hashlib.sha256(modelo_raw).hexdigest()
    if os.name != "nt":
        assert stat.S_IMODE(respaldo.stat().st_mode) == 0o700
        assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in respaldo.iterdir())


@pytest.mark.parametrize("retry_activo", [False, True])
def test_aplicacion_unica_no_reinicia_si_ya_se_preparo_o_hay_otro_intento(corrida, retry_activo):
    ejecutar(corrida, aplicar=True)
    if retry_activo:
        registro(corrida["journal"], recuperacion.CLAVES_MODELO, estado="iniciado", enviada=True,
                 modelo="gpt-6.2-sol", peticion_sha256=recuperacion.PETICION_ESPERADA)
    antes = archivos(corrida["raiz"])
    for aplicar in (False, True):
        with pytest.raises(recuperacion.ErrorRecuperacion, match="Ya existe"):
            ejecutar(corrida, aplicar=aplicar)
    assert archivos(corrida["raiz"]) == antes


@pytest.mark.parametrize("defecto", ["fuente", "huella", "parcial", "otra_ambiguedad", "resultado_alterado", "no_enviada", "con_resultado", "etapa_completa", "falta_generacion"])
def test_inconsistencia_falla_cerrada_sin_retirar_ni_archivar(corrida, defecto):
    if defecto == "fuente":
        corrida["fuente"].write_bytes(b"CAMBIO NO ADMITIDO")
    elif defecto == "huella":
        p = corrida["carpeta"] / "manifiesto_evaluacion.json"
        d = json.loads(p.read_bytes());d["huella_sha256"] = "0" * 64;guardar(p, d)
    elif defecto == "parcial":
        p = corrida["carpeta"] / "resumen_parcial.json"
        d = json.loads(p.read_bytes());d["generaciones_completas"]["linea_base"] = 11;guardar(p, d)
    elif defecto == "otra_ambiguedad":
        registro(corrida["journal"], ["modelo", "rag", "F01", "generacion", "otra", "1"], estado="iniciado", enviada=True)
    elif defecto in {"no_enviada", "con_resultado"}:
        d = json.loads(corrida["modelo"].read_bytes())
        if defecto == "no_enviada":d["enviada"] = False
        else:d["resultado"] = {"no_es_resultado_aceptado": True}
        guardar(corrida["modelo"], d)
    elif defecto == "etapa_completa":
        registro(corrida["journal"], recuperacion.CLAVES_ETAPA, estado="completo", resultado={})
    else:
        p = next(p for p in corrida["journal"].glob("*.json") if json.loads(p.read_bytes()).get("claves") == ["etapa", "agente", "F01", "generacion"])
        if defecto == "falta_generacion":p.unlink()
        else:
            d = json.loads(p.read_bytes());d["resultado"]["fixture"] = "ALTERADO";guardar(p, d)
    antes = archivos(corrida["raiz"])
    with pytest.raises(recuperacion.ErrorRecuperacion):
        ejecutar(corrida, aplicar=True)
    assert archivos(corrida["raiz"]) == antes and corrida["modelo"].exists()


def test_otro_evaluador_con_candado_impide_preflight_y_aplicacion(corrida):
    import fcntl

    antes = archivos(corrida["raiz"])
    with (corrida["journal"] / ".lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            for aplicar in (False, True):
                with pytest.raises(recuperacion.ErrorRecuperacion, match="ocupada"):
                    ejecutar(corrida, aplicar=aplicar)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    assert archivos(corrida["raiz"]) == antes


def test_fallo_de_respaldo_no_retira_modelo_y_bloquea_otro_intento(corrida, monkeypatch):
    def fallo(*args, **kwargs):
        raise OSError("fallo de disco simulado")
    monkeypatch.setattr(recuperacion, "_guardar_privado", fallo)
    with pytest.raises(OSError):
        ejecutar(corrida, aplicar=True)
    assert corrida["modelo"].exists()
    with pytest.raises(recuperacion.ErrorRecuperacion, match="Ya existe"):
        ejecutar(corrida, aplicar=True)
