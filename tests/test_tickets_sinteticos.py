"""Evaluación técnica con fakes offline; ninguna fixture acredita tickets humanos."""

import copy
import builtins
import importlib.util
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickets_rag import config


@pytest.fixture
def evaluador(monkeypatch):
    spec = importlib.util.spec_from_file_location("evaluar_sinteticos_test", config.RAIZ / "scripts/evaluar_sinteticos.py")
    modulo = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, modulo)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def copia(tmp_path, evaluador):
    raiz = tmp_path / "repo"
    ruta = evaluador.CONJUNTO
    meta = json.loads((ruta.parent / "manifiesto.json").read_bytes())
    nombres = [f["ruta"] for f in meta["fuentes_referencia"]]
    nombres += ["indices/chunks.jsonl", "evaluacion/tickets_sinteticos/tickets.jsonl", "evaluacion/tickets_sinteticos/manifiesto.json"]
    for n in nombres:
        destino = raiz / n
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(config.RAIZ / n, destino)
    return raiz, raiz / "evaluacion/tickets_sinteticos/tickets.jsonl", tmp_path / "resultados"


def actualizar_meta(evaluador, raiz, ruta, casos=None):
    if casos is not None:
        ruta.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in casos))
    meta_ruta = ruta.parent / "manifiesto.json"
    meta = json.loads(meta_ruta.read_bytes())
    meta["artefactos_sha256"]["tickets.jsonl"] = evaluador.sha(ruta.read_bytes())
    meta["fuentes_referencia"] = evaluador.cargar_referencias(raiz)[1]
    if casos:
        meta["balance"] = {k: dict(evaluador.Counter(c[k] for c in casos)) for k in ("categoria", "prioridad", "tipo")}
    meta_ruta.write_text(json.dumps(meta, ensure_ascii=False))


def fake_clasificadores(evaluador, monkeypatch, casos, *, fallar_en=None):
    por_texto = {c["texto"]: c for c in casos}
    llamadas, entrenamiento = [], []
    estado = {"fallar_en": fallar_en}

    def tfidf(casos_recibidos, train):
        entrenamiento.extend(copy.deepcopy(train))
        assert [c["ticket_id"] for c in casos_recibidos] == [c["ticket_id"] for c in casos]
        return {c["ticket_id"]: {k: c[k] for k in ("categoria", "prioridad")} for c in casos}

    class Falso:
        sistemas = [f"PROMPT OFFLINE {i}" for i in range(5)]

        def clasificar(self, texto):
            c = por_texto[texto]
            llamadas.append(c["ticket_id"])
            if c["ticket_id"] == estado["fallar_en"]:
                error = RuntimeError("DATO SECRETO NO DEBE SALIR")
                error.codigo = "cuota"
                raise error
            valores = {k: c[k] for k in ("categoria", "prioridad", "tipo")}
            datos = {**valores, "confianza": {k: 1.0 for k in valores},
                     "votos": {k: {v: 5} for k, v in valores.items()}, "corridas_validas": 5,
                     "needs_human_review": False, "tokens_entrada": 10, "tokens_salida": 2,
                     "costo_usd": 0.0, "costo_api_usd": 0.0, "proveedor": "codex_subscription",
                     "modo_autenticacion": "chatgpt"}
            return SimpleNamespace(model_dump=lambda: datos)

    monkeypatch.setattr(evaluador, "predicciones_tfidf", tfidf)
    monkeypatch.setattr(evaluador, "crear_clasificador", lambda modelo: Falso())
    return llamadas, entrenamiento, estado


def test_conjunto_real_explicita_ia_justifica_balance_y_no_es_humano(evaluador):
    casos, meta = evaluador.cargar_conjunto()
    assert len(casos) == 20 and tuple(c["ticket_id"] for c in casos) == evaluador.IDS
    assert meta["autoria"]["tipo"] == "IA" and meta["autoria"]["persona_autora"] is None
    assert meta["cumple_requisito_20_humanos"] is False
    assert meta["balance"]["prioridad"] == {"ALTA": 6, "MEDIA": 6, "BAJA": 8}
    assert set(meta["balance"]["categoria"]) == set(evaluador.CATEGORIAS)
    assert all(set(c["justificacion"]) == {"categoria", "prioridad", "tipo"} for c in casos)
    assert all(c["procedencia"] == "sintetico_ia" and c["uso"] == "evaluacion_tecnica_reservada" for c in casos)


@pytest.mark.parametrize("defecto", ["hash", "autoria", "humanos", "referencias", "categoria", "duplicado", "id", "justificacion", "extra"])
def test_rechaza_cambios_y_metadatos_enganosos(evaluador, copia, defecto):
    raiz, ruta, _ = copia
    meta_ruta = ruta.parent / "manifiesto.json"
    meta = json.loads(meta_ruta.read_bytes())
    casos = [json.loads(l) for l in ruta.read_text().splitlines()]
    if defecto == "hash":
        ruta.write_bytes(ruta.read_bytes() + b"\n")
    elif defecto in {"autoria", "humanos", "referencias"}:
        if defecto == "autoria":
            meta["autoria"]["tipo"] = "humana"
        elif defecto == "humanos":
            meta["cumple_requisito_20_humanos"] = True
        else:
            meta["fuentes_referencia"] = []
        meta_ruta.write_text(json.dumps(meta))
    else:
        if defecto == "categoria":
            casos[0]["categoria"] = "VALOR PRIVADO"
        elif defecto == "duplicado":
            casos[0]["texto"] = casos[1]["texto"].upper()
        elif defecto == "id":
            casos[0]["ticket_id"] = casos[1]["ticket_id"]
        elif defecto == "justificacion":
            casos[0]["justificacion"] = {}
        else:
            casos[0]["autor_humano"] = "VALOR PRIVADO"
        actualizar_meta(evaluador, raiz, ruta, casos)
    with pytest.raises(evaluador.ErrorSinteticos) as e:
        evaluador.cargar_conjunto(ruta, raiz=raiz)
    assert "VALOR PRIVADO" not in str(e.value)


def test_no_copia_f3_ni_aun_con_manifiesto_recalculado(evaluador, copia):
    raiz, ruta, _ = copia
    casos, _ = evaluador.cargar_conjunto(ruta, raiz=raiz)
    f3 = raiz / "datos/f3_tickets/tickets.jsonl"
    fila = json.loads(f3.read_text().splitlines()[0])
    casos[0]["texto"] = "  " + fila["texto"].upper().replace(" ", "  ")
    actualizar_meta(evaluador, raiz, ruta, casos)
    with pytest.raises(evaluador.ErrorSinteticos):
        evaluador.cargar_conjunto(ruta, raiz=raiz)


def test_solo_validar_no_importa_clasificadores_ni_infiere(evaluador, monkeypatch, capsys):
    def prohibido(*args, **kwargs):
        raise AssertionError("No debe cargar clasificadores, NER ni usar red")
    monkeypatch.setattr(evaluador, "crear_clasificador", prohibido)
    monkeypatch.setattr(evaluador, "predicciones_tfidf", prohibido)
    monkeypatch.setattr(socket.socket, "connect", prohibido)
    monkeypatch.setattr(subprocess, "Popen", prohibido)
    importar = builtins.__import__
    def importar_sin_modelos(nombre, *args, **kwargs):
        if nombre.startswith(("tickets_rag.clasificador", "spacy", "presidio_analyzer", "torch")):
            return prohibido()
        return importar(nombre, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", importar_sin_modelos)
    monkeypatch.setattr(sys, "argv", ["evaluar_sinteticos.py", "--solo-validar"])
    evaluador.main()
    salida = json.loads(capsys.readouterr().out)
    assert salida["inferencias_ejecutadas"] == 0 and salida["metricas"] is None


def test_corrida_completa_reanuda_sin_repetir_y_entrena_solo_indice(evaluador, copia, monkeypatch):
    raiz, ruta, salida = copia
    casos, _ = evaluador.cargar_conjunto(ruta, raiz=raiz)
    llamadas, train, _ = fake_clasificadores(evaluador, monkeypatch, casos)
    resumen, carpeta = evaluador.ejecutar(ruta=ruta, salida_base=salida, raiz=raiz)
    assert llamadas == list(evaluador.IDS)
    assert train and all(t["particion"] == "indice" for t in train)
    assert not {c["texto"] for c in casos} & {t["texto"] for t in train}
    assert resumen["estado"] == "completo" and resumen["tickets_medidos"] == 20
    assert resumen["macro_f1"] == {s: {"categoria": 1.0, "prioridad": 1.0} for s in ("tfidf", "llm")}
    assert resumen["tokens_entrada_tickets_completos"] == 200 and resumen["tokens_salida_tickets_completos"] == 40
    assert resumen["cumple_requisito_20_humanos"] is False
    raw = (carpeta / "mediciones_parciales.jsonl").read_bytes()
    segunda, otra = evaluador.ejecutar(ruta=ruta, salida_base=salida, raiz=raiz, reanudar=carpeta.name)
    assert llamadas == list(evaluador.IDS) and otra == carpeta and segunda == resumen
    assert (carpeta / "mediciones_parciales.jsonl").read_bytes() == raw
    registro = json.loads((carpeta / "corrida.json").read_bytes())
    assert registro["plan"]["ajustes"] == evaluador.AJUSTES and registro["plan"]["juegos"] == [0, 1, 2, 3, 4]
    assert len(registro["sistemas_sha256"]) == 5


def test_interrupcion_conserva_parciales_y_reintento_explicito_mismo_uuid(evaluador, copia, monkeypatch):
    raiz, ruta, salida = copia
    casos, _ = evaluador.cargar_conjunto(ruta, raiz=raiz)
    llamadas, _, control = fake_clasificadores(evaluador, monkeypatch, casos, fallar_en="SYN-03")
    notificaciones = []
    with pytest.raises(evaluador.ErrorSinteticos) as e:
        evaluador.ejecutar(ruta=ruta, salida_base=salida, raiz=raiz, al_reservar=notificaciones.append)
    assert "DATO SECRETO" not in str(e.value)
    carpeta = salida / notificaciones[0]["corrida_id"]
    parcial = json.loads((carpeta / "resumen.json").read_bytes())
    assert parcial["estado"] == "incompleto" and parcial["tickets_medidos"] == 2 and parcial["metricas_parciales"]
    assert parcial["tokens_entrada_tickets_completos"] == 20
    assert llamadas == ["SYN-01", "SYN-02", "SYN-03"]
    with pytest.raises(evaluador.ErrorSinteticos, match="reintentar-pendiente"):
        evaluador.ejecutar(ruta=ruta, salida_base=salida, raiz=raiz, reanudar=carpeta.name)
    assert llamadas == ["SYN-01", "SYN-02", "SYN-03"]
    control["fallar_en"] = None
    resumen, misma = evaluador.ejecutar(ruta=ruta, salida_base=salida, raiz=raiz,
                                      reanudar=carpeta.name, reintentar_pendiente=True)
    assert misma == carpeta and resumen["tickets_medidos"] == 20
    assert llamadas == ["SYN-01", "SYN-02", "SYN-03", *evaluador.IDS[2:]]
    eventos = [json.loads(l) for l in (carpeta / "mediciones_parciales.jsonl").read_text().splitlines()]
    assert len([e for e in eventos if e["evento"] == "resultado"]) == 20
    assert "DATO SECRETO" not in (carpeta / "mediciones_parciales.jsonl").read_text()
    assert "ultimo_error" not in json.loads((carpeta / "corrida.json").read_bytes())


@pytest.mark.parametrize("cambio", ["modelo", "variante", "parciales", "tfidf", "prompt", "datos", "codigo", "referencia"])
def test_reanudar_rechaza_cambios_sin_nuevas_llamadas(evaluador, copia, monkeypatch, cambio):
    raiz, ruta, salida = copia
    casos, _ = evaluador.cargar_conjunto(ruta, raiz=raiz)
    llamadas, _, _ = fake_clasificadores(evaluador, monkeypatch, casos, fallar_en="SYN-02")
    with pytest.raises(evaluador.ErrorSinteticos):
        evaluador.ejecutar(ruta=ruta, salida_base=salida, raiz=raiz)
    carpeta = next(salida.iterdir())
    if cambio == "modelo":
        monkeypatch.setattr(config, "MODELO_CLASIFICADOR", "modelo-distinto")
    elif cambio == "prompt":
        monkeypatch.setattr(evaluador, "crear_clasificador", lambda m: SimpleNamespace(sistemas=["PROMPT CAMBIADO"] * 5))
    elif cambio == "parciales":
        with (carpeta / "mediciones_parciales.jsonl").open("a") as f:
            f.write('{"json_incompleto":')
    elif cambio == "datos":
        casos[0]["texto"] += " Otro detalle de prueba, sin cambiar el oráculo."
        actualizar_meta(evaluador, raiz, ruta, casos)
    elif cambio == "referencia":
        p = raiz / "datos/manifiesto.json"
        p.write_bytes(p.read_bytes() + b"\n")
        actualizar_meta(evaluador, raiz, ruta)
    elif cambio == "codigo":
        plan_original = evaluador._plan
        def otro_plan(*args):
            p = plan_original(*args)
            p["codigo_sha256"]["scripts/evaluar_sinteticos.py"] = "f" * 64
            return p
        monkeypatch.setattr(evaluador, "_plan", otro_plan)
    else:
        registro_ruta = carpeta / "corrida.json"
        registro = json.loads(registro_ruta.read_bytes())
        if cambio == "variante":
            registro["plan"]["variante"] = "original"
        else:
            registro["tfidf"]["SYN-01"]["categoria"] = "OTRO"
        registro_ruta.write_text(json.dumps(registro))
    antes = llamadas.copy()
    with pytest.raises(evaluador.ErrorSinteticos):
        evaluador.ejecutar(ruta=ruta, salida_base=salida, raiz=raiz,
                          reanudar=carpeta.name, reintentar_pendiente=True)
    assert llamadas == antes


def test_preparacion_local_fallida_no_inventa_metricas(evaluador, copia, monkeypatch):
    raiz, ruta, salida = copia
    casos, _ = evaluador.cargar_conjunto(ruta, raiz=raiz)
    llamadas, _, _ = fake_clasificadores(evaluador, monkeypatch, casos)
    def fallar(modelo):
        raise RuntimeError("DATO SECRETO NO MOSTRAR")
    monkeypatch.setattr(evaluador, "crear_clasificador", fallar)
    with pytest.raises(evaluador.ErrorSinteticos) as e:
        evaluador.ejecutar(ruta=ruta, salida_base=salida, raiz=raiz)
    assert not llamadas and "DATO SECRETO" not in str(e.value)
    carpeta = next(salida.iterdir())
    resumen = json.loads((carpeta / "resumen.json").read_bytes())
    assert resumen["tickets_medidos"] == 0 and resumen["macro_f1"] is None
    assert not (carpeta / "mediciones_parciales.jsonl").exists()


def test_uuid_invalido_y_bloqueo_no_inician_modelos(evaluador, copia, monkeypatch):
    raiz, ruta, salida = copia
    casos, _ = evaluador.cargar_conjunto(ruta, raiz=raiz)
    llamadas, _, _ = fake_clasificadores(evaluador, monkeypatch, casos, fallar_en="SYN-01")
    with pytest.raises(evaluador.ErrorSinteticos):
        evaluador.ejecutar(ruta=ruta, salida_base=salida, raiz=raiz, reanudar="../otra")
    assert not llamadas and not salida.exists()
    with pytest.raises(evaluador.ErrorSinteticos):
        evaluador.ejecutar(ruta=ruta, salida_base=salida, raiz=raiz)
    carpeta = next(salida.iterdir())
    antes = llamadas.copy()
    with evaluador._bloquear(carpeta):
        with pytest.raises(evaluador.ErrorSinteticos, match="Otra instancia"):
            evaluador.ejecutar(ruta=ruta, salida_base=salida, raiz=raiz,
                              reanudar=carpeta.name, reintentar_pendiente=True)
    assert llamadas == antes


def test_interrupcion_sin_evento_error_requiere_reintento_explicito(evaluador, copia, monkeypatch):
    raiz, ruta, salida = copia
    casos, _ = evaluador.cargar_conjunto(ruta, raiz=raiz)
    llamadas, _, _ = fake_clasificadores(evaluador, monkeypatch, casos)
    original = evaluador.crear_clasificador(config.MODELO_CLASIFICADOR)
    clasificar = original.clasificar
    def interrumpir(texto):
        if texto == casos[1]["texto"]:
            raise KeyboardInterrupt()
        return clasificar(texto)
    original.clasificar = interrumpir
    monkeypatch.setattr(evaluador, "crear_clasificador", lambda _: original)
    with pytest.raises(KeyboardInterrupt):
        evaluador.ejecutar(ruta=ruta, salida_base=salida, raiz=raiz)
    carpeta = next(salida.iterdir())
    with pytest.raises(evaluador.ErrorSinteticos, match="reintentar-pendiente"):
        evaluador.ejecutar(ruta=ruta, salida_base=salida, raiz=raiz, reanudar=carpeta.name)
    original.clasificar = clasificar
    resumen, _ = evaluador.ejecutar(ruta=ruta, salida_base=salida, raiz=raiz,
                                  reanudar=carpeta.name, reintentar_pendiente=True)
    assert llamadas == list(evaluador.IDS) and resumen["tickets_medidos"] == 20


def test_tfidf_usa_pipeline_actual_y_solo_etiquetas_de_entrenamiento(evaluador, monkeypatch):
    from tickets_rag import clasificador
    vistos = []
    class Modelo:
        def fit(self, x, y):
            vistos.append((list(x), list(y)))
            self.campo = "categoria" if y[0] == "RED" else "prioridad"
            return self
        def predict(self, x):
            assert list(x) == ["PREPARADO caso reservado"]
            return ["RED" if self.campo == "categoria" else "MEDIA"]
    monkeypatch.setattr(clasificador, "construir", Modelo)
    monkeypatch.setattr(clasificador, "preparar", lambda t: "PREPARADO " + t)
    r = evaluador.predicciones_tfidf([{"ticket_id": "SYN-01", "texto": "caso reservado"}],
                                    [{"texto": "solo entrenamiento", "categoria": "RED", "prioridad": "MEDIA"}])
    assert r == {"SYN-01": {"categoria": "RED", "prioridad": "MEDIA"}}
    assert vistos == [(["PREPARADO solo entrenamiento"], ["RED"]), (["PREPARADO solo entrenamiento"], ["MEDIA"])]
