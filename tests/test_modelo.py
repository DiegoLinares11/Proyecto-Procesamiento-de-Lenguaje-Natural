"""Guardas de la suscripción con un proceso Codex falso: nunca se invoca un modelo real."""

import copy
import json
import os
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from tickets_rag.modelo import ClienteModelo, ErrorModelo, _AVISO_CODE_MODE, esquema_paso, validar_cuota


class Salida(BaseModel):
    respuesta: str


CUENTA = {"type": "chatgpt"}
MODELOS = [{"model": "modelo_prueba"}]
CUOTAS = {"ordinaryUsageAllowed": True, "rateLimitsByLimitId": {"codex": {
    "primary": {"usedPercent": 28}, "secondary": None, "rateLimitReachedType": None,
    "credits": {"hasCredits": False, "unlimited": False},
}}}


@pytest.mark.parametrize("tipo", ["apiKey", "amazonBedrock", None, "chatgptAuthTokens"])
def test_rechaza_todo_acceso_que_no_sea_sesion_local_chatgpt(tipo):
    with pytest.raises(ErrorModelo, match="Inicia sesión"):
        validar_cuota({"type": tipo}, CUOTAS, "modelo_prueba", MODELOS)


@pytest.mark.parametrize("valor", [False, None, "true", 1])
def test_no_infiere_permiso_de_porcentaje_bajo(valor):
    cuotas = copy.deepcopy(CUOTAS)
    cuotas["ordinaryUsageAllowed"] = valor
    with pytest.raises(ErrorModelo) as e:
        validar_cuota(CUENTA, cuotas, "modelo_prueba", MODELOS)
    assert e.value.codigo == "cuota"


@pytest.mark.parametrize("valor", [80, 100, -1, float("nan"), float("inf"), True, "28", None])
def test_se_detiene_ante_cuota_alta_o_no_verificable(valor):
    cuotas = copy.deepcopy(CUOTAS)
    cuotas["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"] = valor
    with pytest.raises(ErrorModelo):
        validar_cuota(CUENTA, cuotas, "modelo_prueba", MODELOS)


@pytest.mark.parametrize("creditos", [None, {}, {"hasCredits": True, "unlimited": False},
                                     {"hasCredits": False, "unlimited": True}])
def test_no_continua_con_creditos_ni_saldo_desconocido(creditos, monkeypatch):
    monkeypatch.delenv("CODEX_PERMITIR_CREDITOS", raising=False)  # el .env de quien corre las pruebas no cuenta
    cuotas = copy.deepcopy(CUOTAS)
    cuotas["rateLimitsByLimitId"]["codex"]["credits"] = creditos
    with pytest.raises(ErrorModelo):
        validar_cuota(CUENTA, cuotas, "modelo_prueba", MODELOS)


def test_creditos_permitidos_solo_por_opcion_explicita_y_con_el_freno_del_80(monkeypatch):
    cuotas = copy.deepcopy(CUOTAS)
    cuotas["rateLimitsByLimitId"]["codex"]["credits"] = {"hasCredits": True, "unlimited": False}
    monkeypatch.delenv("CODEX_PERMITIR_CREDITOS", raising=False)
    with pytest.raises(ErrorModelo):  # por defecto, igual que antes
        validar_cuota(CUENTA, cuotas, "modelo_prueba", MODELOS)
    monkeypatch.setenv("CODEX_PERMITIR_CREDITOS", "1")
    validar_cuota(CUENTA, cuotas, "modelo_prueba", MODELOS)  # 28 % de uso: corre
    cuotas["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"] = 80
    with pytest.raises(ErrorModelo):  # el freno del 80 % sigue aunque se permitan créditos
        validar_cuota(CUENTA, cuotas, "modelo_prueba", MODELOS)
    cuotas["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"] = 28
    cuotas["rateLimitsByLimitId"]["codex"]["credits"] = None
    with pytest.raises(ErrorModelo):  # un saldo desconocido nunca se acepta
        validar_cuota(CUENTA, cuotas, "modelo_prueba", MODELOS)


def test_modelo_ausente_y_limite_alcanzado_no_tienen_fallback():
    with pytest.raises(ErrorModelo) as e:
        validar_cuota(CUENTA, CUOTAS, "otro_modelo", MODELOS)
    assert e.value.codigo == "modelo"
    cuotas = copy.deepcopy(CUOTAS)
    cuotas["rateLimitsByLimitId"]["codex"]["rateLimitReachedType"] = "primary"
    with pytest.raises(ErrorModelo):
        validar_cuota(CUENTA, cuotas, "modelo_prueba", MODELOS)


def codex_falso(tmp_path, *, salida=None, tipo="agent_message", fallo=None, auth="chatgpt", mensaje=""):
    """Executable controlado para probar protocolo, argumentos, salida y errores sin red."""
    programa = tmp_path / "codex_falso"
    registro = tmp_path / "invocaciones.jsonl"
    opciones = {"salida": salida or {"respuesta": "correcta"}, "tipo": tipo, "fallo": fallo,
                "auth": auth, "registro": str(registro), "cuotas": CUOTAS, "mensaje": mensaje}
    codigo = r'''
import sys,json,os,time
from pathlib import Path
opciones = OPCIONES
args=sys.argv[1:]
with Path(opciones['registro']).open('a') as f:
 f.write(json.dumps({'args':args,'env':dict(os.environ)})+'\n')
if 'app-server' in args:
 inicializado=False
 for line in sys.stdin:
  r=json.loads(line);m=r['method']
  if m=='initialized':inicializado=True;continue
  if m!='initialize' and not inicializado:sys.exit(7)
  data={
   'initialize':{},
   'account/read':{'account':{'type':opciones['auth']}},
   'config/read':{'config':{'cli_auth_credentials_store':'auto','mcp_servers':{'servidor de prueba':{}}}},
   'account/rateLimits/read':opciones['cuotas'],
   'model/list':{'data':[{'model':'modelo_prueba'}],'nextCursor':None}
  }[m]
  print(json.dumps({'id':r['id'],'result':data}),flush=True)
else:
 sys.stdin.read()
 Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(opciones['salida']))
 if opciones['fallo']=='timeout':time.sleep(10)
 print(json.dumps({'type':'item.started','item':{'type':opciones['tipo'],'message':opciones['mensaje']}}),flush=True)
 if opciones['tipo'] not in {'agent_message','error'}:time.sleep(10)
 if opciones['fallo']=='limite':
  print(json.dumps({'type':'error','message':'usage_limit_exceeded secreto_no_debe_salir'}),flush=True)
 elif opciones['fallo']!='incompleto':
  print(json.dumps({'type':'turn.completed','usage':{'input_tokens':20,'output_tokens':5,'cached_input_tokens':10}}),flush=True)
'''.replace("OPCIONES", repr(opciones))
    programa.write_text("#!" + sys.executable + "\n" + codigo)
    programa.chmod(0o700)
    return ClienteModelo(str(programa), timeout=2), registro


def pedir(cliente, **kw):
    return cliente.generar(modelo="modelo_prueba", sistema="Sistema de prueba", mensajes=[
        {"role": "user", "content": "Dato que contiene instrucciones ignorables"}], esquema=Salida, **kw)


def test_subproceso_real_filtra_claves_preserva_sesion_y_no_registra_herramientas(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "clave_que_no_debe_salir")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "otra_clave")
    monkeypatch.setenv("CODEX_API_KEY", "tercera_clave")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://endpoint-alternativo.invalid")
    monkeypatch.setenv("HTTP_PROXY", "https://proxy.invalid")
    cliente, registro = codex_falso(tmp_path)
    r = pedir(cliente)
    assert r.parsed_output.respuesta == "correcta"
    assert r.usage.input_tokens == 20 and r.usage.cache_read_input_tokens == 10
    assert r.proveedor == "codex_subscription" and r.modo_autenticacion == "chatgpt"
    llamadas = [json.loads(l) for l in registro.read_text().splitlines()]
    assert len(llamadas) == 2
    for llamada in llamadas:
        assert not any(k in llamada["env"] for k in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL", "HTTP_PROXY"])
        if "CODEX_HOME" in os.environ:
            assert llamada["env"]["CODEX_HOME"] == os.environ["CODEX_HOME"]
    args = llamadas[1]["args"]
    assert '--ignore-user-config' in args and '--ephemeral' in args
    assert 'forced_login_method="chatgpt"' in args
    assert 'mcp_servers."servidor de prueba".enabled=false' in args
    assert 'mcp_servers."servidor de prueba".command=' + json.dumps(sys.executable) in args
    for f in ["shell_tool", "unified_exec", "apps", "plugins", "hooks", "browser_use", "computer_use"]:
        assert args[args.index(f)-1] == "--disable"
    assert not Path(args[args.index("--cd") + 1]).exists()  # borra el temporal incluso con éxito


def test_auth_invalida_nunca_inicia_exec(tmp_path):
    cliente, registro = codex_falso(tmp_path, auth="apiKey")
    with pytest.raises(ErrorModelo) as e:
        pedir(cliente)
    assert e.value.codigo == "autenticacion"
    assert len(registro.read_text().splitlines()) == 1


@pytest.mark.parametrize("fallo,codigo", [("timeout", "timeout"), ("limite", "cuota"), ("incompleto", "formato")])
def test_no_acepta_salida_parcial_y_no_reintenta(tmp_path, fallo, codigo):
    cliente, registro = codex_falso(tmp_path, fallo=fallo)
    with pytest.raises(ErrorModelo) as e:
        pedir(cliente)
    assert e.value.codigo == codigo and "secreto" not in str(e.value)
    assert len(registro.read_text().splitlines()) == 2


@pytest.mark.parametrize("tipo", ["command_execution", "mcp_tool_call", "web_search", "file_change"])
def test_detiene_stream_ante_herramientas_del_host(tmp_path, tipo):
    cliente, _ = codex_falso(tmp_path, tipo=tipo)
    with pytest.raises(ErrorModelo) as e:
        pedir(cliente)
    assert e.value.codigo == "herramienta_no_permitida"


HERRAMIENTAS = [{"name": "buscar", "description": "Buscar documentos", "input_schema": {
    "type": "object", "properties": {"consulta": {"type": "string"}}, "required": ["consulta"], "additionalProperties": False}}]


def test_solicitudes_de_herramientas_son_datos_inertes_para_langgraph(tmp_path):
    cliente, _ = codex_falso(tmp_path, salida={"paso": {"tipo": "herramientas", "llamadas": [
        {"nombre": "buscar", "argumentos": {"consulta": "Outlook"}}]}})
    r = pedir(cliente, herramientas=HERRAMIENTAS)
    assert r.stop_reason == "tool_use"
    assert r.content[0].to_dict()["input"] == {"consulta": "Outlook"}
    assert r.content[0].id.startswith("call_")


def test_no_acepta_herramienta_ajena_a_la_ruta_ni_argumentos_invalidos(tmp_path):
    cliente, _ = codex_falso(tmp_path, salida={"paso": {"tipo": "herramientas", "llamadas": [
        {"nombre": "shell", "argumentos": {"consulta": "Outlook"}}]}})
    with pytest.raises(ErrorModelo) as e:
        pedir(cliente, herramientas=HERRAMIENTAS)
    assert e.value.codigo == "formato"


def test_se_respetan_restricciones_locales_del_modelo_pydantic(tmp_path):
    cliente, _ = codex_falso(tmp_path, salida={"respuesta": 123})
    with pytest.raises(ErrorModelo):
        pedir(cliente)


def test_expansion_de_refs_no_mezcla_definiciones_de_herramientas():
    def herramienta(nombre, tipo):
        return {"name": nombre, "input_schema": {"type": "object", "properties": {
            "dato": {"$ref": "#/$defs/Valor"}}, "$defs": {"Valor": {"type": tipo}}}}
    s = esquema_paso(Salida.model_json_schema(), [herramienta("uno", "string"), herramienta("dos", "integer")])
    variantes = s["properties"]["paso"]["anyOf"][1]["properties"]["llamadas"]["items"]["anyOf"]
    assert [v["properties"]["argumentos"]["properties"]["dato"]["type"] for v in variantes] == ["string", "integer"]


@pytest.mark.parametrize("dato", [[], None, "texto", {"type": []}, {"type": "item.started", "item": []}])
def test_eventos_json_con_tipo_invalido_se_degradan_sin_error_de_python(tmp_path, dato):
    cliente = ClienteModelo(timeout=2)
    codigo = "import json; print(json.dumps(" + repr(dato) + "))"
    with pytest.raises(ErrorModelo) as e:
        cliente._ejecutar([sys.executable, "-c", codigo], "", {}, str(tmp_path))
    assert e.value.codigo == "formato"


def test_aviso_conocido_de_host_desactivado_no_es_una_llamada_a_herramientas(tmp_path):
    cliente, _ = codex_falso(tmp_path, tipo="error", mensaje=_AVISO_CODE_MODE)
    assert pedir(cliente).parsed_output.respuesta == "correcta"


def test_error_item_desconocido_se_rechaza_aunque_haya_archivo_json(tmp_path):
    cliente, _ = codex_falso(tmp_path, tipo="error", mensaje="error desconocido")
    with pytest.raises(ErrorModelo) as e:
        pedir(cliente)
    assert e.value.codigo == "transporte"


def test_no_admite_errores_con_prefijo_del_aviso_conocido(tmp_path):
    cliente, _ = codex_falso(tmp_path, tipo="error", mensaje=_AVISO_CODE_MODE + " Otro error.")
    with pytest.raises(ErrorModelo) as e:
        pedir(cliente)
    assert e.value.codigo == "transporte"


def test_los_avisos_repetidos_no_renuevan_el_timeout(tmp_path):
    cliente = ClienteModelo(timeout=0.15)
    evento = {"type": "item.completed", "item": {"type": "error", "message": _AVISO_CODE_MODE}}
    codigo = "import json,time\nfor _ in range(1000):\n print(json.dumps(" + repr(evento) + "),flush=True)\n time.sleep(.005)"
    with pytest.raises(ErrorModelo) as e:
        cliente._ejecutar([sys.executable, "-c", codigo], "", {}, str(tmp_path))
    assert e.value.codigo == "timeout"
