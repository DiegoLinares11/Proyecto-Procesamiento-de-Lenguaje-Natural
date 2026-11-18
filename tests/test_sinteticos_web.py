"""La vista identifica IA y no atribuye a estos casos métricas de otro conjunto."""

import hashlib
import json
import shutil

import pytest

from tickets_rag import config
from tickets_rag.sinteticos_web import ErrorVistaSinteticos, obtener_sinteticos


@pytest.fixture
def raiz(tmp_path):
    destino = tmp_path / "evaluacion/tickets_sinteticos"
    shutil.copytree(config.EVALUACION / "tickets_sinteticos", destino)
    return tmp_path


def test_vista_muestra_20_sinteticos_sin_acreditar_autoria_humana(raiz):
    d = obtener_sinteticos(raiz)
    assert len(d["tickets"]) == 20
    assert d["metadatos"]["autoria"]["tipo"] == "IA"
    assert d["metadatos"]["cumple_requisito_20_humanos"] is False
    assert d["evaluacion"]["estado"] == "sin_iniciar"
    assert d["evaluacion"]["macro_f1"] is None


def test_vista_rechaza_textos_alterados_aunque_json_siga_valido(raiz):
    p = raiz / "evaluacion/tickets_sinteticos/tickets.jsonl"
    p.write_text(p.read_text().replace('SYN-01', 'SYN-20'))
    with pytest.raises(ErrorVistaSinteticos):
        obtener_sinteticos(raiz)


def escribir_resumen(raiz, *, ajeno=False, completo=False, medidos=3):
    conjunto = raiz / "evaluacion/tickets_sinteticos"
    plan = {"tickets_sha256": hashlib.sha256((conjunto / 'tickets.jsonl').read_bytes()).hexdigest(),
            "manifiesto_sha256": hashlib.sha256((conjunto / 'manifiesto.json').read_bytes()).hexdigest()}
    if ajeno:
        plan["tickets_sha256"] = '0' * 64
    huella = hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    carpeta = raiz / "resultados/codex_suscripcion/clasificador_sinteticos/ejemplo"
    carpeta.mkdir(parents=True)
    registro = {"plan": plan, "plan_sha256": huella, "corrida_id": 'ejemplo'}
    resumen = {"plan_sha256": huella, "corrida_id": 'ejemplo', "autoria": 'IA',
               "cumple_requisito_20_humanos": False, "tickets_objetivo": 20, "tickets_medidos": medidos,
               "estado": 'completo' if completo else 'incompleto', "metricas_parciales": not completo,
               "macro_f1": {"llm": {"categoria": .75, "prioridad": .5}}}
    (carpeta / 'corrida.json').write_text(json.dumps(registro))
    (carpeta / 'resumen.json').write_text(json.dumps(resumen))


def test_no_atribuye_resultados_de_otro_conjunto(raiz):
    escribir_resumen(raiz, ajeno=True)
    assert obtener_sinteticos(raiz)["evaluacion"]["estado"] == 'sin_iniciar'


def test_conserva_la_indicacion_parcial_y_rechaza_falso_completo(raiz):
    escribir_resumen(raiz)
    assert obtener_sinteticos(raiz)["evaluacion"]["metricas_parciales"] is True
    p = raiz / "resultados/codex_suscripcion/clasificador_sinteticos/ejemplo/resumen.json"
    d = json.loads(p.read_text())
    d.update(estado='completo', metricas_parciales=False)
    p.write_text(json.dumps(d))
    assert obtener_sinteticos(raiz)["evaluacion"]["estado"] == 'sin_iniciar'
