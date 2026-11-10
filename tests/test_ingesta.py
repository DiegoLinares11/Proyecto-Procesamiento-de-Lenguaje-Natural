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


def test_manifiesto_coincide_con_los_documentos():
    for doc in cargar_manifiesto():
        if doc.en_indice:
            assert sha256(config.RAIZ / doc.ruta) == doc.sha256


def test_chunks_traen_los_metadatos_minimos():
    obligatorios = {"text", "source", "page", "chunk_id", "version", "hash", "roles_permitidos", "vigente"}
    for chunk in cargar_chunks():
        assert obligatorios <= chunk.keys()
        assert re.match(r"^\d+\.\d+ ", chunk["text"])
