import re

from tickets_rag import config
from tickets_rag.ingesta import (
    Seccion,
    Unidad,
    cargar_chunks,
    cargar_manifiesto,
    contar_tokens,
    estructurar,
    limpiar_pagina,
    secciones_modificadas,
    segmentar,
    sha256,
)


def test_limpieza_quita_encabezado_y_pie():
    pagina = (
        "Corporación Valcora · Manual de Mesa de Ayuda de TI · Versión 2026-2\n"
        "2.1 Restablecimiento de contraseña\n"
        "                          Página 4"
    )
    assert [t for _, t in limpiar_pagina(pagina)] == ["2.1 Restablecimiento de contraseña"]


def test_un_paso_que_cruza_de_pagina_sigue_siendo_un_solo_paso():
    pagina1 = limpiar_pagina("Capítulo 2: Accesos\n2.1 Contraseña\n   1. Primera parte del paso\n   que sigue")
    pagina2 = limpiar_pagina("   en la otra página.\n   2. Segundo paso.")
    seccion = estructurar([pagina1, pagina2])[0]
    assert [u.texto for u in seccion.unidades] == [
        "1. Primera parte del paso que sigue en la otra página.",
        "2. Segundo paso.",
    ]
    assert seccion.unidades[0].pagina == 1


def test_etiqueta_n2_marca_la_seccion_como_restringida():
    lineas = limpiar_pagina("Capítulo 2: Accesos\n2.4 MFA\nUso exclusivo: técnicos N2\n   1. Verifique.")
    assert estructurar([lineas])[0].restringida


def _seccion_larga() -> Seccion:
    pasos = [
        Unidad("paso", f"{i}. " + "Revise la configuración del equipo y anote el resultado en el ticket. " * 4, 1)
        for i in range(1, 16)
    ]
    return Seccion(id="9.9", titulo="Procedimiento largo", capitulo="Capítulo 9: Pruebas", pagina=1, unidades=pasos)


def test_segmentacion_respeta_el_maximo_y_no_parte_pasos():
    seccion = _seccion_larga()
    chunks = segmentar(seccion)
    assert len(chunks) > 1
    for texto, unidades in chunks:
        assert contar_tokens(texto) <= config.MAX_TOKENS_CHUNK
        for u in unidades:
            assert u.texto in texto  # cada paso entra completo
    cubiertos = {u.texto for _, unidades in chunks for u in unidades}
    assert cubiertos == {u.texto for u in seccion.unidades}


def test_solapamiento_repite_solo_pasos_completos_y_cortos():
    chunks = segmentar(_seccion_larga())
    for (_, anterior), (_, siguiente) in zip(chunks, chunks[1:]):
        repetidos = [u for u in siguiente if u in anterior]
        assert sum(contar_tokens(u.texto) + 1 for u in repetidos) <= config.SOLAPAMIENTO_TOKENS


def test_todos_los_pasos_de_f1_quedan_completos_en_su_chunk():
    """Cada paso del Markdown fuente aparece entero en el chunk de su sección, en ambas versiones."""
    fuente = re.sub(r"<!--.*?-->", "", (config.DATOS / "f1_manual" / "manual_mesa_ayuda.md").read_text(encoding="utf-8"), flags=re.S)
    chunks = cargar_chunks()
    for version in ("2026-1", "2026-2"):
        por_seccion = {c["seccion"]: " ".join(c["text"].split()) for c in chunks if c["doc_id"] == f"F1-{version}"}
        activo, seccion = True, None
        for linea in (l.strip() for l in fuente.splitlines()):
            if linea == ":::":
                activo = True
            elif m := re.match(r"^:::\s*(\S+)$", linea):
                activo = m.group(1) == version
            elif activo and (m := re.match(r"^### (\d+\.\d+) ", linea)):
                seccion = m.group(1)
            elif activo and seccion and re.match(r"^\d+\. ", linea):
                assert linea in por_seccion[seccion], (version, seccion, linea)


def test_solo_cuentan_como_modificados_los_procedimientos_que_cambiaron():
    assert secciones_modificadas(cargar_chunks()) == {"2.1", "2.2", "3.2", "5.2", "8.3"}


def test_tickets_de_prueba_no_entran_al_indice():
    ids = {c["seccion"] for c in cargar_chunks() if c["doc_type"] == "ticket"}
    lineas = (config.DATOS / "f3_tickets" / "tickets.jsonl").read_text(encoding="utf-8").splitlines()
    import json
    prueba = {json.loads(l)["ticket_id"] for l in lineas if json.loads(l)["particion"] == "prueba"}
    assert ids and not ids & prueba


def test_manifiesto_coincide_con_los_documentos():
    for doc in cargar_manifiesto():
        if doc.en_indice:
            assert sha256(config.RAIZ / doc.ruta) == doc.sha256


def test_chunks_traen_los_metadatos_minimos():
    obligatorios = {"text", "source", "page", "chunk_id", "version", "hash", "roles_permitidos", "vigente", "unidad"}
    inicio = {"manual": r"^\d+\.\d+ ", "articulo": r"^.+\n\d+\.\d+ ", "ticket": r"^Ticket TCK-2026-\d{5} · "}
    for chunk in cargar_chunks():
        assert obligatorios <= chunk.keys()
        assert re.match(inicio[chunk["doc_type"]], chunk["text"]), chunk["chunk_id"]
