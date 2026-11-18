"""Gestor web con Popen falsos y fixtures técnicas; nunca ejecuta el clasificador real."""

import ast
import csv
import hashlib
import json
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path

import pytest

from tickets_rag.evaluacion_manual_web import (
    PROVEEDOR, VARIANTE, ErrorEvaluacionManualWeb, EvaluacionManualWeb, identidad_canonica,
)
from tickets_rag.tickets_manuales import (
    CAMPOS_CSV, CATEGORIAS, DECLARACIONES, IDS, PRIORIDADES, REFERENCIAS, cargar_manuales, preparar_manuales,
)


class ProcesoFalso:
    def __init__(self):
        self.fin = threading.Event()
        self.esperando = threading.Event()
        self.codigo = 0

    def wait(self):
        self.esperando.set()
        if not self.fin.wait(5):
            raise RuntimeError("Fixture no finalizada")
        return self.codigo


class FabricaFalsa:
    def __init__(self):
        self.llamadas = []
        self.procesos = []

    def __call__(self, comando, **kwargs):
        self.llamadas.append((comando, kwargs))
        p = ProcesoFalso()
        self.procesos.append(p)
        return p


@pytest.fixture
def entorno(tmp_path):
    raiz = tmp_path / "repo"
    for nombre, (relativa, campo) in REFERENCIAS.items():
        ruta = raiz / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps({campo: f"REFERENCIA ARTIFICIAL {nombre}"}) + "\n")
    (raiz / "datos/manifiesto.json").write_text('{"documentos": []}')
    script = raiz / "scripts/evaluar_clasificador_llm.py"
    script.parent.mkdir()
    script.write_text("# Script ficticio de fixture: nunca se ejecuta\n")
    filas = [{"ticket_id": id, "texto": f"FIXTURE PRIVADA ARTIFICIAL {n}, no es un ticket humano real.",
              "categoria": CATEGORIAS[n % len(CATEGORIAS)], "prioridad": PRIORIDADES[n % len(PRIORIDADES)]}
             for n, id in enumerate(IDS)]
    entrada = tmp_path / "fuente.csv"
    with entrada.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_CSV)
        w.writeheader()
        w.writerows(filas)
    autoria = tmp_path / "autor.json"
    autoria.write_text(json.dumps({"estado": "declarado", "autor": "AUTOR ARTIFICIAL DE FIXTURE PRIVADA",
                                  "fecha_redaccion": date.today().isoformat(),
                                  "declaraciones": {d: True for d in DECLARACIONES}}))
    congelado = raiz / "evaluacion/tickets_manuales/congelado"
    preparar_manuales(entrada, autoria, raiz=raiz, salida=congelado)
    fabrica = FabricaFalsa()
    gestores = []

    def gestor(**kwargs):
        g = EvaluacionManualWeb(raiz=raiz, proceso_factory=kwargs.pop("proceso_factory", fabrica), **kwargs)
        gestores.append(g)
        return g

    e = {"raiz": raiz, "tickets": congelado / "tickets.jsonl", "fabrica": fabrica, "gestor": gestor}
    yield e
    for p in fabrica.procesos:
        p.fin.set()
    for g in gestores:
        if g._hilo is not None:
            g._hilo.join(2)
            assert not g._hilo.is_alive()


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def carpetas(g, e):
    casos = cargar_manuales(e["tickets"], raiz=e["raiz"])
    id = identidad_canonica(casos)
    return g.salida_base / "manuales" / id, g.salida_base / ".web" / id


def escribir_finales(g, e, *, con_journal=True):
    """Artefactos ficticios para verificar publicación; ningún modelo interviene."""
    casos = cargar_manuales(e["tickets"], raiz=e["raiz"])
    salida, privado = carpetas(g, e)
    salida.mkdir(parents=True, exist_ok=True)
    hashes = {"identidad_canonica": identidad_canonica(casos), "tickets_manuales_sha256": _sha(e["tickets"]),
              "manifiesto_sha256": _sha(e["tickets"].parent / "manifiesto.json"),
              "evaluador_sha256": _sha(e["raiz"] / "scripts/evaluar_clasificador_llm.py")}
    intento = {"estado": "completo", "variante": VARIANTE, "modelo": "gpt-6.2-sol", **hashes}
    (salida / "intento.json").write_text(json.dumps(intento))
    resumen = {"variante": VARIANTE, "proveedor": PROVEEDOR, "modelo": "gpt-6.2-sol", "conjunto": "manuales",
               "tickets": 20, "macro_f1_llm": {"categoria": 1.0, "prioridad": 1.0},
               "macro_f1_tfidf": {"categoria": 1.0, "prioridad": 1.0}, "tokens_entrada": 1234,
               "tokens_salida": 100, "costo_usd": 0, "tickets_con_error": 0, "revision_humana": 0,
               "NO_EXPOSICION": "VALOR PRIVADO DEL RESULTADO NO PUBLICABLE", **hashes}
    (salida / "clasificador_manuales.json").write_text(json.dumps({VARIANTE: resumen}))
    csv_filas = [{"ticket_id": c["ticket_id"],
                  **{f"{campo}_{sistema}": c[campo] for campo in ("categoria", "prioridad")
                     for sistema in ("real", "llm", "tfidf")}} for c in casos]
    with (salida / f"clasificador_manuales_{VARIANTE}.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_filas[0])
        w.writeheader()
        w.writerows(csv_filas)
    if con_journal:
        (salida / "mediciones_parciales.jsonl").write_text("".join(json.dumps({
            "ticket_id": c["ticket_id"], "resultado": {"dato": "VALOR PRIVADO DEL JOURNAL"}}) + "\n" for c in casos))
    return salida, privado


def terminar(g, e, codigo=0):
    p = e["fabrica"].procesos[-1]
    p.codigo = codigo
    p.fin.set()
    g._hilo.join(2)
    assert not g._hilo.is_alive()


def test_identidad_equivale_al_helper_cli_y_es_independiente_del_orden(entorno):
    e = entorno
    # Extraer sólo el helper evita importar sklearn o cualquier clase de modelo.
    ruta = Path(__file__).parents[1] / "scripts/evaluar_clasificador_llm.py"
    arbol = ast.parse(ruta.read_text())
    nodo = next(n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == "identidad_manuales")
    modulo = ast.fix_missing_locations(ast.Module(body=[nodo], type_ignores=[]))
    espacio = {"hashlib": hashlib, "json": json}
    exec(compile(modulo, str(ruta), "exec"), espacio)
    casos = cargar_manuales(e["tickets"], raiz=e["raiz"])
    assert identidad_canonica(casos) == espacio["identidad_manuales"](casos[::-1])
    assert identidad_canonica(casos[::-1]) == identidad_canonica(casos)
    casos[0]["categoria"] = "OTRO"
    assert identidad_canonica(casos) != espacio["identidad_manuales"](cargar_manuales(e["tickets"], raiz=e["raiz"]))


def test_sin_congelacion_estado_no_crea_procesos_archivos_ni_hilos(tmp_path):
    fabrica = FabricaFalsa()
    g = EvaluacionManualWeb(raiz=tmp_path, proceso_factory=fabrica)
    antes = list(tmp_path.iterdir())
    for _ in range(3):
        estado = g.estado()
        assert estado["estado"] == "no_disponible" and estado["progreso"] == {"completados": 0, "total": 20}
        assert estado["resumen"] is None and not estado["puede_iniciar"]
    assert list(tmp_path.iterdir()) == antes and fabrica.llamadas == [] and g._hilo is None
    with pytest.raises(ErrorEvaluacionManualWeb) as error:
        g.iniciar()
    assert error.value.status_code == 409 and error.value.codigo == "conjunto_no_disponible"


def test_get_del_congelado_es_pasivo_y_no_filtra_texto_autoria_o_rutas(entorno):
    e = entorno
    g = e["gestor"]()
    antes = {p: p.read_bytes() for p in e["raiz"].rglob("*") if p.is_file()}
    for _ in range(3):
        r = g.estado()
        assert r["estado"] == "sin_iniciar" and r["puede_iniciar"]
        contenido = json.dumps(r)
        assert all(v not in contenido for v in ("FIXTURE PRIVADA", "AUTOR ARTIFICIAL", str(e["raiz"])))
    assert e["fabrica"].llamadas == [] and g._hilo is None
    assert {p: p.read_bytes() for p in e["raiz"].rglob("*") if p.is_file()} == antes


def test_post_inicia_cli_sin_shell_claves_ni_stdout_y_espera_en_background(entorno, monkeypatch, tmp_path):
    e = entorno
    for clave in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_API_KEY", "HTTP_PROXY"):
        monkeypatch.setenv(clave, "SECRETO_NO_HEREDAR")
    monkeypatch.setenv("PYTHONPATH", "/ruta/ajena/no/heredar")
    monkeypatch.setenv("CODEX_BIN", "/ruta/local/codex")
    base = tmp_path / "resultados alternativos con espacios"
    g = e["gestor"](salida_base=base)
    assert g.iniciar()["estado"] == "ejecutando"
    p = e["fabrica"].procesos[0]
    assert p.esperando.wait(1) and not p.fin.is_set()
    comando, kwargs = e["fabrica"].llamadas[0]
    assert comando == [sys.executable, str(e["raiz"] / "scripts/evaluar_clasificador_llm.py"),
                       "--conjunto", "manuales", "--variante", VARIANTE, "--tickets-manuales", str(e["tickets"]),
                       "--salida-base", str(base)]
    assert kwargs["cwd"] == str(e["raiz"]) and kwargs["shell"] is False and kwargs["close_fds"] is True
    assert kwargs["stdin"] == kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
    assert kwargs["env"]["CODEX_BIN"] == "/ruta/local/codex"
    assert kwargs["env"]["PYTHONPATH"] == str(e["raiz"] / "src")
    assert "SECRETO_NO_HEREDAR" not in json.dumps(kwargs["env"])
    assert kwargs["env"]["PYTHONNOUSERSITE"] == "1"
    assert len(e["fabrica"].llamadas) == 1


def test_doble_click_y_reinicio_conservan_el_primer_intento(entorno):
    e = entorno
    g = e["gestor"]()
    g.iniciar()
    reiniciado = e["gestor"]()
    for gestor in (g, reiniciado):
        with pytest.raises(ErrorEvaluacionManualWeb) as error:
            gestor.iniciar()
        assert error.value.status_code == 409 and error.value.codigo == "intento_existente"
    assert reiniciado.estado()["estado"] == "incompleto"  # no presume vida ni exit0 de otro proceso
    assert len(e["fabrica"].llamadas) == 1
    escribir_finales(g, e)
    terminar(g, e)
    assert reiniciado.estado()["estado"] == "completo"
    with pytest.raises(ErrorEvaluacionManualWeb):
        reiniciado.iniciar()


def test_dos_gestores_concurrentes_solo_crean_un_proceso(entorno):
    e = entorno
    gestores = [e["gestor"](), e["gestor"]()]
    barrera = threading.Barrier(2)
    resultados = []

    def iniciar(g):
        barrera.wait(timeout=2)
        try:
            resultados.append(g.iniciar()["estado"])
        except ErrorEvaluacionManualWeb as error:
            resultados.append(error.status_code)

    hilos = [threading.Thread(target=iniciar, args=(g,)) for g in gestores]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(2)
        assert not h.is_alive()
    assert resultados.count("ejecutando") == resultados.count(409) == 1
    assert len(e["fabrica"].llamadas) == 1


def test_intento_preexistente_del_cli_no_se_repite_ni_se_certifica_exit0(entorno):
    e = entorno
    g = e["gestor"]()
    escribir_finales(g, e)
    assert g.estado()["estado"] == "incompleto" and g.estado()["resumen"] is None
    with pytest.raises(ErrorEvaluacionManualWeb) as error:
        g.iniciar()
    assert error.value.status_code == 409 and not e["fabrica"].llamadas


def test_progreso_cuenta_solo_ids_unicos_validos_y_no_expone_resultados(entorno):
    e = entorno
    g = e["gestor"]()
    g.iniciar()
    salida, _ = carpetas(g, e)
    salida.mkdir(parents=True)
    lineas = [{"ticket_id": "MAN-01", "resultado": {"secreto": "NO_PUBLICAR"}}, {"ticket_id": "MAN-02"},
              {"ticket_id": "MAN-01"}, {"ticket_id": "OTRO-03"}]
    (salida / "mediciones_parciales.jsonl").write_text("".join(json.dumps(l) + "\n" for l in lineas) + '{"ticket_id":"MAN-03"')
    r = g.estado()
    assert r["estado"] == "ejecutando" and r["progreso"] == {"completados": 2, "total": 20}
    assert r["resumen"] is None and "NO_PUBLICAR" not in json.dumps(r)
    assert len(e["fabrica"].llamadas) == 1


def test_completo_solo_publica_macro_f1_actual_y_datos_permitidos(entorno):
    e = entorno
    g = e["gestor"]()
    g.iniciar()
    escribir_finales(g, e)
    terminar(g, e)
    r = g.estado()
    assert r["estado"] == "completo" and r["codigo_salida"] == 0 and not r["puede_iniciar"]
    assert r["progreso"] == {"completados": 20, "total": 20}
    assert r["resumen"]["macro_f1_llm"] == {"categoria": 1.0, "prioridad": 1.0}
    assert r["resumen"]["macro_f1_tfidf"] == {"categoria": 1.0, "prioridad": 1.0}
    assert r["resumen"]["tokens_entrada"] == 1234 and r["resumen"]["costo_usd"] == 0.0
    assert all(v not in json.dumps(r) for v in ("PRIVAD", "AUTOR", str(e["raiz"]), "NO_EXPOSICION"))


@pytest.mark.parametrize("codigo", [1, 2, -9, 139])
def test_exit_fallido_no_se_vuelve_completo_aunque_existan_metricas(codigo, entorno):
    e = entorno
    g = e["gestor"]()
    g.iniciar()
    escribir_finales(g, e)
    terminar(g, e, codigo)
    r = e["gestor"]().estado()
    assert r["estado"] == "incompleto" and r["codigo_salida"] == codigo and r["resumen"] is None
    with pytest.raises(ErrorEvaluacionManualWeb):
        g.iniciar()


@pytest.mark.parametrize("defecto", ["falta_json", "falta_csv", "falta_journal", "intento_incompleto", "hash",
                                   "variante", "proveedor", "modelo", "f1", "csv_gold", "journal_duplicado"])
def test_no_publica_finales_ausentes_incoherentes_o_de_otro_conjunto(entorno, defecto):
    e = entorno
    g = e["gestor"]()
    g.iniciar()
    salida, _ = escribir_finales(g, e)
    ruta_json = salida / "clasificador_manuales.json"
    resumen = json.loads(ruta_json.read_text())
    if defecto.startswith("falta_"):
        nombre = {"falta_json": "clasificador_manuales.json", "falta_csv": f"clasificador_manuales_{VARIANTE}.csv",
                  "falta_journal": "mediciones_parciales.jsonl"}[defecto]
        (salida / nombre).unlink()
    elif defecto == "intento_incompleto":
        ruta = salida / "intento.json"
        intento = json.loads(ruta.read_text())
        intento["estado"] = "incompleto; conservar parciales, no repetir desde cero"
        ruta.write_text(json.dumps(intento))
    elif defecto == "csv_gold":
        ruta = salida / f"clasificador_manuales_{VARIANTE}.csv"
        ruta.write_text(ruta.read_text().replace("MAN-01,ACCESO", "MAN-01,RED", 1))
    elif defecto == "journal_duplicado":
        ruta = salida / "mediciones_parciales.jsonl"
        with ruta.open("a") as f:
            f.write(json.dumps({"ticket_id": "MAN-01"}) + "\n")
    else:
        clave = {"hash": "tickets_manuales_sha256", "variante": "variante", "proveedor": "proveedor", "modelo": "modelo"}.get(defecto)
        if defecto == "f1":
            resumen[VARIANTE]["macro_f1_llm"]["categoria"] = 0.7
        else:
            resumen[VARIANTE][clave] = "VALOR PRIVADO INCOHERENTE"
        ruta_json.write_text(json.dumps(resumen))
    terminar(g, e)
    assert g.estado()["estado"] == "incompleto" and g.estado()["resumen"] is None
    with pytest.raises(ErrorEvaluacionManualWeb):
        g.iniciar()
    assert len(e["fabrica"].llamadas) == 1


def test_cambio_de_hash_del_congelado_no_muestra_resultados_antiguos(entorno):
    e = entorno
    g = e["gestor"]()
    g.iniciar()
    escribir_finales(g, e)
    terminar(g, e)
    e["tickets"].write_bytes(e["tickets"].read_bytes() + b"\n")
    r = g.estado()
    assert r["estado"] == "no_disponible" and r["resumen"] is None
    with pytest.raises(ErrorEvaluacionManualWeb) as error:
        g.iniciar()
    assert error.value.codigo == "conjunto_no_disponible" and len(e["fabrica"].llamadas) == 1


def test_cambio_del_evaluador_no_atribuye_metricas_a_codigo_nuevo(entorno):
    e = entorno
    g = e["gestor"]()
    g.iniciar()
    escribir_finales(g, e)
    terminar(g, e)
    (e["raiz"] / "scripts/evaluar_clasificador_llm.py").write_text("# Otra revisión del evaluador\n")
    assert g.estado()["estado"] == "incompleto" and g.estado()["resumen"] is None
    with pytest.raises(ErrorEvaluacionManualWeb):
        g.iniciar()


def test_reordenar_un_congelado_valido_no_habilita_otro_intento(entorno):
    e = entorno
    g = e["gestor"]()
    identidad_anterior = g.estado()["identidad_canonica"]
    g.iniciar()
    escribir_finales(g, e)
    terminar(g, e)
    casos = cargar_manuales(e["tickets"], raiz=e["raiz"])[::-1]
    e["tickets"].write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in casos), encoding="utf-8")
    fuente = e["tickets"].parent / "fuente.csv"
    with fuente.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=CAMPOS_CSV)
        escritor.writeheader()
        escritor.writerows({k: c[k] for k in CAMPOS_CSV} for c in casos)
    manifiesto = e["tickets"].parent / "manifiesto.json"
    meta = json.loads(manifiesto.read_text())
    for nombre in ("tickets.jsonl", "fuente.csv"):
        meta["artefactos_sha256"][nombre] = _sha(e["tickets"].parent / nombre)
    manifiesto.write_text(json.dumps(meta), encoding="utf-8")
    # Fixture de manipulación consistente: pasa el loader, pero conserva la identidad de evaluación.
    assert len(cargar_manuales(e["tickets"], raiz=e["raiz"])) == 20
    reiniciado = e["gestor"]()
    assert reiniciado.estado()["identidad_canonica"] == identidad_anterior
    assert reiniciado.estado()["estado"] == "incompleto" and not reiniciado.estado()["puede_iniciar"]
    with pytest.raises(ErrorEvaluacionManualWeb) as error:
        reiniciado.iniciar()
    assert error.value.status_code == 409 and len(e["fabrica"].llamadas) == 1


def test_fallo_de_popen_antes_de_crear_proceso_permite_otro_post_explicito(entorno):
    e = entorno
    llamadas = 0

    def fabrica(*args, **kwargs):
        nonlocal llamadas
        llamadas += 1
        if llamadas == 1:
            raise OSError("NO_PUBLICAR_CREDENCIAL_NI_RUTA")
        return e["fabrica"](*args, **kwargs)

    g = e["gestor"](proceso_factory=fabrica)
    with pytest.raises(ErrorEvaluacionManualWeb) as error:
        g.iniciar()
    assert error.value.status_code == 503 and "NO_PUBLICAR" not in str(error.value)
    for _ in range(3):
        assert g.estado()["estado"] == "incompleto" and g.estado()["puede_iniciar"]
    assert llamadas == 1  # GET jamás reintenta
    _, privado = carpetas(g, e)
    assert not (privado / "reserva.lock").exists()
    assert len(list(privado.glob("fallo_arranque_*.json"))) == 1
    assert "NO_PUBLICAR" not in "".join(p.read_text() for p in privado.iterdir())
    assert g.iniciar()["estado"] == "ejecutando" and llamadas == 2


def test_error_no_oserror_no_prueba_ausencia_de_proceso_y_no_permite_reintentar(entorno):
    e = entorno

    def fabrica(*args, **kwargs):
        raise RuntimeError("NO_PUBLICAR_FALLO_DESPUES_DE_INICIO_DESCONOCIDO")

    g = e["gestor"](proceso_factory=fabrica)
    with pytest.raises(ErrorEvaluacionManualWeb) as error:
        g.iniciar()
    assert error.value.status_code == 503 and "NO_PUBLICAR" not in str(error.value)
    assert g.estado()["estado"] == "incompleto" and not g.estado()["puede_iniciar"]
    with pytest.raises(ErrorEvaluacionManualWeb) as error:
        e["gestor"]().iniciar()
    assert error.value.status_code == 409


def test_registro_privado_corrupto_no_habilita_otro_primer_intento(entorno):
    e = entorno
    g = e["gestor"]()
    _, privado = carpetas(g, e)
    privado.mkdir(parents=True)
    (privado / "trabajo.json").write_text("registro dañado")
    assert g.estado()["estado"] == "incompleto" and not g.estado()["puede_iniciar"]
    with pytest.raises(ErrorEvaluacionManualWeb):
        g.iniciar()
    assert e["fabrica"].llamadas == []
