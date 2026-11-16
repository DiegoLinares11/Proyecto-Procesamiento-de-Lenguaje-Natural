"""Pruebas de las herramientas sin llamar a la API: cliente falso, herramientas falsas y la base local."""

import time
from types import SimpleNamespace

import psycopg
import pytest

from tickets_rag import herramientas as H
from tickets_rag.clasificador_llm import Clasificacion, ClasificadorLLM
from tickets_rag.ingesta import cargar_chunks

CTX = H.Contexto(ticket_id="TCK-2026-09001", rol="N1")
TODAS = set(H.HERRAMIENTAS)


@pytest.fixture(scope="module")
def chunks():
    return cargar_chunks()


@pytest.fixture
def recursos_minimos(chunks):
    return H.Recursos(chunks=chunks, bm25=H.IndiceBM25(chunks))


# ---------------------------------------------------------------- Ejecución, permisos y límites

def test_herramienta_fuera_de_la_ruta_se_rechaza(recursos_minimos):
    r = H.ejecutar(recursos_minimos, CTX, "take_action", {"accion": "restablecer_mfa", "motivo": "x"}, {"search_docs"})
    assert not r.ok and "no está permitida en esta ruta" in r.error and r.intentos == 0


def test_herramienta_inexistente(recursos_minimos):
    r = H.ejecutar(recursos_minimos, CTX, "borrar_base", {}, TODAS)
    assert not r.ok and "no existe" in r.error


@pytest.mark.parametrize("nombre, argumentos, fragmento", [
    ("search_docs", {"query": "vpn", "top_k": 50}, "top_k"),
    ("buscar_casos_similares", {"query": "vpn", "top_k": 0}, "top_k"),
    ("query_tickets", {"peticion": {"consulta": "escalados", "desde": "2026-01-01", "hasta": "2026-02-01", "limite": 500}}, "limite"),
    ("query_tickets", {"peticion": {"consulta": "borrar_todo"}}, "peticion"),
    ("take_action", {"accion": "formatear_disco", "motivo": "x"}, "accion"),
    # El ticket y el rol salen de la sesión: el modelo no puede elegirlos.
    ("take_action", {"accion": "restablecer_mfa", "motivo": "x", "ticket_id": "TCK-2026-00001"}, "Extra inputs"),
    ("escalate", {"motivo": "x", "rol": "N2"}, "Extra inputs"),
])
def test_argumentos_invalidos_vuelven_como_error_para_el_modelo(recursos_minimos, nombre, argumentos, fragmento):
    r = H.ejecutar(recursos_minimos, CTX, nombre, argumentos, TODAS)
    assert not r.ok and r.error.startswith("Argumentos inválidos") and fragmento in r.error


@pytest.fixture
def falsa(monkeypatch):
    """Registra una herramienta falsa cuyo comportamiento define cada prueba."""
    def registrar(funcion):
        h = H.Herramienta("falsa", "prueba", H.EntradaClasificar, funcion)
        monkeypatch.setitem(H.HERRAMIENTAS, "falsa", h)
    return registrar


def test_servicio_lento_se_corta_y_se_reintenta_una_vez(recursos_minimos, falsa):
    llamadas = []

    def lenta(recursos, contexto, entrada):
        llamadas.append(1)
        time.sleep(1.0)
        return {}

    falsa(lenta)
    r = H.ejecutar(recursos_minimos, CTX, "falsa", {"text": "x"}, {"falsa"}, timeout=0.1)
    assert not r.ok and r.intentos == 2 and "no respondió" in r.error and len(llamadas) == 2


def test_falla_pasajera_se_reintenta_y_luego_funciona(recursos_minimos, falsa):
    estado = {"n": 0}

    def inestable(recursos, contexto, entrada):
        estado["n"] += 1
        if estado["n"] == 1:
            raise psycopg.OperationalError("conexión perdida")
        return {"ok": True}

    falsa(inestable)
    r = H.ejecutar(recursos_minimos, CTX, "falsa", {"text": "x"}, {"falsa"})
    assert r.ok and r.intentos == 2 and r.contenido == {"ok": True}


def test_error_de_la_herramienta_no_se_reintenta(recursos_minimos, falsa):
    estado = {"n": 0}

    def invalida(recursos, contexto, entrada):
        estado["n"] += 1
        raise H.ErrorHerramienta("ticket inexistente")

    falsa(invalida)
    r = H.ejecutar(recursos_minimos, CTX, "falsa", {"text": "x"}, {"falsa"})
    assert not r.ok and r.error == "ticket inexistente" and estado["n"] == 1


def test_esquemas_para_la_api_son_compatibles_con_modo_estricto():
    prohibidas = {"title", "default", "pattern", "minimum", "maximum", "minLength", "maxLength", "maxItems",
                  "oneOf", "discriminator"}

    def revisar(nodo):
        if isinstance(nodo, dict):
            assert not prohibidas & nodo.keys(), nodo.keys()
            if nodo.get("type") == "object":
                assert nodo.get("additionalProperties") is False
            for v in nodo.values():
                revisar(v)
        elif isinstance(nodo, list):
            for v in nodo:
                revisar(v)

    for definicion in H.definiciones_api(sorted(H.HERRAMIENTAS)):
        assert definicion["strict"] is True
        revisar(definicion["input_schema"])


# ---------------------------------------------------------------- Clasificador: votación

class ClienteVotos:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs):
        voto = self.respuestas.pop(0)
        return SimpleNamespace(parsed_output=voto, stop_reason="refusal" if voto is None else "end_turn",
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=20))


def voto(categoria, prioridad="MEDIA", tipo="procedimiento"):
    return Clasificacion(categoria=categoria, prioridad=prioridad, tipo=tipo)


def test_votacion_unanime_no_va_a_revision():
    r = ClasificadorLLM(ClienteVotos([voto("RED")] * 5)).clasificar("La VPN no conecta")
    assert r.categoria == "RED" and r.confianza == {"categoria": 1.0, "prioridad": 1.0, "tipo": 1.0}
    assert not r.needs_human_review


def test_voto_discrepante_o_rechazo_va_a_revision():
    r = ClasificadorLLM(ClienteVotos([voto("RED")] * 3 + [voto("ACCESO"), None])).clasificar("La VPN no conecta")
    assert r.categoria == "RED" and r.confianza["categoria"] == 0.6 and r.needs_human_review
    assert r.corridas_validas == 4  # el rechazo cuenta en contra de la confianza


def test_cada_voto_usa_un_juego_de_ejemplos_distinto():
    c = ClasificadorLLM(ClienteVotos([]))
    assert len(set(c.sistemas)) == c.corridas


def test_el_clasificador_ve_el_texto_enmascarado():
    cliente = ClienteVotos([voto("ACCESO")] * 5)
    vistos = []
    original = cliente.messages.parse
    cliente.messages = SimpleNamespace(parse=lambda **k: vistos.append(k["messages"][0]["content"]) or original(**k))
    ClasificadorLLM(cliente).clasificar("Olvidé la clave, mi correo es ana@correo.example")
    assert all("ana@correo.example" not in v and "[EMAIL_REDACTED]" in v for v in vistos)


# ---------------------------------------------------------------- Con la base de datos

@pytest.fixture(scope="module")
def recursos_bd(chunks):
    try:
        from tickets_rag import acciones, historial, vectores
        from tickets_rag.recuperacion import Configuracion, RecuperadorHibrido

        conexion = vectores.conectar()
        bm25 = H.IndiceBM25(chunks)
        recursos = H.Recursos(
            chunks=chunks, bm25=bm25,
            procedimientos=RecuperadorHibrido(chunks, Configuracion(tipos=["manual", "articulo"]), conexion=conexion, bm25=bm25),
            casos=RecuperadorHibrido(chunks, Configuracion(tipos=["ticket"]), conexion=conexion, bm25=bm25),
            conexion_vectores=conexion,
            conexion_lectura=historial.conectar_lectura(),
            conexion_acciones=acciones.conectar_acciones(),
        )
    except Exception:
        pytest.skip("Base no disponible: docker compose up -d y scripts/preparar_bd.py")
    yield recursos
    conexion.execute("DELETE FROM solicitudes_accion WHERE ticket_id = %s", (CTX.ticket_id,))
    conexion.execute("DELETE FROM escalamientos WHERE ticket_id = %s", (CTX.ticket_id,))


def test_search_docs_devuelve_citas_y_respeta_el_rol(recursos_bd):
    r = H.ejecutar(recursos_bd, CTX, "search_docs", {"query": "¿Cómo se restablece el MFA de un usuario?"}, TODAS, timeout=60)
    assert r.ok and r.contenido["fragmentos"] and r.contenido["evidencia_suficiente"]
    roles = {c["chunk_id"]: c["roles_permitidos"] for c in recursos_bd.chunks}
    assert all("N1" in roles[f["chunk_id"]] for f in r.contenido["fragmentos"])


def test_sin_base_vectorial_sigue_con_bm25_y_lo_marca(recursos_bd, chunks):
    from tickets_rag import vectores
    from tickets_rag.recuperacion import Configuracion, RecuperadorHibrido

    caida = vectores.conectar()
    caida.close()
    roto = H.Recursos(chunks=chunks, bm25=recursos_bd.bm25,
                      procedimientos=RecuperadorHibrido(chunks, Configuracion(tipos=["manual", "articulo"]), conexion=caida, bm25=recursos_bd.bm25))
    r = H.ejecutar(roto, CTX, "search_docs", {"query": "Error 0x80070005 al actualizar"}, TODAS, timeout=60)
    assert r.ok and r.contenido["degradado"] and r.contenido["fragmentos"]


def test_query_tickets_por_la_herramienta(recursos_bd):
    r = H.ejecutar(recursos_bd, CTX, "query_tickets",
                   {"peticion": {"consulta": "conteo_por_categoria", "desde": "2026-10-01", "hasta": "2026-10-31"}}, TODAS)
    assert r.ok and all("categoria" in f for f in r.contenido["filas"])


def test_take_action_usa_el_ticket_de_la_sesion_y_queda_pendiente(recursos_bd):
    r = H.ejecutar(recursos_bd, CTX, "take_action", {"accion": "restablecer_mfa", "motivo": "Perdió el teléfono (2.3)"}, TODAS)
    assert r.ok and r.contenido["ticket_id"] == CTX.ticket_id and r.contenido["estado"] == "pendiente"


def test_escalate_valida_las_fuentes(recursos_bd):
    r = H.ejecutar(recursos_bd, CTX, "escalate", {"motivo": "Sin evidencia", "fuentes": ["F9-c999"]}, TODAS)
    assert not r.ok and "no existen" in r.error
    fuente = recursos_bd.chunks[0]["chunk_id"]
    r = H.ejecutar(recursos_bd, CTX, "escalate", {"motivo": "Sin evidencia", "fuentes": [fuente]}, TODAS)
    assert r.ok and r.contenido["escalado"]
