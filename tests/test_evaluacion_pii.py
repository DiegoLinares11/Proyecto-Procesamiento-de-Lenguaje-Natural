"""Prueba el evaluador con fakes: no carga Presidio ni ejecuta el NER del holdout."""

import importlib.util
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

from tickets_rag.evaluacion_pii import (
    SHA256_BANCO,
    cargar_banco,
    evaluar_caso,
    resumir,
    sha256_archivo,
    validar_caso,
)

RAIZ = Path(__file__).resolve().parents[1]
BANCO = RAIZ / "evaluacion" / "pii_sembrada.jsonl"


@dataclass(frozen=True)
class DeteccionFalsa:
    tipo: str
    inicio: int
    fin: int
    score: float = 1.0


def caso_prueba():
    return {
        "id": "PII-01",
        "texto": "María José usa HTTP 503.",
        "entidades": [{"tipo": "PERSON", "inicio": 0, "fin": 10}],
        "negativos": [{"inicio": 15, "fin": 23, "motivo": "estado_http"}],
    }


def test_match_exacto_conserva_acentos_y_no_copia_valores_al_diagnostico():
    caso = caso_prueba()
    r = evaluar_caso(caso, [DeteccionFalsa("PERSON", 0, 10)], "[PERSON_REDACTED] usa HTTP 503.", {"PERSON": 1})
    assert r["estricto"] == {"tp": 1, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert r["redaccion"]["integra"] and r["redaccion"]["recall_efectivo"] == 1
    assert "María" not in json.dumps(r, ensure_ascii=False)
    assert r["negativos"]["fragmentos_afectados"] == 0


@pytest.mark.parametrize("inicio,fin,salida", [
    (0, 5, "[PERSON_REDACTED] José usa HTTP 503."),
    (0, 14, "[PERSON_REDACTED] HTTP 503."),
])
def test_span_parcial_o_demasiado_amplio_no_es_tp(inicio, fin, salida):
    r = evaluar_caso(caso_prueba(), [DeteccionFalsa("PERSON", inicio, fin)], salida, {"PERSON": 1})
    assert (r["estricto"]["tp"], r["estricto"]["fp"], r["estricto"]["fn"]) == (0, 1, 1)
    assert r["redaccion"]["integra"]  # sustituyó fielmente el span; detectó la entidad mal
    assert r["estricto"]["recall"] == r["redaccion"]["recall_efectivo"] == 0


def test_detecciones_duplicadas_no_aumentan_recall_y_agregan_fp():
    pred = DeteccionFalsa("PERSON", 0, 10)
    r = evaluar_caso(caso_prueba(), [pred, pred], "[PERSON_REDACTED] usa HTTP 503.", {"PERSON": 2})
    assert (r["estricto"]["tp"], r["estricto"]["fp"], r["estricto"]["fn"]) == (1, 1, 0)
    assert r["estricto"]["precision"] == 0.5
    assert not r["redaccion"]["integra"] and r["redaccion"]["recall_efectivo"] == 0


def test_tipo_incorrecto_no_se_empareja_por_solapamiento():
    r = evaluar_caso(caso_prueba(), [DeteccionFalsa("EMAIL", 0, 10)], "[EMAIL_REDACTED] usa HTTP 503.", {"EMAIL": 1})
    assert r["estricto"]["tp"] == 0
    assert r["por_tipo"]["PERSON"]["fn"] == 1 and r["por_tipo"]["EMAIL"]["fp"] == 1


def test_fn_sin_detecciones_no_es_una_redaccion_exitosa():
    caso = caso_prueba()
    r = evaluar_caso(caso, [], caso["texto"], {})
    assert r["estricto"]["fn"] == 1 and r["estricto"]["precision"] is None
    assert r["redaccion"]["integra"] and r["redaccion"]["recall_efectivo"] == 0


def test_fp_tecnico_se_cuenta_global_y_por_fragmento_negativo():
    pred = [DeteccionFalsa("PERSON", 0, 10), DeteccionFalsa("PHONE", 15, 23)]
    r = evaluar_caso(caso_prueba(), pred, "[PERSON_REDACTED] usa [PHONE_REDACTED].", {"PERSON": 1, "PHONE": 1})
    assert (r["estricto"]["tp"], r["estricto"]["fp"], r["estricto"]["fn"]) == (1, 1, 0)
    assert r["negativos"] == {"fragmentos": 1, "fragmentos_afectados": 1, "detecciones_sobre_negativos": 1}
    assert r["por_tipo"]["PHONE"]["fp"] == 1


@pytest.mark.parametrize("salida", ["", "texto genérico sin datos", "[PERSON_REDACTED]", "Prefijo [PERSON_REDACTED] usa HTTP 503."])
def test_cambiar_o_vaciar_texto_no_acredita_redaccion(salida):
    r = evaluar_caso(caso_prueba(), [DeteccionFalsa("PERSON", 0, 10)], salida, {"PERSON": 1})
    assert r["estricto"]["recall"] == 1  # capacidad del detector medida aparte
    assert not r["redaccion"]["integra"]
    assert r["redaccion"]["entidades_efectivas"] == r["redaccion"]["recall_efectivo"] == 0
    assert not resumir([r])["cumple_meta"]


@pytest.mark.parametrize("conteos", [{}, {"PERSON": 2}, {"PERSON": True}, {"PERSON": -1}, {"PERSON": 1, "EMAIL": 0}])
def test_conteos_incorrectos_impiden_acreditar_redaccion(conteos):
    r = evaluar_caso(caso_prueba(), [DeteccionFalsa("PERSON", 0, 10)], "[PERSON_REDACTED] usa HTTP 503.", conteos)
    assert "conteos_inconsistentes" in r["redaccion"]["errores"]
    assert r["redaccion"]["recall_efectivo"] == 0


@pytest.mark.parametrize("pred", [
    DeteccionFalsa("PERSON", -1, 10), DeteccionFalsa("PERSON", 0, 1000),
    DeteccionFalsa("PERSON", 10, 10), DeteccionFalsa("PERSON", False, 10),
    DeteccionFalsa("VALOR_A_NO_COPIAR", 0, 10), {"valor": "VALOR_A_NO_COPIAR"},
])
def test_prediccion_invalida_cuenta_como_fp_sin_filtrar_su_valor(pred):
    r = evaluar_caso(caso_prueba(), [pred], "", {})
    assert (r["estricto"]["tp"], r["estricto"]["fp"], r["estricto"]["fn"]) == (0, 1, 1)
    assert r["detecciones_invalidas"] == 1 and not r["redaccion"]["integra"]
    assert "VALOR_A_NO_COPIAR" not in json.dumps(r)


def test_nombres_repetidos_se_asignan_a_offsets_distintos():
    caso = {"id": "PII-01", "texto": "Ana y Ana", "entidades": [
        {"tipo": "PERSON", "inicio": 0, "fin": 3}, {"tipo": "PERSON", "inicio": 6, "fin": 9}], "negativos": []}
    r = evaluar_caso(caso, [DeteccionFalsa("PERSON", 0, 3)], "[PERSON_REDACTED] y Ana", {"PERSON": 1})
    assert r["estricto"]["recall"] == 0.5
    assert r["redaccion"]["recall_efectivo"] == 0.5
    assert r["falsos_negativos"] == [{"tipo": "PERSON", "inicio": 6, "fin": 9}]


def test_sin_referencia_no_inventa_recall_uno():
    r = evaluar_caso({"id": "NEG-01", "texto": "HTTP 503", "entidades": []}, [], "HTTP 503", {})
    resumen = resumir([r])
    assert resumen["estricto"]["precision"] is resumen["estricto"]["recall"] is resumen["estricto"]["f1"] is None
    assert resumen["redaccion"]["recall_efectivo"] is None and not resumen["cumple_meta"]
    assert resumir([])["estricto"]["recall"] is None


def test_anotaciones_de_referencia_duplicadas_o_negativos_superpuestos_se_rechazan():
    caso = caso_prueba()
    caso["entidades"].append(dict(caso["entidades"][0]))
    with pytest.raises(ValueError, match="duplicadas"):
        validar_caso(caso)
    caso = caso_prueba()
    caso["negativos"][0]["inicio"] = 1
    with pytest.raises(ValueError, match="negativo solapa"):
        validar_caso(caso)


def test_holdout_fijo_contiene_30_textos_56_entidades_y_24_negativos():
    casos = cargar_banco(BANCO)
    assert len(casos) == 30 and sha256_archivo(BANCO) == SHA256_BANCO
    assert Counter(e["tipo"] for c in casos for e in c["entidades"]) == {
        "PERSON": 25, "EMAIL": 10, "PHONE": 9, "DPI": 7, "CARD": 5}
    assert sum(any(e["tipo"] == "PERSON" for e in c["entidades"]) for c in casos) == 24
    assert sum(len(c["negativos"]) for c in casos) == 24
    assert all(c["origen"] == "sintetico_ia_seguridad" for c in casos)


def test_pii_no_nominal_sembrada_tiene_formato_valido_sin_usar_el_detector():
    for caso in cargar_banco(BANCO):
        for entidad in caso["entidades"]:
            valor = caso["texto"][entidad["inicio"]:entidad["fin"]]
            tipo = entidad["tipo"]
            if tipo == "EMAIL":
                assert re.fullmatch(r"[\w.+-]+@[\w.-]+\.example", valor)
            elif tipo == "PHONE":
                assert re.fullmatch(r"(?:\+502[ -]?)?[2-7]\d{3}[ -]?\d{4}", valor)
            elif tipo == "DPI":
                digitos = re.sub(r"\D", "", valor)
                assert len(digitos) == 13 and digitos[-4:] == "0101"
                assert sum(int(c) * (i + 2) for i, c in enumerate(digitos[:8])) % 11 == int(digitos[8])
            elif tipo == "CARD":
                digitos = [int(d) for d in re.sub(r"\D", "", valor)][::-1]
                assert len(digitos) in (15, 16)
                assert sum(d if i % 2 == 0 else (2*d-9 if 2*d > 9 else 2*d) for i, d in enumerate(digitos)) % 10 == 0


def test_cambiar_un_byte_del_holdout_se_rechaza(tmp_path):
    alterado = tmp_path / "pii.jsonl"
    alterado.write_bytes(BANCO.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="SHA-256"):
        cargar_banco(alterado)


def script(*, metadata_falsa=True):
    spec = importlib.util.spec_from_file_location("evaluar_pii_offline", RAIZ / "scripts" / "evaluar_pii.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    # Cada ejecución fake debe seguir siendo independiente de los modelos instalados.
    if metadata_falsa:
        modulo._metadata_modelos = lambda modelos: {
            idioma: {"distribucion": m["nombre"], "version_instalada": m["version"],
                     "archivos_sha256": {"METADATA": "0" * 64, "meta.json": "1" * 64}}
            for idioma, m in modelos.items()
        }
    return modulo


def salud_falsa():
    return {"local": True, "ner_disponible": True, "modelo_personas": "es_core_news_md",
            "version_modelo_personas": "3.8.0", "spacy": "fake-offline", "presidio_analyzer": "fake-offline",
            "score_personas": 0.5, "tipos": ["PERSON", "EMAIL", "PHONE", "DPI", "CARD"],
            "idioma": "es", "modelos": {
                "es": {"nombre": "es_core_news_md", "version": "3.8.0", "componentes": ["tok2vec", "morphologizer", "attribute_ruler", "ner"]},
                "en": {"nombre": "en_core_web_md", "version": "3.8.0", "componentes": ["tok2vec", "tagger", "attribute_ruler", "ner"]}},
            "componentes_activos": ["tok2vec", "morphologizer", "attribute_ruler", "ner"],
            "configuracion": "presidio_spacy_pos_bilingue_v2", "filtro_personas": "NER_PERSON_y_token_PROPN"}


def fakes_de_referencia():
    # Oráculo sólo de pruebas para comprobar el cálculo y la escritura, nunca una métrica NER real.
    por_texto = {c["texto"]: c for c in cargar_banco(BANCO)}

    def detector(texto):
        return [DeteccionFalsa(**e) for e in por_texto[texto]["entidades"]]

    def enmascarador(texto):
        entidades = por_texto[texto]["entidades"]
        salida = texto
        for e in sorted(entidades, key=lambda x: x["inicio"], reverse=True):
            salida = salida[:e["inicio"]] + f"[{e['tipo']}_REDACTED]" + salida[e["fin"]:]
        return salida, dict(Counter(e["tipo"] for e in entidades))

    return detector, enmascarador


def test_cli_con_fakes_guarda_manifiesto_versiones_y_no_copia_texto(tmp_path):
    detector, enmascarador = fakes_de_referencia()
    codigo, salida = script().ejecutar(BANCO, tmp_path, detector=detector, enmascarador=enmascarador, informador=salud_falsa)
    assert codigo == 0
    manifiesto = json.loads((salida / "manifiesto.json").read_text())
    resumen = json.loads((salida / "resumen.json").read_text())
    assert manifiesto["estado"] == "completo" and manifiesto["textos_completos"] == 30
    assert manifiesto["banco"]["sha256_observado"] == SHA256_BANCO
    assert manifiesto["detector"]["spacy"] == "fake-offline"
    assert manifiesto["version_formato"] == 2
    assert manifiesto["interpretacion"] == "comprobacion_versionada_no_holdout_ciego_nuevo"
    assert manifiesto["detector"]["modelos"] == salud_falsa()["modelos"]
    assert manifiesto["detector"]["componentes_activos"] == salud_falsa()["componentes_activos"]
    assert manifiesto["detector"]["configuracion"] == "presidio_spacy_pos_bilingue_v2"
    assert manifiesto["detector"]["filtro_personas"] == "NER_PERSON_y_token_PROPN"
    assert manifiesto["metadata_modelos"]["en"]["version_instalada"] == "3.8.0"
    assert manifiesto["dependencias_sha256"] == {
        nombre: sha256_archivo(RAIZ / nombre) for nombre in ("pyproject.toml", "uv.lock")}
    assert len(manifiesto["codigo_sha256"]) == 3
    assert resumen["estricto"]["tp"] == 56 and resumen["cumple_meta"]
    assert len((salida / "casos.jsonl").read_text().splitlines()) == 30
    contenido = "".join(p.read_text() for p in salida.iterdir())
    assert "María Fernanda" not in contenido and "4111 1111" not in contenido


@pytest.mark.parametrize("informacion", [{}, {**salud_falsa(), "ner_disponible": False},
                                         {**salud_falsa(), "version_modelo_personas": "otra"},
                                         {**salud_falsa(), "modelos": None},
                                         {**salud_falsa(), "configuracion": None}])
def test_cli_sin_modelo_saludable_no_infiere_ni_publica_metricas(tmp_path, informacion):
    def prohibido(texto):
        pytest.fail("No debe analizar texto si la salud falla")

    codigo, salida = script().ejecutar(BANCO, tmp_path, detector=prohibido, enmascarador=prohibido,
                                      informador=lambda: informacion)
    assert codigo == 2 and not (salida / "resumen.json").exists()
    manifiesto = json.loads((salida / "manifiesto.json").read_text())
    assert manifiesto["estado"] == "fallido" and manifiesto["metricas"] is None
    assert manifiesto["textos_completos"] == 0 and manifiesto["error"]["etapa"] == "salud_detector"


def distribuciones_falsas(tmp_path, *, version="3.8.0", metadata=True, meta_json=True):
    class PaqueteFalso:
        def __init__(self, nombre):
            self.version = version
            self.nombre = nombre
            self.files = [PurePosixPath(f"{nombre}/config.cfg")]
            if meta_json:
                self.files.append(PurePosixPath(f"{nombre}/meta.json"))
            for archivo in self.files:
                ruta = tmp_path / str(archivo)
                ruta.parent.mkdir(parents=True, exist_ok=True)
                ruta.write_text("metadatos de modelo falso sin pesos", encoding="utf-8")

        def read_text(self, nombre):
            assert nombre == "METADATA"
            return f"Name: {self.nombre}\nVersion: {self.version}\n" if metadata else None

        def locate_file(self, archivo):
            return tmp_path / str(archivo)

    return PaqueteFalso


def test_hashes_metadata_de_ambos_modelos_sin_cargar_ner(tmp_path, monkeypatch):
    modulo = script(metadata_falsa=False)
    monkeypatch.setattr(modulo, "distribution", distribuciones_falsas(tmp_path))
    modelos = modulo._metadata_modelos(salud_falsa()["modelos"])
    for idioma, nombre in (("es", "es_core_news_md"), ("en", "en_core_web_md")):
        m = modelos[idioma]
        assert m["distribucion"] == nombre and m["version_instalada"] == "3.8.0"
        assert set(m["archivos_sha256"]) == {"METADATA", f"{nombre}/meta.json", f"{nombre}/config.cfg"}
        assert all(re.fullmatch("[a-f0-9]{64}", h) for h in m["archivos_sha256"].values())
        assert m["archivos_sha256"][f"{nombre}/meta.json"] == sha256_archivo(tmp_path / nombre / "meta.json")


@pytest.mark.parametrize("cambio", ["declaracion_en", "version_instalada", "sin_metadata", "sin_meta_json"])
def test_metadata_ausente_o_inconsistente_falla_antes_de_analizar(tmp_path, monkeypatch, cambio):
    modulo = script(metadata_falsa=False)
    kwargs = {"version": "3.7.0"} if cambio == "version_instalada" else {}
    if cambio == "sin_metadata":
        kwargs["metadata"] = False
    if cambio == "sin_meta_json":
        kwargs["meta_json"] = False
    monkeypatch.setattr(modulo, "distribution", distribuciones_falsas(tmp_path, **kwargs))
    modelos = salud_falsa()["modelos"]
    if cambio == "declaracion_en":
        modelos["en"]["version"] = "otra"
    with pytest.raises(RuntimeError):
        modulo._metadata_modelos(modelos)


def test_cli_modelo_instalado_inconsistente_no_mide_ni_serializa_error(tmp_path, monkeypatch):
    modulo = script(metadata_falsa=False)
    monkeypatch.setattr(modulo, "distribution", distribuciones_falsas(tmp_path / "paquetes", version="3.7.0"))
    codigo, salida = modulo.ejecutar(BANCO, tmp_path / "corridas", detector=lambda _: pytest.fail(),
                                    enmascarador=lambda _: pytest.fail(), informador=salud_falsa)
    assert codigo == 2 and not (salida / "resumen.json").exists()
    manifiesto = json.loads((salida / "manifiesto.json").read_text())
    assert manifiesto["estado"] == "fallido" and manifiesto["metadata_modelos"] is None
    assert manifiesto["error"] == {"etapa": "salud_detector", "tipo": "RuntimeError"}


def test_excepcion_a_mitad_conserva_casos_parciales_sin_aggregate_ni_mensaje_sensible(tmp_path):
    detector_base, enmascarador = fakes_de_referencia()
    llamadas = 0

    def detector(texto):
        nonlocal llamadas
        llamadas += 1
        if llamadas == 2:
            raise RuntimeError("ERROR_CON_DATOS_QUE_NO_SE_DEBEN_GUARDAR")
        return detector_base(texto)

    codigo, salida = script().ejecutar(BANCO, tmp_path, detector=detector, enmascarador=enmascarador,
                                      informador=salud_falsa)
    assert codigo == 2 and llamadas == 2 and not (salida / "resumen.json").exists()
    manifiesto = json.loads((salida / "manifiesto.json").read_text())
    assert manifiesto["textos_completos"] == 1 and manifiesto["metricas"] is None
    assert len((salida / "casos.jsonl").read_text().splitlines()) == 1
    assert "ERROR_CON_DATOS" not in (salida / "manifiesto.json").read_text()


def test_cli_meta_no_cumplida_tiene_metricas_medidas_y_exit_no_cero(tmp_path):
    codigo, salida = script().ejecutar(BANCO, tmp_path, detector=lambda _: [],
                                      enmascarador=lambda texto: (texto, {}), informador=salud_falsa)
    assert codigo == 1
    resumen = json.loads((salida / "resumen.json").read_text())
    assert resumen["estricto"]["recall"] == 0 and resumen["estricto"]["fn"] == 56
    assert resumen["estricto"]["precision"] is None and not resumen["cumple_meta"]
    assert json.loads((salida / "manifiesto.json").read_text())["estado"] == "completo"


def test_cli_banco_manipulado_no_llega_al_detector(tmp_path):
    banco = tmp_path / "alterado.jsonl"
    banco.write_bytes(BANCO.read_bytes() + b" ")
    codigo, salida = script().ejecutar(banco, tmp_path / "corridas", detector=lambda _: pytest.fail(),
                                      enmascarador=lambda _: pytest.fail(), informador=salud_falsa)
    assert codigo == 3 and not (salida / "resumen.json").exists()
    assert json.loads((salida / "manifiesto.json").read_text())["error"]["etapa"] == "banco"
