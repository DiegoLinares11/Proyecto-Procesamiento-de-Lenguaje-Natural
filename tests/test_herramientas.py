"""Pruebas de las herramientas sin llamar a la API: cliente falso, herramientas falsas y la base local."""

import dataclasses
import threading
import time
from concurrent.futures import wait
from contextlib import ExitStack
from types import SimpleNamespace

import psycopg
import pytest

from tickets_rag import herramientas as H
from tickets_rag.clasificador_llm import Clasificacion, ClasificadorLLM
from tickets_rag.ingesta import cargar_chunks
from tickets_rag.modelo import ErrorModelo

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


def test_servicio_lento_agota_dos_ventanas_sin_duplicar_el_worker(recursos_minimos, falsa):
    llamadas = []

    def lenta(recursos, contexto, entrada):
        llamadas.append(1)
        time.sleep(1.0)
        return {}

    falsa(lenta)
    r = H.ejecutar(recursos_minimos, CTX, "falsa", {"text": "x"}, {"falsa"}, timeout=0.1)
    assert not r.ok and r.intentos == 2 and "no respondió" in r.error and len(llamadas) == 1


@pytest.mark.parametrize("consulta,suficiente", [
    ("¿Cuál es la cuota del buzón de correo?", True),
    ("¿Qué días son feriado este año?", False),
])
def test_busqueda_lenta_usa_bm25_con_filtros_y_umbral(recursos_minimos, monkeypatch, consulta, suficiente):
    liberar = threading.Event()
    llamadas = []

    def lenta(*args):
        llamadas.append(1)
        liberar.wait(2)
        return {"fragmentos": []}

    herramienta = dataclasses.replace(H.HERRAMIENTAS["search_docs"], funcion=lenta)
    recursos_minimos.herramientas_locales = {"search_docs": herramienta}
    with H.ThreadPoolExecutor(max_workers=1) as pool:
        monkeypatch.setattr(H, "_POOL", pool)
        try:
            resultado = H.ejecutar(recursos_minimos, CTX, "search_docs",
                                   {"query": consulta, "version": "2026-1", "top_k": 3},
                                   {"search_docs"}, timeout=0.05)
        finally:
            liberar.set()
    assert resultado.ok and resultado.intentos == 1 and llamadas == [1]
    contenido = resultado.contenido
    assert contenido["degradado"] and contenido["metodo_recuperacion"] == "bm25_por_timeout"
    assert contenido["evidencia_suficiente"] is suficiente
    por_id = {c["chunk_id"]: c for c in recursos_minimos.chunks}
    assert len(contenido["fragmentos"]) <= 3
    assert all(f["version"] == "2026-1" and f["tipo"] == "manual"
               and "N1" in por_id[f["chunk_id"]]["roles_permitidos"] for f in contenido["fragmentos"])
    if suficiente:
        assert contenido["fragmentos"] and por_id[contenido["fragmentos"][0]["chunk_id"]]["seccion"] == "3.2"


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


@pytest.mark.parametrize("codigo", ["autenticacion", "cuota", "configuracion"])
def test_error_permanente_del_modelo_no_se_reintenta(recursos_minimos, falsa, codigo):
    llamadas = []

    def falla(recursos, contexto, entrada):
        llamadas.append(1)
        raise ErrorModelo(codigo)

    falsa(falla)
    r = H.ejecutar(recursos_minimos, CTX, "falsa", {"text": "x"}, {"falsa"})
    assert not r.ok and r.intentos == 1 and llamadas == [1] and codigo in r.error


def test_error_transitorio_del_modelo_conserva_el_reintento(recursos_minimos, falsa):
    llamadas = []

    def inestable(recursos, contexto, entrada):
        llamadas.append(1)
        if len(llamadas) == 1:
            raise ErrorModelo("transporte", transitorio=True)
        return {"ok": True}

    falsa(inestable)
    r = H.ejecutar(recursos_minimos, CTX, "falsa", {"text": "x"}, {"falsa"})
    assert r.ok and r.intentos == 2


def test_classify_espera_sin_pool_ni_timeout_de_herramienta(recursos_minimos, monkeypatch):
    llamadas = []

    def clasificar(recursos, contexto, entrada):
        llamadas.append(1)
        time.sleep(0.02)
        return {"categoria": "RED"}

    def no_enviar_al_pool(*args, **kwargs):
        raise AssertionError("classify debe esperar directamente al cliente del modelo")

    monkeypatch.setitem(H.HERRAMIENTAS, "classify", dataclasses.replace(H.HERRAMIENTAS["classify"], funcion=clasificar))
    monkeypatch.setattr(H._POOL, "submit", no_enviar_al_pool)
    r = H.ejecutar(recursos_minimos, CTX, "classify", {"text": "vpn"}, {"classify"}, timeout=0.001)
    assert r.ok and r.intentos == 1 and llamadas == [1] and r.contenido == {"categoria": "RED"}


@pytest.mark.parametrize("codigo", ["transporte", "timeout"])
def test_classify_no_repite_inferencias_ante_error_transitorio(recursos_minimos, monkeypatch, codigo):
    llamadas = []

    def clasificar(recursos, contexto, entrada):
        llamadas.append(1)
        raise ErrorModelo(codigo, transitorio=True)

    monkeypatch.setitem(H.HERRAMIENTAS, "classify", dataclasses.replace(H.HERRAMIENTAS["classify"], funcion=clasificar))
    r = H.ejecutar(recursos_minimos, CTX, "classify", {"text": "vpn"}, {"classify"})
    assert not r.ok and r.intentos == 1 and llamadas == [1] and codigo in r.error


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

    def generar(self, **kwargs):
        voto = self.respuestas.pop(0)
        return SimpleNamespace(parsed_output=voto, stop_reason="refusal" if voto is None else "end_turn",
                               proveedor="codex_subscription", modo_autenticacion="chatgpt",
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=20, cache_read_input_tokens=400))


def voto(categoria, prioridad="MEDIA", tipo="procedimiento"):
    return Clasificacion(categoria=categoria, prioridad=prioridad, tipo=tipo)


def test_votacion_unanime_no_va_a_revision():
    r = ClasificadorLLM(ClienteVotos([voto("RED")] * 5)).clasificar("La VPN no conecta")
    assert r.categoria == "RED" and r.confianza == {"categoria": 1.0, "prioridad": 1.0, "tipo": 1.0}
    assert not r.needs_human_review
    assert r.tokens_entrada == 5000 and r.tokens_salida == 100
    assert r.costo_api_usd == 0 and r.proveedor == "codex_subscription"


def test_voto_discrepante_o_rechazo_va_a_revision():
    r = ClasificadorLLM(ClienteVotos([voto("RED")] * 3 + [voto("ACCESO"), None])).clasificar("La VPN no conecta")
    assert r.categoria == "RED" and r.confianza["categoria"] == 0.6 and r.needs_human_review
    assert r.corridas_validas == 4  # el rechazo cuenta en contra de la confianza


def test_error_del_primer_voto_impide_iniciar_los_restantes():
    llamadas = []

    class ClienteInterrumpido:
        def generar(self, **kwargs):
            llamadas.append(kwargs)
            raise ErrorModelo("transporte", transitorio=True)

    clasificador = ClasificadorLLM(ClienteInterrumpido())
    assert clasificador.corridas == 5
    with pytest.raises(ErrorModelo):
        clasificador.clasificar("La VPN no conecta")
    assert len(llamadas) == 1


def test_cada_voto_usa_un_juego_de_ejemplos_distinto():
    c = ClasificadorLLM(ClienteVotos([]))
    assert len(set(c.sistemas)) == c.corridas


def test_el_clasificador_ve_el_texto_enmascarado():
    cliente = ClienteVotos([voto("ACCESO")] * 5)
    vistos = []
    original = cliente.generar
    cliente.generar = lambda **k: vistos.append(k["mensajes"][0]["content"]) or original(**k)
    ClasificadorLLM(cliente).clasificar("Olvidé la clave, mi correo es ana@correo.example")
    assert all("ana@correo.example" not in v and "[EMAIL_REDACTED]" in v for v in vistos)


# ---------------------------------------------------------------- Con la base de datos

@pytest.fixture(scope="module")
def recursos_bd(chunks):
    cierres = ExitStack()
    try:
        from tickets_rag import acciones, historial, vectores
        from tickets_rag.recuperacion import Configuracion, RecuperadorHibrido

        conexion = vectores.conectar()
        cierres.callback(conexion.close)
        lectura = historial.conectar_lectura()
        cierres.callback(lectura.close)
        acciones_bd = acciones.conectar_acciones()
        cierres.callback(acciones_bd.close)
        bm25 = H.IndiceBM25(chunks)
        recursos = H.Recursos(
            chunks=chunks, bm25=bm25,
            procedimientos=RecuperadorHibrido(chunks, Configuracion(tipos=["manual", "articulo"]), conexion=conexion, bm25=bm25),
            casos=RecuperadorHibrido(chunks, Configuracion(tipos=["ticket"]), conexion=conexion, bm25=bm25),
            conexion_vectores=conexion,
            conexion_lectura=lectura,
            conexion_acciones=acciones_bd,
        )
    except Exception:
        cierres.close()
        pytest.skip("Base no disponible: docker compose up -d y scripts/preparar_bd.py")

    # Solo en esta fixture de integración: observar Future sin cambiar funciones, plazos,
    # permisos o resultados. Un timeout no detiene el trabajo nativo del pool.
    futuros, candado = set(), threading.Lock()
    enviar_original = H._POOL.submit
    def descartar(futuro):
        with candado:
            futuros.discard(futuro)
    def enviar(*args, **kwargs):
        futuro = enviar_original(*args, **kwargs)
        with candado:
            futuros.add(futuro)
        futuro.add_done_callback(descartar)
        return futuro
    def pendientes():
        with candado:
            return [f for f in futuros if not f.done()]
    recursos._futuros_integracion_pendientes = pendientes
    H._POOL.submit = enviar
    ocupados = []
    try:
        yield recursos
    finally:
        try:
            activos = pendientes()
            if activos:
                _, ocupados = wait(activos, timeout=2 * H.config.TIMEOUT_HERRAMIENTA_S)
            if not ocupados:
                conexion.execute("DELETE FROM solicitudes_accion WHERE ticket_id = %s", (CTX.ticket_id,))
                conexion.execute("DELETE FROM escalamientos WHERE ticket_id = %s", (CTX.ticket_id,))
        finally:
            H._POOL.submit = enviar_original
            cierres.close()
        if ocupados:
            pytest.exit("Integración incompleta: sigue activo un worker tras el timeout; no se inician más pruebas con GPU.", returncode=2)


@pytest.fixture(autouse=True)
def _no_solapar_integracion_pendiente(request):
    if "recursos_bd" in request.fixturenames:
        recursos = request.getfixturevalue("recursos_bd")
        if recursos._futuros_integracion_pendientes():
            pytest.exit("Integración incompleta: un test anterior dejó un worker activo; no se inicia otra recuperación.", returncode=2)


@pytest.fixture(scope="module")
def recursos_busqueda_bd(recursos_bd):
    # La recuperación se mide con los pesos cargados, igual que en producción.
    recursos_bd.calentar()
    return recursos_bd


def test_search_docs_devuelve_citas_y_respeta_el_rol(recursos_busqueda_bd):
    recursos_bd = recursos_busqueda_bd
    r = H.ejecutar(recursos_bd, CTX, "search_docs", {"query": "¿Cómo se restablece el MFA de un usuario?"}, TODAS, timeout=60)
    assert r.ok and r.contenido["fragmentos"] and r.contenido["evidencia_suficiente"]
    roles = {c["chunk_id"]: c["roles_permitidos"] for c in recursos_bd.chunks}
    assert all("N1" in roles[f["chunk_id"]] for f in r.contenido["fragmentos"])


def test_sin_base_vectorial_sigue_con_bm25_y_lo_marca(recursos_busqueda_bd, chunks):
    from tickets_rag import vectores
    from tickets_rag.recuperacion import Configuracion, RecuperadorHibrido

    caida = vectores.conectar()
    caida.close()
    bm25 = recursos_busqueda_bd.bm25
    roto = H.Recursos(chunks=chunks, bm25=bm25,
                      procedimientos=RecuperadorHibrido(chunks, Configuracion(tipos=["manual", "articulo"]), conexion=caida, bm25=bm25))
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
    r = H.ejecutar(recursos_bd, CTX, "escalate", {"causa": "pasos_agotados", "motivo": "El usuario ya aplicó los pasos", "fuentes": ["F9-c999"]}, TODAS)
    assert not r.ok and "no existen" in r.error
    fuente = recursos_bd.chunks[0]["chunk_id"]
    r = H.ejecutar(recursos_bd, CTX, "escalate", {"causa": "pasos_agotados", "motivo": "El usuario ya aplicó los pasos", "fuentes": [fuente]}, TODAS)
    assert r.ok and r.contenido["escalado"]
