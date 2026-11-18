"""NER local real y límites de PII; ejemplos propios de desarrollo, separados del holdout."""

import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from tickets_rag import pii


@pytest.mark.parametrize("texto,nombres", [
    ("Mi nombre es Teresa Marín y no puedo entrar a mi cuenta.", ["Teresa Marín"]),
    ("La agente habló con Beatriz Salcedo sobre el acceso.", ["Beatriz Salcedo"]),
    ("Hablé con Óscar Benítez y Lucía Castellanos por el acceso.", ["Óscar Benítez", "Lucía Castellanos"]),
    ("El caso pertenece a Héctor Alarcón.", ["Héctor Alarcón"]),
])
def test_presidio_real_detecta_personas_en_espanol(texto, nombres):
    detecciones = pii.detectar(texto)
    assert [texto[d.inicio:d.fin] for d in detecciones if d.tipo == "PERSON"] == nombres
    salida, conteos = pii.enmascarar(texto)
    assert conteos == {"PERSON": len(nombres)}
    assert all(n not in salida for n in nombres)


@pytest.mark.parametrize("texto", [
    "Outlook no abre en Windows; Teams falla. Técnico N2 revisa VPN y ERP-401.",
    "Agente N1 consulta TCK-2026-09002, F1-2026-2-c022 y error 0x80070005.",
    "Microsoft Authenticator y Valcora ID requieren MFA; SharePoint, OneDrive y Office funcionan.",
    "La IP 169.254.10.2 y ffffa884`c0c40000 son datos de diagnóstico.",
])
def test_ner_no_destruye_productos_roles_ni_codigos_tecnicos(texto):
    assert pii.enmascarar(texto) == (texto, {})


@pytest.mark.parametrize("texto", [
    "Indique al usuario cómo abrir Outlook. Recomiende reiniciar Windows y ejecute el diagnóstico.",
    "Registre prioridad ALTA o MEDIA y revise el grupo GS-finanzas-M.",
    "En el menú Archivo, abra Opciones y seleccione Rendimiento.",
])
def test_instrucciones_y_prioridades_no_son_personas(texto):
    assert pii.enmascarar(texto) == (texto, {})


@pytest.mark.parametrize("texto", [
    "Warn the user before continuing. Manually select the corrupt file and save it.",
    "In the File menu, select Options. If you see a warning, restart Windows.",
    "Run Dism.exe and Sfc.exe after installing KB4493473; use WinDbg and PowerShell for diagnostics.",
    "Open Notepad or File Explorer. Intune and Print Spooler are available.",
    "The debugger prints FOLLOWUP_IP and VIDEO_ENGINE_TIMEOUT_DETECTED, then mov qword and eip=82154573.",
])
def test_instrucciones_y_sintaxis_tecnica_en_ingles_no_son_personas(texto):
    assert pii.enmascarar(texto, idioma="en") == (texto, {})


@pytest.mark.parametrize("texto,nombres", [
    ("The ticket was opened by Jennifer Lawrence and assigned to Robert Miller.", ["Jennifer Lawrence", "Robert Miller"]),
    ("Please ask Elizabeth Green to restart Outlook.", ["Elizabeth Green"]),
])
def test_modelo_ingles_detecta_personas_reales_del_ejemplo(texto, nombres):
    detecciones = pii.detectar(texto, idioma="en")
    assert [texto[d.inicio:d.fin] for d in detecciones if d.tipo == "PERSON"] == nombres
    salida, conteos = pii.enmascarar(texto, idioma="en")
    assert conteos == {"PERSON": len(nombres)} and all(n not in salida for n in nombres)


def test_nombres_dentro_de_rutas_y_logs_no_quedan_exentos_por_ser_codigo():
    texto = r"La carpeta C:\Users\Teresa Marín\Documents presenta errores; el log indica que Beatriz Salcedo inició sesión."
    salida, conteos = pii.enmascarar(texto)
    assert "Teresa Marín" not in salida and "Beatriz Salcedo" not in salida and conteos.get("PERSON", 0) >= 2


def test_enmascarado_es_idempotente_y_no_cuenta_placeholders():
    primero, conteos = pii.enmascarar("Mi nombre es Teresa Marín; correo cliente@example.com y teléfono 5555-1234.")
    assert conteos == {"PERSON": 1, "EMAIL": 1, "PHONE": 1}
    assert pii.enmascarar(primero) == (primero, {})


def test_overlap_ner_regex_conserva_nombre_y_prioriza_email(monkeypatch):
    texto = "Teresa Marín cliente@example.com"
    monkeypatch.setattr(pii, "_personas", lambda t, idioma: [pii.Deteccion("PERSON", 0, len(t), 0.85)])
    spans = pii.detectar(texto)
    assert [(d.tipo, texto[d.inicio:d.fin]) for d in spans] == [("PERSON", "Teresa Marín"), ("EMAIL", "cliente@example.com")]
    assert pii.enmascarar(texto) == ("[PERSON_REDACTED] [EMAIL_REDACTED]", {"PERSON": 1, "EMAIL": 1})


def test_un_ner_con_falso_positivo_no_enmascara_el_buzon_institucional(monkeypatch):
    texto = "Escriba a mesadeayuda@valcora.example"
    inicio = texto.index("mesadeayuda")
    monkeypatch.setattr(pii, "_personas", lambda t, idioma: [pii.Deteccion("PERSON", inicio, len(t), 0.85)])
    assert pii.enmascarar(texto) == (texto, {})


def test_placeholders_y_productos_se_protegen_aun_si_ner_los_clasifica_como_persona(monkeypatch):
    texto = "Outlook y [PERSON_REDACTED] están disponibles para Teresa Marín."
    inicio = texto.index("Teresa")
    monkeypatch.setattr(pii, "_personas", lambda t, idioma: [
        pii.Deteccion("PERSON", 0, len("Outlook"), 0.85),
        pii.Deteccion("PERSON", t.index("[PERSON_"), t.index("]") + 1, 0.85),
        pii.Deteccion("PERSON", inicio, inicio + len("Teresa Marín"), 0.85),
    ])
    assert pii.enmascarar(texto) == ("Outlook y [PERSON_REDACTED] están disponibles para [PERSON_REDACTED].", {"PERSON": 1})


def test_modelo_ausente_falla_cerrado_sin_descargar_ni_devolver_resultado_parcial(monkeypatch):
    import spacy

    monkeypatch.setattr(pii, "_ANALIZADORES", {})
    monkeypatch.setattr(spacy.util, "is_package", lambda nombre: False)

    def prohibida(*args, **kwargs):
        raise AssertionError("No se permiten descargas durante el análisis")

    monkeypatch.setattr(spacy.cli, "download", prohibida)
    with pytest.raises(pii.ErrorPII) as error:
        pii.enmascarar("Teresa Marín usa cliente@example.com")
    assert "Teresa" not in str(error.value) and "cliente@example.com" not in str(error.value)
    assert error.value.codigo == "pii_no_disponible"


def test_falla_del_analisis_no_revela_texto_en_error(monkeypatch):
    def fallar(*args, **kwargs):
        raise RuntimeError("falló Teresa Marín cliente@example.com")

    monkeypatch.setattr(pii, "_ANALIZADORES", {"es": SimpleNamespace(nlp_engine=SimpleNamespace(process_text=fallar))})
    with pytest.raises(pii.ErrorPII) as error:
        pii.enmascarar("Teresa Marín usa cliente@example.com")
    assert "Teresa" not in str(error.value) and "cliente@example.com" not in str(error.value)


def test_carga_y_analisis_reales_no_usan_red(monkeypatch):
    def prohibida(*args, **kwargs):
        raise AssertionError("El detector debe usar solo el modelo local")

    monkeypatch.setattr(socket.socket, "connect", prohibida)
    monkeypatch.setattr(socket, "create_connection", prohibida)
    monkeypatch.setattr(pii, "_ANALIZADORES", {})
    info = pii.informacion_detector()
    assert info["local"] and info["ner_disponible"] and info["modelo_personas"] == "es_core_news_md"
    assert pii.enmascarar("Mi nombre es Teresa Marín.")[1] == {"PERSON": 1}


def test_carga_concurrente_crea_un_solo_analizador(monkeypatch):
    construcciones = []
    analizador = object()

    def crear(idioma):
        construcciones.append(1)
        time.sleep(0.01)
        return analizador

    monkeypatch.setattr(pii, "_ANALIZADORES", {})
    monkeypatch.setattr(pii, "_crear_analizador", crear)
    with ThreadPoolExecutor(max_workers=5) as pool:
        cargados = list(pool.map(lambda _: pii._analizador_personas(), range(5)))
    assert construcciones == [1] and all(a is analizador for a in cargados)


def test_importar_para_f3_y_luhn_no_carga_ner():
    codigo = "import sys,json; from tickets_rag.pii import luhn_valido; print(json.dumps([luhn_valido('4111111111111111'), 'spacy' in sys.modules, 'presidio_analyzer' in sys.modules]))"
    env = {**os.environ, "CODEX_BIN": "/ruta/inexistente-no-inferir"}
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, env=env, check=True)
    assert json.loads(r.stdout) == [True, False, False]
