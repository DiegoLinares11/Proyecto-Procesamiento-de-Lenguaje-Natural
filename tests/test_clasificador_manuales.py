"""El holdout humano no entra al entrenamiento y validar no consume cuota."""

import sys
import json
from types import SimpleNamespace

import pytest

from scripts import evaluar_clasificador_llm as evaluador


def test_preparar_manuales_solo_entrena_con_f3_del_indice(monkeypatch, tmp_path):
    manuales = [{"ticket_id": f"MAN-{i:02d}", "texto": "fixture de contrato"} for i in range(1, 21)]
    monkeypatch.setattr(evaluador, "cargar_manuales", lambda ruta: manuales)
    tickets = [{"ticket_id": "indice", "particion": "indice"}, {"ticket_id": "prueba", "particion": "prueba"}]
    casos, entrenamiento = evaluador.preparar_conjunto(tickets, "manuales", tmp_path / "tickets.jsonl")
    assert casos is manuales and entrenamiento == [tickets[0]]
    assert not {t["ticket_id"] for t in casos} & {t["ticket_id"] for t in entrenamiento}


def test_solo_validar_manuales_no_construye_clasificadores(monkeypatch, capsys):
    def inesperado(*args, **kwargs):
        raise AssertionError("Validar no debe entrenar ni llamar al modelo")

    monkeypatch.setattr(sys, "argv", ["evaluar_clasificador_llm.py", "--conjunto", "manuales", "--solo-validar"])
    monkeypatch.setattr(evaluador, "preparar_conjunto", lambda *a: ([{}] * 20, [{}] * 240))
    monkeypatch.setattr(evaluador, "construir", inesperado)
    monkeypatch.setattr(evaluador, "ClasificadorLLM", inesperado)
    evaluador.main()
    assert '"inferencias_ejecutadas": 0' in capsys.readouterr().out


def test_reordenar_tickets_no_permite_otra_medicion(tmp_path):
    casos = [{"ticket_id": "MAN-02", "texto": "fixture B"}, {"ticket_id": "MAN-01", "texto": "fixture A"}]
    assert evaluador.identidad_manuales(casos) == evaluador.identidad_manuales(list(reversed(casos)))
    ruta = tmp_path / "tickets.jsonl"
    ruta.write_text("fixture\n")
    (tmp_path / "manifiesto.json").write_text("{}")
    salida = tmp_path / "salida"
    meta = evaluador.reservar_intento(salida, ruta, casos, "juegos_criterios")
    assert meta["manifiesto_sha256"] and (salida / "intento.json").exists()
    with pytest.raises(ValueError, match="Ya existe"):
        evaluador.reservar_intento(salida, ruta, list(reversed(casos)), "original")


def test_interrupcion_conserva_primera_medicion_y_no_repite(monkeypatch, tmp_path):
    casos = [{"ticket_id": f"MAN-{i:02d}", "texto": "fixture de prueba"} for i in range(1, 21)]
    ruta = tmp_path / "tickets.jsonl"
    ruta.write_text("fixture, no es un holdout humano\n")
    (tmp_path / "manifiesto.json").write_text("{}")
    llamadas = []

    def clasificar(texto):
        llamadas.append(texto)
        if len(llamadas) == 2:
            raise RuntimeError("modelo falso interrumpido")
        return SimpleNamespace(model_dump=lambda: {"categoria": "RED", "prioridad": "MEDIA"})

    monkeypatch.setattr(evaluador, "SALIDA", tmp_path / "resultados")
    monkeypatch.setattr(evaluador, "preparar_conjunto", lambda *a: (casos, [{"texto": "fixture F3", "categoria": "RED", "prioridad": "MEDIA"}]))
    modelo = SimpleNamespace(fit=lambda *a: SimpleNamespace(predict=lambda textos: ["RED"] * len(textos)))
    monkeypatch.setattr(evaluador, "construir", lambda: modelo)
    monkeypatch.setattr(evaluador, "preparar", lambda t: t)
    monkeypatch.setattr(evaluador, "ClasificadorLLM", lambda **k: SimpleNamespace(clasificar=clasificar))
    monkeypatch.setattr(sys, "argv", ["eval", "--conjunto", "manuales", "--variante", "juegos_criterios",
                                      "--tickets-manuales", str(ruta)])
    with pytest.raises(RuntimeError, match="modelo falso"):
        evaluador.main()
    carpeta = evaluador.SALIDA / "manuales" / evaluador.identidad_manuales(casos)
    assert len((carpeta / "mediciones_parciales.jsonl").read_text().splitlines()) == 1
    assert json.loads((carpeta / "intento.json").read_text())["estado"].startswith("incompleto")
    with pytest.raises(SystemExit):
        evaluador.main()
    assert len(llamadas) == 2
