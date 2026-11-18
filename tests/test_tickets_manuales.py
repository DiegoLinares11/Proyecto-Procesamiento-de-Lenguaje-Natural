"""Fixtures técnicas artificiales en tmp_path: nunca se presentan como los veinte tickets humanos."""

import ast
import copy
import csv
import hashlib
import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from tickets_rag.tickets_manuales import (
    CAMPOS_CSV, CATEGORIAS, CARPETA, DECLARACIONES, EXCLUSIONES, IDS, PRIORIDADES, REFERENCIAS,
    ErrorTicketsManuales, cargar_manuales, leer_csv, normalizar_texto, preparar_manuales,
    validar_autoria, validar_filas,
)


@pytest.fixture
def entradas(tmp_path):
    raiz = tmp_path / "repo"
    for nombre, (relativa, campo) in REFERENCIAS.items():
        ruta = raiz / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps({campo: f"FUENTE TÉCNICA DE PRUEBA {nombre}"}) + "\n", encoding="utf-8")
    (raiz / "datos/manifiesto.json").write_text('{"documentos": []}', encoding="utf-8")
    filas = [{"ticket_id": i, "texto": f"FIXTURE TÉCNICA {n}: dato artificial de prueba unitaria, no ticket humano.",
              "categoria": CATEGORIAS[n % 6], "prioridad": PRIORIDADES[n % 3]} for n, i in enumerate(IDS)]
    csv_ruta = tmp_path / "entrada.csv"
    with csv_ruta.open("w", newline="", encoding="utf-8") as archivo:
        w = csv.DictWriter(archivo, fieldnames=CAMPOS_CSV)
        w.writeheader()
        w.writerows(filas)
    meta = {"estado": "declarado", "autor": "AUTOR FICTICIO DE PRUEBA UNITARIA", "fecha_redaccion": date.today().isoformat(),
            "declaraciones": {k: True for k in DECLARACIONES}}
    meta_ruta = tmp_path / "autoria.json"
    meta_ruta.write_text(json.dumps(meta), encoding="utf-8")
    return {"raiz": raiz, "filas": filas, "csv": csv_ruta, "meta": meta, "autoria": meta_ruta,
            "salida": tmp_path / "congelado"}


def test_plantilla_sigue_vacia_y_la_cli_no_crea_un_final(tmp_path, monkeypatch, capsys):
    filas = leer_csv((CARPETA / "plantilla.csv").read_bytes())
    assert len(filas) == 20 and tuple(f["ticket_id"] for f in filas) == IDS
    assert all(not f["texto"] and not f["categoria"] and not f["prioridad"] for f in filas)
    meta = json.loads((CARPETA / "autoria.pendiente.json").read_text())
    assert meta["estado"] == "pendiente" and not meta["autor"]
    spec = importlib.util.spec_from_file_location("preparar_manual_test", Path(__file__).parents[1] / "scripts/preparar_tickets_manuales.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    salida = tmp_path / "no_crear"
    monkeypatch.setattr("sys.argv", ["preparar_tickets_manuales.py", "--salida", str(salida)])
    assert modulo.main() == 2
    assert not salida.exists() and "Autoría" in capsys.readouterr().out


def test_congelacion_compatible_y_sin_modificar_fuentes(entradas):
    e = entradas
    antes = {p: p.read_bytes() for p in (e["csv"], e["autoria"], *e["raiz"].rglob("*.jsonl"))}
    assert preparar_manuales(e["csv"], e["autoria"], raiz=e["raiz"])["congelado"] is False
    assert not e["salida"].exists()
    resumen = preparar_manuales(e["csv"], e["autoria"], raiz=e["raiz"], salida=e["salida"])
    filas = cargar_manuales(e["salida"] / "tickets.jsonl", raiz=e["raiz"])
    assert resumen["tickets"] == len(filas) == 20
    assert all(f["particion"] == "manuales" and f["uso"] == "evaluacion_reservada"
               and f["procedencia"] == "humano_declarado" and "tipo" not in f for f in filas)
    assert all(p.read_bytes() == raw for p, raw in antes.items())
    m = json.loads((e["salida"] / "manifiesto.json").read_text())
    assert set(m["excluido_de"]) == set(EXCLUSIONES)
    assert "no prueba" in m["alcance_autoria"]
    for n, h in m["artefactos_sha256"].items():
        assert hashlib.sha256((e["salida"] / n).read_bytes()).hexdigest() == h


@pytest.mark.parametrize("defecto", ["cantidad", "vacio", "texto_duplicado", "id_duplicado", "categoria", "prioridad"])
def test_rechaza_filas_invalidas_sin_imprimir_valores(entradas, defecto):
    filas = copy.deepcopy(entradas["filas"])
    if defecto == "cantidad":
        filas.pop()
    elif defecto == "vacio":
        filas[0]["texto"] = " \t\n "
    elif defecto == "texto_duplicado":
        filas[0]["texto"] = "  " + filas[1]["texto"].lower().replace(" ", "  ")
    elif defecto == "id_duplicado":
        filas[0]["ticket_id"] = filas[1]["ticket_id"]
    else:
        filas[0][defecto] = "VALOR PRIVADO QUE NO DEBE APARECER EN EL ERROR"
    with pytest.raises(ErrorTicketsManuales) as error:
        validar_filas(filas, {})
    assert "VALOR PRIVADO" not in str(error.value) and "FIXTURE TÉCNICA" not in str(error.value)


@pytest.mark.parametrize("fuente", list(REFERENCIAS))
def test_rechaza_duplicado_exacto_normalizado_de_cada_conjunto(entradas, fuente):
    filas = copy.deepcopy(entradas["filas"])
    filas[0]["texto"] = "  TEXTO\n conocido con   ácento "
    with pytest.raises(ErrorTicketsManuales, match=fuente):
        validar_filas(filas, {fuente: {normalizar_texto("texto conocido con a\u0301cento")}})


@pytest.mark.parametrize("declaracion", DECLARACIONES)
def test_declaraciones_requieren_booleano_true(entradas, declaracion):
    for valor in (False, "true", 1):
        meta = copy.deepcopy(entradas["meta"])
        meta["declaraciones"][declaracion] = valor
        with pytest.raises(ErrorTicketsManuales):
            validar_autoria(meta)


@pytest.mark.parametrize("campo,valor", [("autor", ""), ("autor", "pendiente"), ("estado", "pendiente"),
                                        ("fecha_redaccion", "ayer"), ("fecha_redaccion", None)])
def test_autoria_incompleta_no_se_acredita(entradas, campo, valor):
    meta = {**entradas["meta"], campo: valor}
    with pytest.raises(ErrorTicketsManuales):
        validar_autoria(meta)
    meta = {**entradas["meta"], "fecha_redaccion": (date.today() + timedelta(days=1)).isoformat()}
    with pytest.raises(ErrorTicketsManuales):
        validar_autoria(meta)


def test_autoria_simple_no_fabrica_declaraciones_y_congela_como_datos_indicados(entradas):
    e = entradas
    meta = {k: v for k, v in e["meta"].items() if k != "declaraciones"}
    assert validar_autoria(meta) == meta and "declaraciones" not in meta
    e["autoria"].write_text(json.dumps(meta), encoding="utf-8")
    preparar_manuales(e["csv"], e["autoria"], raiz=e["raiz"], salida=e["salida"])
    manifiesto = json.loads((e["salida"] / "manifiesto.json").read_text())
    assert manifiesto["version"] == 2
    assert manifiesto["autoria"] == meta and "declaraciones" not in manifiesto["autoria"]
    assert manifiesto["procedencia_declarada"] == {
        "tipo": "persona_independiente_f3_indicada", "registro": "nombre_y_fecha", "verificacion": "no_verificada",
    }
    assert len(cargar_manuales(e["salida"] / "tickets.jsonl", raiz=e["raiz"])) == 20
    manifiesto["procedencia_declarada"]["verificacion"] = "verificada"
    (e["salida"] / "manifiesto.json").write_text(json.dumps(manifiesto), encoding="utf-8")
    with pytest.raises(ErrorTicketsManuales):
        cargar_manuales(e["salida"] / "tickets.jsonl", raiz=e["raiz"])


@pytest.mark.parametrize("legacy", [False, True])
def test_copia_exacta_normalizada_de_sintetico_guardado_no_se_congela_como_humano(entradas, legacy):
    e = entradas
    ruta = e["raiz"] / "evaluacion/tickets_sinteticos/tickets.jsonl"
    ruta.parent.mkdir(parents=True)
    ruta.write_text(json.dumps({"texto": e["filas"][0]["texto"].lower().replace(" ", "  "),
                                "procedencia": "sintetico_ia"}) + "\n", encoding="utf-8")
    if not legacy:
        e["autoria"].write_text(json.dumps({k: v for k, v in e["meta"].items() if k != "declaraciones"}))
    with pytest.raises(ErrorTicketsManuales, match="sinteticos_ia"):
        preparar_manuales(e["csv"], e["autoria"], raiz=e["raiz"], salida=e["salida"])
    assert not e["salida"].exists()


def test_referencia_sintetica_nueva_no_invalida_congelado_historico(entradas):
    e = entradas
    preparar_manuales(e["csv"], e["autoria"], raiz=e["raiz"], salida=e["salida"])
    antes = {p: p.read_bytes() for p in e["salida"].iterdir()}
    ruta = e["raiz"] / "evaluacion/tickets_sinteticos/tickets.jsonl"
    ruta.parent.mkdir(parents=True)
    ruta.write_text(json.dumps({"texto": "CASO SINTÉTICO ARTIFICIAL ADICIONAL"}) + "\n")
    assert len(cargar_manuales(e["salida"] / "tickets.jsonl", raiz=e["raiz"])) == 20
    assert all(p.read_bytes() == raw for p, raw in antes.items())


def test_nueva_congelacion_fija_hash_de_sinteticos_existentes(entradas):
    e = entradas
    ruta = e["raiz"] / "evaluacion/tickets_sinteticos/tickets.jsonl"
    ruta.parent.mkdir(parents=True)
    ruta.write_text(json.dumps({"texto": "CASO SINTÉTICO ARTIFICIAL DIFERENTE"}) + "\n")
    preparar_manuales(e["csv"], e["autoria"], raiz=e["raiz"], salida=e["salida"])
    manifiesto = json.loads((e["salida"] / "manifiesto.json").read_text())
    assert any(f["nombre"] == "sinteticos_ia" for f in manifiesto["fuentes_referencia"])
    assert len(cargar_manuales(e["salida"] / "tickets.jsonl", raiz=e["raiz"])) == 20
    ruta.write_text("NO ES JSONL")
    with pytest.raises(ErrorTicketsManuales):
        cargar_manuales(e["salida"] / "tickets.jsonl", raiz=e["raiz"])


def test_sin_banco_oficial_no_se_congela(entradas):
    e = entradas
    (e["raiz"] / REFERENCIAS["banco_oficial"][0]).unlink()
    with pytest.raises(ErrorTicketsManuales, match="banco_oficial"):
        preparar_manuales(e["csv"], e["autoria"], raiz=e["raiz"], salida=e["salida"])
    assert not e["salida"].exists()


@pytest.mark.parametrize("archivo", ["tickets.jsonl", "fuente.csv", "autoria.json"])
def test_hash_impide_cargar_artefacto_alterado(entradas, archivo):
    e = entradas
    preparar_manuales(e["csv"], e["autoria"], raiz=e["raiz"], salida=e["salida"])
    p = e["salida"] / archivo
    p.write_bytes(p.read_bytes() + b"\n")
    with pytest.raises(ErrorTicketsManuales, match="cambiaron"):
        cargar_manuales(e["salida"] / "tickets.jsonl", raiz=e["raiz"])


def test_cambio_de_corpus_o_sobrescritura_no_pasan_silenciosamente(entradas):
    e = entradas
    preparar_manuales(e["csv"], e["autoria"], raiz=e["raiz"], salida=e["salida"])
    original = (e["salida"] / "tickets.jsonl").read_bytes()
    with pytest.raises(ErrorTicketsManuales, match="ya existe"):
        preparar_manuales(e["csv"], e["autoria"], raiz=e["raiz"], salida=e["salida"])
    assert (e["salida"] / "tickets.jsonl").read_bytes() == original
    fuente = e["raiz"] / REFERENCIAS["f3"][0]
    fuente.write_text(json.dumps({"texto": "FUENTE MODIFICADA DE PRUEBA"}) + "\n")
    with pytest.raises(ErrorTicketsManuales):
        cargar_manuales(e["salida"] / "tickets.jsonl", raiz=e["raiz"])


def test_etiquetas_coinciden_con_el_contrato_del_clasificador():
    # Leer AST evita importar/cargar modelos para comprobar etiquetas estáticas.
    source = Path(__file__).parents[1] / "src/tickets_rag/clasificador_llm.py"
    tree = ast.parse(source.read_text())
    categorias = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "CATEGORIAS" for t in n.targets))
    assert ast.literal_eval(categorias) == CATEGORIAS
    clase = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Clasificacion")
    prioridad = next(n.annotation.slice for n in clase.body if isinstance(n, ast.AnnAssign) and n.target.id == "prioridad")
    assert ast.literal_eval(prioridad) == PRIORIDADES
