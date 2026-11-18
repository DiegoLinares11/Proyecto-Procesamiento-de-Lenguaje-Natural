"""Captura sin modelos: datos artificiales exclusivamente en tmp_path, nunca un holdout humano."""

import copy
import csv
import io
import json
import os
import shutil
import socket
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest

from tickets_rag import config
from tickets_rag.captura_manuales import CapturaManuales, ErrorCaptura
from tickets_rag.tickets_manuales import (
    CAMPOS_CSV, CATEGORIAS, DECLARACIONES, IDS, PRIORIDADES, cargar_manuales, leer_csv, preparar_manuales,
)


def editable(snapshot):
    return {k: copy.deepcopy(snapshot[k]) for k in ("revision", "tickets", "autoria")}


@pytest.fixture
def oficial(tmp_path):
    """Copia referencias reales del banco; sus validadores genuinos siguen activos."""
    raiz = tmp_path / "repo"
    manifest = json.loads((config.RAIZ / "evaluacion/banco.manifiesto.json").read_text())
    nombres = {"evaluacion/banco.jsonl", "evaluacion/banco.manifiesto.json", "indices/chunks.jsonl",
               manifest["revision_casos"]["archivo"], *manifest["referencias_sha256"]}
    for nombre in nombres:
        origen, destino = config.RAIZ / nombre, raiz / nombre
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origen, destino)
    return raiz


def completo(captura):
    payload = editable(captura.estado())
    for n, ticket in enumerate(payload["tickets"]):
        ticket.update(texto=f"  FIXTURE CAPTURA {n}: dato artificial de prueba unitaria, no ticket humano.\n ",
                      categoria=CATEGORIAS[n % len(CATEGORIAS)], prioridad=PRIORIDADES[n % len(PRIORIDADES)])
    payload["autoria"] = {
        "estado": "declarado", "autor": " AUTOR FICTICIO DE PRUEBA UNITARIA ",
        "fecha_redaccion": date.today().isoformat(), "declaraciones": {d: True for d in DECLARACIONES},
    }
    return payload


def temporales(captura):
    return list(captura.local.glob(".validacion-*")) + list(captura.local.glob(".borrador-*"))


def test_estado_inicial_vacio_no_fabrica_autoria_ni_textos(tmp_path):
    captura = CapturaManuales(raiz=tmp_path)
    estado = captura.estado()
    assert estado["revision"] == 0 and estado["estado"] == "borrador"
    assert tuple(t["ticket_id"] for t in estado["tickets"]) == IDS
    assert all(not t[c] for t in estado["tickets"] for c in ("texto", "categoria", "prioridad"))
    assert estado["version"] == 2
    assert estado["autoria"] == {"estado": "pendiente", "autor": "", "fecha_redaccion": None}
    assert estado["categorias"] == list(CATEGORIAS) and estado["prioridades"] == list(PRIORIDADES)
    assert not captura.borrador.exists() and not captura.congelado.exists()


def test_guarda_incompleto_y_recarga_sin_corregir_redaccion(tmp_path):
    captura = CapturaManuales(raiz=tmp_path)
    payload = editable(captura.estado())
    texto = "  mi redacción SIN corregir\ncon un errorr y comillas \"a\", coma, á.  "
    payload["tickets"][0]["texto"] = texto
    payload["autoria"]["autor"] = " AUTOR FICTICIO "
    payload["autoria"]["fecha_redaccion"] = ""
    guardado = captura.guardar(payload)
    assert guardado["revision"] == 1 and guardado["tickets"][0]["texto"] == texto
    assert CapturaManuales(raiz=tmp_path).estado() == guardado
    assert guardado["autoria"]["estado"] == "pendiente" and "declaraciones" not in guardado["autoria"]
    assert not temporales(captura)
    if os.name != "nt":
        assert stat.S_IMODE(captura.local.stat().st_mode) == 0o700
        assert stat.S_IMODE(captura.borrador.stat().st_mode) == 0o600


@pytest.mark.parametrize("defecto", [
    "extra", "referencias", "cantidad", "id", "duplicado", "categoria", "prioridad", "texto", "autor", "booleano",
    "revision_texto", "revision_booleano", "autoria_extra", "declaracion_extra",
])
def test_formato_y_limites_se_rechazan_antes_de_escribir(tmp_path, defecto):
    captura = CapturaManuales(raiz=tmp_path)
    # No llama estado(): una entrada mal formada ni siquiera debe inicializar el almacenamiento.
    payload = {"revision": 0, "tickets": [{"ticket_id": i, "texto": "", "categoria": "", "prioridad": ""} for i in IDS],
               "autoria": {"estado": "pendiente", "autor": "", "fecha_redaccion": None,
                           "declaraciones": {d: False for d in DECLARACIONES}}}
    if defecto in {"extra", "referencias"}:
        payload[defecto] = "VALOR PRIVADO"
    elif defecto == "cantidad":
        payload["tickets"].pop()
    elif defecto == "id":
        payload["tickets"][0]["ticket_id"] = "VALOR PRIVADO"
    elif defecto == "duplicado":
        payload["tickets"][0]["ticket_id"] = IDS[1]
    elif defecto in {"categoria", "prioridad"}:
        payload["tickets"][0][defecto] = "VALOR PRIVADO"
    elif defecto == "texto":
        payload["tickets"][0]["texto"] = "P" * 8001
    elif defecto == "autor":
        payload["autoria"]["autor"] = "P" * 121
    elif defecto == "booleano":
        payload["autoria"]["declaraciones"][DECLARACIONES[0]] = "true"
    elif defecto == "revision_texto":
        payload["revision"] = "0"
    elif defecto == "revision_booleano":
        payload["revision"] = True
    elif defecto == "autoria_extra":
        payload["autoria"]["VALOR PRIVADO"] = "VALOR PRIVADO"
    else:
        payload["autoria"]["declaraciones"]["VALOR PRIVADO"] = True
    with pytest.raises(ErrorCaptura) as error:
        captura.guardar(payload)
    assert error.value.codigo == error.value.status_code == 422
    assert "VALOR PRIVADO" not in str(error.value) and "PPPPPP" not in str(error.value)
    assert not captura.local.exists()


def test_revision_obsoleta_no_pisa_el_trabajo_reciente(tmp_path):
    captura = CapturaManuales(raiz=tmp_path)
    anterior = editable(captura.estado())
    actual = captura.guardar(anterior)
    raw = captura.borrador.read_bytes()
    for operacion in (lambda: captura.guardar(anterior), lambda: captura.validar(0), lambda: captura.congelar(0)):
        with pytest.raises(ErrorCaptura) as error:
            operacion()
        assert error.value.codigo == 409
    assert captura.estado() == actual and captura.borrador.read_bytes() == raw


def test_dos_instancias_concurrentes_no_pierden_actualizaciones(tmp_path):
    captura = CapturaManuales(raiz=tmp_path)
    original = editable(captura.estado())

    def guardar(n):
        payload = copy.deepcopy(original)
        payload["tickets"][0]["texto"] = f"FIXTURE CONCURRENTE {n}, NO TICKET HUMANO"
        try:
            return CapturaManuales(raiz=tmp_path).guardar(payload)["revision"]
        except ErrorCaptura as error:
            return error.codigo

    with ThreadPoolExecutor(max_workers=5) as pool:
        resultados = list(pool.map(guardar, range(5)))
    assert resultados.count(1) == 1 and resultados.count(409) == 4
    assert CapturaManuales(raiz=tmp_path).estado()["revision"] == 1


def test_fallo_de_reemplazo_atomico_conserva_borrador_y_limpia_temporal(tmp_path, monkeypatch):
    captura = CapturaManuales(raiz=tmp_path)
    anterior = captura.guardar(editable(captura.estado()))
    raw = captura.borrador.read_bytes()

    def fallar(*args):
        raise OSError("VALOR PRIVADO")

    monkeypatch.setattr("tickets_rag.captura_manuales.os.replace", fallar)
    with pytest.raises(ErrorCaptura) as error:
        captura.guardar(editable(anterior))
    assert error.value.codigo == 500 and "VALOR PRIVADO" not in str(error.value)
    assert captura.borrador.read_bytes() == raw and not temporales(captura)


def test_borrador_corrupto_no_se_reinicia_ni_sobrescribe(tmp_path):
    captura = CapturaManuales(raiz=tmp_path)
    captura.guardar(editable(captura.estado()))
    captura.borrador.write_text('{"dato":"VALOR PRIVADO"}', encoding="utf-8")
    raw = captura.borrador.read_bytes()
    with pytest.raises(ErrorCaptura) as error:
        captura.estado()
    assert error.value.codigo == 422 and "VALOR PRIVADO" not in str(error.value)
    assert captura.borrador.read_bytes() == raw


def test_borrador_con_enlace_roto_no_se_reinicia_ni_sobrescribe(tmp_path):
    captura = CapturaManuales(raiz=tmp_path)
    payload = editable(captura.estado())
    captura.borrador.symlink_to(captura.local / "no-existe")
    for operacion in (captura.estado, lambda: captura.guardar(payload)):
        with pytest.raises(ErrorCaptura) as error:
            operacion()
        assert error.value.codigo == 422
    assert captura.borrador.is_symlink()


def test_incompleto_no_se_congela_y_no_deja_csv_temporal(oficial):
    captura = CapturaManuales(raiz=oficial)
    datos = captura.guardar(editable(captura.estado()))
    raw = captura.borrador.read_bytes()
    for operacion in (captura.validar, captura.congelar):
        with pytest.raises(ErrorCaptura) as error:
            operacion(datos["revision"])
        assert error.value.codigo == 422 and any("Autoría" in d for d in error.value.detalles)
    assert not captura.congelado.exists() and not temporales(captura)
    assert captura.borrador.read_bytes() == raw


def test_no_declara_autoria_por_llenar_los_campos(oficial):
    captura = CapturaManuales(raiz=oficial)
    payload = completo(captura)
    payload["autoria"]["estado"] = "pendiente"
    datos = captura.guardar(payload)
    assert datos["autoria"]["estado"] == "pendiente"
    with pytest.raises(ErrorCaptura) as error:
        captura.validar(datos["revision"])
    assert error.value.codigo == 422 and not captura.congelado.exists()


def test_datos_simples_guardan_validan_y_congelan_sin_crear_casillas(oficial):
    captura = CapturaManuales(raiz=oficial)
    payload = completo(captura)
    payload["autoria"].pop("declaraciones")
    guardado = captura.guardar(payload)
    assert guardado["version"] == 2 and guardado["autoria"] == payload["autoria"]
    persistido = json.loads(captura.borrador.read_text())
    assert persistido["version"] == 2 and "declaraciones" not in persistido["autoria"]
    assert CapturaManuales(raiz=oficial).estado() == guardado
    assert captura.validar(guardado["revision"])["valido"] is True
    congelado = captura.congelar(guardado["revision"])
    assert congelado["version"] == 2 and congelado["autoria"] == payload["autoria"]
    assert CapturaManuales(raiz=oficial).estado() == congelado
    assert len(cargar_manuales(captura.congelado / "tickets.jsonl", raiz=oficial)) == 20


def test_borrador_legacy_se_lee_sin_migrar_ni_completar_declaraciones(oficial):
    captura = CapturaManuales(raiz=oficial)
    payload = completo(captura)
    payload["autoria"]["declaraciones"]["sin_ia_en_redaccion"] = False
    guardado = captura.guardar(payload)
    raw = captura.borrador.read_bytes()
    assert guardado["version"] == 1 and guardado["autoria"] == payload["autoria"]
    assert CapturaManuales(raiz=oficial).estado() == guardado
    assert captura.borrador.read_bytes() == raw
    with pytest.raises(ErrorCaptura) as error:
        captura.validar(guardado["revision"])
    assert error.value.codigo == 422 and not captura.congelado.exists()
    # Guardar expresamente el formato nuevo no convierte las declaraciones previas a true.
    nuevo = editable(guardado)
    nuevo["autoria"].pop("declaraciones")
    actualizado = captura.guardar(nuevo)
    assert actualizado["version"] == 2 and "declaraciones" not in actualizado["autoria"]
    assert actualizado["tickets"] == guardado["tickets"]


def test_ui_rechaza_copia_exacta_de_sinteticos_al_validar_y_congelar(oficial):
    captura = CapturaManuales(raiz=oficial)
    payload = completo(captura)
    payload["autoria"].pop("declaraciones")
    ruta = oficial / "evaluacion/tickets_sinteticos/tickets.jsonl"
    ruta.parent.mkdir(parents=True)
    ruta.write_text(json.dumps({"texto": payload["tickets"][0]["texto"].swapcase().replace(" ", "  "),
                                "procedencia": "sintetico_ia"}) + "\n", encoding="utf-8")
    guardado = captura.guardar(payload)
    raw = captura.borrador.read_bytes()
    for operacion in (captura.validar, captura.congelar):
        with pytest.raises(ErrorCaptura) as error:
            operacion(guardado["revision"])
        assert error.value.codigo == 422 and any("sinteticos_ia" in e for e in error.value.detalles)
    assert captura.borrador.read_bytes() == raw and not captura.congelado.exists()


def test_validar_y_congelar_usan_validadores_reales_sin_red_modelos_ni_reescrituras(oficial, monkeypatch):
    captura = CapturaManuales(raiz=oficial)
    payload = completo(captura)
    captura.carpeta.mkdir(parents=True, exist_ok=True)
    plantilla = captura.carpeta / "plantilla.csv"
    pendiente = captura.carpeta / "autoria.pendiente.json"
    plantilla.write_text("PLANTILLA ORIGINAL NO MODIFICAR", encoding="utf-8")
    pendiente.write_text("METADATOS ORIGINALES NO MODIFICAR", encoding="utf-8")
    originales = {p: p.read_bytes() for p in (plantilla, pendiente, oficial / "datos/f3_tickets/tickets.jsonl",
                                             oficial / "evaluacion/banco.jsonl")}

    def prohibida(*args, **kwargs):
        raise AssertionError("Capturar no debe ejecutar modelos ni usar la red")

    monkeypatch.setattr(socket.socket, "connect", prohibida)
    monkeypatch.setattr(subprocess, "Popen", prohibida)
    guardado = captura.guardar(payload)
    borrador_antes = captura.borrador.read_bytes()
    validacion = captura.validar(guardado["revision"])
    assert validacion["valido"] and validacion["resumen"]["tickets"] == 20 and not validacion["resumen"]["congelado"]
    assert not captura.congelado.exists() and not temporales(captura)
    congelado = captura.congelar(guardado["revision"])
    assert congelado["estado"] == "congelado" and congelado["revision"] == guardado["revision"] + 1
    assert congelado["tickets"] == payload["tickets"] and congelado["autoria"] == payload["autoria"]
    assert CapturaManuales(raiz=oficial).estado() == congelado
    assert leer_csv((captura.congelado / "fuente.csv").read_bytes()) == payload["tickets"]
    finales = cargar_manuales(captura.congelado / "tickets.jsonl", raiz=oficial)
    assert finales[0]["texto"] == payload["tickets"][0]["texto"].strip()  # única normalización ya existente en CLI
    assert captura.borrador.read_bytes() == borrador_antes and not temporales(captura)
    assert all(p.read_bytes() == raw for p, raw in originales.items())
    if os.name != "nt":
        assert stat.S_IMODE(captura.congelado.stat().st_mode) == 0o700
        assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in captura.congelado.iterdir())


@pytest.mark.parametrize("archivo", ["fuente.csv", "autoria.json", "tickets.jsonl", "captura.json"])
def test_congelado_alterado_no_se_presenta_como_valido_ni_se_sobrescribe(oficial, archivo):
    captura = CapturaManuales(raiz=oficial)
    guardado = captura.guardar(completo(captura))
    captura.congelar(guardado["revision"])
    ruta = captura.congelado / archivo
    ruta.write_bytes(ruta.read_bytes() + (b"NO ES VALIDO" if archivo == "captura.json" else b"\n"))
    raw = ruta.read_bytes()
    with pytest.raises(ErrorCaptura) as error:
        captura.estado()
    assert error.value.codigo == 422
    with pytest.raises(ErrorCaptura) as error:
        captura.guardar(editable(guardado))
    assert error.value.codigo == 409 and ruta.read_bytes() == raw
    with pytest.raises(ErrorCaptura) as error:
        captura.congelar(guardado["revision"])
    assert error.value.codigo == 409 and ruta.read_bytes() == raw


def test_no_pisa_ni_una_carpeta_congelada_vacia(oficial):
    captura = CapturaManuales(raiz=oficial)
    captura.congelado.mkdir(parents=True)
    with pytest.raises(ErrorCaptura) as error:
        captura.estado()
    assert error.value.codigo == 422
    with pytest.raises(ErrorCaptura) as error:
        captura.congelar(0)
    assert error.value.codigo == 409 and list(captura.congelado.iterdir()) == []


def test_control_congelado_con_enlace_roto_no_se_ignora(oficial):
    captura = CapturaManuales(raiz=oficial)
    datos = captura.guardar(completo(captura))
    captura.congelar(datos["revision"])
    control = captura.congelado / "captura.json"
    control.unlink()
    control.symlink_to(captura.congelado / "no-existe")
    with pytest.raises(ErrorCaptura) as error:
        captura.estado()
    assert error.value.codigo == 422 and control.is_symlink()


def test_carga_un_conjunto_cli_valido_sin_exigir_draft_de_ui(oficial, tmp_path):
    captura = CapturaManuales(raiz=oficial)
    payload = completo(captura)
    entrada = io.StringIO(newline="")
    writer = csv.DictWriter(entrada, fieldnames=CAMPOS_CSV)
    writer.writeheader()
    writer.writerows(payload["tickets"])
    csv_ruta, autoria_ruta = tmp_path / "cli.csv", tmp_path / "cli.json"
    csv_ruta.write_text(entrada.getvalue(), encoding="utf-8", newline="")
    autoria_ruta.write_text(json.dumps(payload["autoria"]), encoding="utf-8")
    preparar_manuales(csv_ruta, autoria_ruta, raiz=oficial, salida=captura.congelado)
    estado = captura.estado()
    assert estado["estado"] == "congelado" and estado["revision"] == 0
    assert estado["tickets"] == payload["tickets"] and not captura.borrador.exists()


def test_banco_o_referencias_forjados_impiden_congelar(oficial):
    captura = CapturaManuales(raiz=oficial)
    datos = captura.guardar(completo(captura))
    ruta = oficial / "evaluacion/banco.manifiesto.json"
    meta = json.loads(ruta.read_text())
    meta["referencias_sha256"] = {}
    ruta.write_text(json.dumps(meta), encoding="utf-8")
    for operacion in (captura.validar, captura.congelar):
        with pytest.raises(ErrorCaptura) as error:
            operacion(datos["revision"])
        assert error.value.codigo == 422 and "banco oficial" in str(error.value)
    assert not captura.congelado.exists() and not temporales(captura)


def test_errores_finales_solo_muestran_fila_y_causa_no_datos_humanos(oficial):
    captura = CapturaManuales(raiz=oficial)
    payload = completo(captura)
    payload["autoria"]["fecha_redaccion"] = (date.today() + timedelta(days=1)).isoformat()
    payload["tickets"][0]["texto"] = "VALOR PRIVADO DEL TEXTO"
    payload["autoria"]["autor"] = "VALOR PRIVADO DEL AUTOR"
    datos = captura.guardar(payload)
    with pytest.raises(ErrorCaptura) as error:
        captura.validar(datos["revision"])
    assert error.value.codigo == 422
    assert "VALOR PRIVADO" not in str(error.value) and "VALOR PRIVADO" not in repr(error.value.detalles)
    assert any("fecha_redaccion" in d for d in error.value.detalles)
    assert not temporales(captura)
