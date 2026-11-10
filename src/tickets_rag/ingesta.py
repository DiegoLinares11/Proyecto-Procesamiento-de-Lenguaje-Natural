"""Pipeline de ingesta en seis fases (sección 5.3 del enunciado).

1. Carga: lee el manifiesto y verifica el hash SHA-256 de cada documento.
2. Extracción: texto de cada página del PDF, conservando la sangría; los tickets salen del JSONL.
3. Limpieza: quita encabezados y pies de página, normaliza Unicode y enmascara datos personales.
4. Segmentación: un chunk por procedimiento o sección, de máximo 450 tokens de BGE-M3, sin partir
   pasos; cada ticket resuelto es un solo chunk.
5. Metadatos: fuente, página, versión, vigencia, roles permitidos, unidad y hash en cada chunk.
6. Indexación: escribe los chunks en indices/; BM25 y pgvector se arman a partir de ellos.

Fuentes: F1 (manual, PDF), F2 (artículos de Microsoft, PDF) y F3 (tickets, JSONL).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pypdf import PdfReader
from tokenizers import Tokenizer

from tickets_rag import config
from tickets_rag.pii import enmascarar

ETIQUETA_N2 = "Uso exclusivo: técnicos N2"
RE_ENCABEZADO = re.compile(
    r"^(.+ · Manual de Mesa de Ayuda de TI · Versión \d{4}-\d"
    r"|Microsoft SupportArticles-docs \(CC BY 4\.0\) · commit [0-9a-f]{7})$"
)
RE_PIE = re.compile(r"^Página \d+$")
RE_CAPITULO = re.compile(r"^(?:Capítulo|Artículo) (\d+): .+$")
RE_PROCEDIMIENTO = re.compile(r"^(\d+\.\d+) (\S.*)$")
RE_PASO = re.compile(r"^\d+\. ")
RE_ORACION = re.compile(r"(?<=[.!?»])\s+")


class Documento(BaseModel):
    id: str
    ruta: str
    fuente: str
    formato: str
    propietario: str
    permiso: str
    licencia: str | None = None
    sensibilidad: str
    actualizacion: str
    version: str
    fecha_version: str
    vigente: bool
    idioma: str
    doc_type: str
    roles_por_defecto: list[str]
    en_indice: bool
    sha256: str | None = None
    indice_articulos: str | None = None


@dataclass
class Unidad:
    tipo: str  # "paso" o "parrafo"
    texto: str
    pagina: int


@dataclass
class Seccion:
    id: str
    titulo: str
    capitulo: str
    pagina: int
    restringida: bool = False
    unidades: list[Unidad] = field(default_factory=list)
    pasos_partidos: int = 0

    @property
    def capitulo_num(self) -> int:
        return int(self.id.split(".")[0])


# ---------------------------------------------------------------- 1. Carga

def cargar_manifiesto(ruta: Path = config.MANIFIESTO) -> list[Documento]:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return [Documento(**d) for d in datos["documentos"]]


def sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def verificar_hash(doc: Documento) -> None:
    """Si un documento cambió sin actualizar el manifiesto, la ingesta se detiene."""
    actual = sha256(config.RAIZ / doc.ruta)
    if actual != doc.sha256:
        raise ValueError(
            f"{doc.id}: el hash no coincide con el manifiesto. Si el cambio es intencional, "
            "corre scripts/ingestar.py --actualizar-hashes."
        )


# ---------------------------------------------------------------- 2. Extracción

def _lineas_con_posicion(pagina) -> list[tuple[float, float, str]]:
    """(y, x, texto) de cada línea, con la posición real en puntos que da el visitante de pypdf."""
    piezas: dict[float, list[tuple[float, str]]] = {}

    def visitante(texto, cm, tm, _fuente, _tamano):
        if texto and texto.strip():
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            piezas.setdefault(round(y, 1), []).append((x, texto))

    pagina.extract_text(visitor_text=visitante)
    lineas = []
    for y in sorted(piezas, reverse=True):
        partes = sorted(piezas[y])
        lineas.append((y, partes[0][0], "".join(t for _, t in partes)))
    return lineas


def extraer_paginas(ruta: Path) -> list[str]:
    """Cada página como texto: las líneas con sangría llevan cuatro espacios al inicio y los
    párrafos se separan con una línea vacía.

    La sangría y los espacios entre párrafos salen de la posición real de cada línea. El modo
    layout de pypdf redondea las posiciones a caracteres y en algunas páginas pierde la sangría
    de los pasos.
    """
    paginas = [_lineas_con_posicion(p) for p in PdfReader(ruta).pages]
    xs = [x for lineas in paginas for _, x, _ in lineas]
    margen = min(xs) if xs else 0.0
    salida = []
    for lineas in paginas:
        saltos = [a[0] - b[0] for a, b in zip(lineas, lineas[1:])]
        interlineado = sorted(saltos)[len(saltos) // 2] if saltos else 0.0
        texto = []
        for i, (_, x, contenido) in enumerate(lineas):
            if i and saltos[i - 1] > interlineado * 1.25:
                texto.append("")
            texto.append(("    " if x - margen > 2 else "") + contenido)
        salida.append("\n".join(texto))
    return salida


# ---------------------------------------------------------------- 3. Limpieza

def limpiar_pagina(texto: str) -> list[tuple[int, str]]:
    """Devuelve (sangría, texto) por línea, sin encabezado ni pie. Una línea vacía es ''.

    Se quitan las líneas vacías del inicio y del final de la página para que un párrafo que
    sigue en la página siguiente no se corte en dos.
    """
    lineas = []
    for linea in texto.splitlines():
        linea = unicodedata.normalize("NFC", linea.replace("\xa0", " ")).rstrip()
        limpia = re.sub(r" {2,}", " ", linea.strip())
        if RE_ENCABEZADO.match(limpia) or RE_PIE.match(limpia):
            continue
        sangria = len(linea) - len(linea.lstrip(" "))
        lineas.append((sangria if limpia else 0, limpia))
    while lineas and not lineas[0][1]:
        lineas.pop(0)
    while lineas and not lineas[-1][1]:
        lineas.pop()
    return lineas


def estructurar(paginas: list[list[tuple[int, str]]]) -> list[Seccion]:
    """Reconstruye secciones, pasos y párrafos a partir de las líneas limpias.

    Un paso empieza con «N. » y tiene sangría; sus líneas siguientes también la tienen, aunque
    pase a otra página. Un párrafo no tiene sangría y termina en una línea vacía. Si un título
    ocupa dos renglones, el segundo empieza en minúscula y se une al título.
    """
    secciones: list[Seccion] = []
    capitulo, numero_capitulo = "", ""
    actual: Seccion | None = None
    abierta: Unidad | None = None
    tras_titulo = False

    for numero, lineas in enumerate(paginas, start=1):
        # Un párrafo que termina justo al final de la página no continúa en la siguiente.
        if lineas and abierta is not None and abierta.tipo == "parrafo":
            if abierta.texto.rstrip().endswith((".", ":", "!", "?", "»", ")")) and not lineas[0][1][:1].islower():
                abierta = None
        for sangria, texto in lineas:
            indentada = sangria >= 2
            if not texto:
                if abierta is not None and abierta.tipo == "parrafo":
                    abierta = None
                tras_titulo = False
                continue
            if not indentada and (m := RE_CAPITULO.match(texto)):
                capitulo, numero_capitulo, abierta, tras_titulo = texto, m.group(1), None, False
                continue
            # Una sección solo cuenta si su número es del capítulo en curso: «802.11 frames...»
            # es texto, no la sección 802.11.
            m = RE_PROCEDIMIENTO.match(texto) if not indentada else None
            if m and m.group(1).split(".")[0] == numero_capitulo:
                actual = Seccion(id=m.group(1), titulo=m.group(2), capitulo=capitulo, pagina=numero)
                secciones.append(actual)
                abierta, tras_titulo = None, True
                continue
            if actual is None:  # portada y texto antes de la primera sección
                continue
            if tras_titulo and not indentada and texto[:1].islower():
                actual.titulo += " " + texto
                continue
            tras_titulo = False
            if texto == ETIQUETA_N2:
                actual.restringida, abierta = True, None
                continue
            if indentada and RE_PASO.match(texto):
                abierta = Unidad("paso", texto, numero)
                actual.unidades.append(abierta)
                continue
            continua_paso = abierta is not None and abierta.tipo == "paso" and indentada
            continua_parrafo = abierta is not None and abierta.tipo == "parrafo" and not indentada
            if continua_paso or continua_parrafo:
                abierta.texto += " " + texto
                continue
            abierta = Unidad("parrafo", texto, numero)
            actual.unidades.append(abierta)
    return secciones


# ---------------------------------------------------------------- 4. Segmentación

@lru_cache(maxsize=1)
def _tokenizer() -> Tokenizer:
    return Tokenizer.from_pretrained(config.TOKENIZER_EMBEDDINGS)


def contar_tokens(texto: str) -> int:
    return len(_tokenizer().encode(texto, add_special_tokens=False).ids)


def encabezado(seccion: Seccion) -> str:
    texto = f"{seccion.id} {seccion.titulo}"
    return f"{texto}\n{ETIQUETA_N2}" if seccion.restringida else texto


def _partir_por_palabras(texto: str, limite: int) -> list[str]:
    """Último recurso para una oración o fila de tabla enorme: ventanas de palabras que caben."""
    partes, actual = [], []
    for palabra in texto.split():
        if actual and contar_tokens(" ".join([*actual, palabra])) > limite:
            partes.append(" ".join(actual))
            actual = []
        actual.append(palabra)
    if actual:
        partes.append(" ".join(actual))
    return partes


def _unidades_que_caben(seccion: Seccion, limite: int, partir_pasos: bool) -> list[Unidad]:
    """Un párrafo demasiado largo se parte por oraciones, y una oración enorme por palabras.

    En el manual propio (F1) un paso nunca se parte: si no cabe, es un error de la fuente. En
    documentos externos (F2) se permite como último recurso y se cuenta en el resumen.
    """
    salida = []
    for u in seccion.unidades:
        if contar_tokens(u.texto) <= limite:
            salida.append(u)
            continue
        if u.tipo == "paso":
            if not partir_pasos:
                raise ValueError(f"El paso de {seccion.id} supera {limite} tokens; divídelo en la fuente.")
            seccion.pasos_partidos += 1
        for oracion in RE_ORACION.split(u.texto):
            piezas = [oracion] if contar_tokens(oracion) <= limite else _partir_por_palabras(oracion, limite)
            salida.extend(Unidad("parrafo", p, u.pagina) for p in piezas)
    return salida


def segmentar(seccion: Seccion, prefijo: str = "", partir_pasos: bool = False) -> list[tuple[str, list[Unidad]]]:
    """Agrupa las unidades en chunks. Repite al inicio del siguiente las unidades completas
    que suman hasta SOLAPAMIENTO_TOKENS, para no perder el contexto en el corte."""
    cabecera = prefijo + encabezado(seccion)
    presupuesto = config.MAX_TOKENS_CHUNK - contar_tokens(cabecera) - 1
    # Cada unidad suma 1 token por el salto de línea que la separa.
    unidades = _unidades_que_caben(seccion, presupuesto - 1, partir_pasos)
    tokens = [contar_tokens(u.texto) + 1 for u in unidades]

    grupos: list[list[int]] = []
    inicio, arrastre = 0, []
    while inicio < len(unidades):
        grupo, usado = list(arrastre), sum(tokens[k] for k in arrastre)
        j = inicio
        while j < len(unidades) and usado + tokens[j] <= presupuesto:
            grupo.append(j)
            usado += tokens[j]
            j += 1
        if j == inicio:  # el arrastre no deja espacio: se intenta sin él
            if not arrastre:
                raise RuntimeError(f"Una unidad de {seccion.id} no cabe en el chunk.")  # no debería ocurrir
            arrastre = []
            continue
        grupos.append(grupo)
        arrastre, acumulado = [], 0
        for k in range(j - 1, inicio - 1, -1):
            if acumulado + tokens[k] > config.SOLAPAMIENTO_TOKENS:
                break
            arrastre.insert(0, k)
            acumulado += tokens[k]
        inicio = j

    if not grupos:  # sección sin cuerpo: queda solo el título
        return [(cabecera, [])]
    return [(cabecera + "\n" + "\n".join(unidades[k].texto for k in g), [unidades[k] for k in g]) for g in grupos]


# ---------------------------------------------------------------- 5. Metadatos

def _base(doc: Documento) -> dict:
    return {
        "source": Path(doc.ruta).name,
        "hash": doc.sha256,
        "doc_id": doc.id,
        "doc_type": doc.doc_type,
        "idioma": doc.idioma,
        "fecha_version": doc.fecha_version,
    }


def procesar_pdf(doc: Documento) -> tuple[list[dict], dict]:
    paginas = [limpiar_pagina(t) for t in extraer_paginas(config.RAIZ / doc.ruta)]
    secciones = estructurar(paginas)
    pii_total: Counter[str] = Counter()
    for s in secciones:
        for u in s.unidades:
            u.texto, encontrados = enmascarar(u.texto)
            pii_total.update(encontrados)

    articulos = {}
    if doc.indice_articulos:
        datos = json.loads((config.RAIZ / doc.indice_articulos).read_text(encoding="utf-8"))
        articulos = {a["articulo"]: a for a in datos["articulos"]}

    chunks = []
    for s in secciones:
        roles = ["N2"] if s.restringida else list(doc.roles_por_defecto)
        articulo = articulos.get(s.capitulo_num)
        # En F2, el título del artículo va al inicio del chunk para que cada sección tenga contexto.
        prefijo = f"{articulo['titulo']}\n" if articulo else ""
        for texto, unidades in segmentar(s, prefijo, partir_pasos=doc.doc_type != "manual"):
            paginas_chunk = [u.pagina for u in unidades] or [s.pagina]
            chunk = {
                **_base(doc),
                "chunk_id": f"{doc.id}-c{len(chunks) + 1:03d}",
                "text": texto,
                "page": min(paginas_chunk),
                "page_end": max(paginas_chunk),
                "version": doc.version,
                "seccion": s.id,
                "titulo_seccion": s.titulo,
                "capitulo": s.capitulo,
                "roles_permitidos": roles,
                "vigente": doc.vigente,
                "unidad": f"{doc.id}:{s.id}",
                "tokens": contar_tokens(texto),
            }
            if articulo:
                chunk.update(unidad=f"{doc.id}:{articulo['slug']}", capitulo=f"Artículo {articulo['articulo']}: {articulo['titulo']}",
                             url=articulo["url"], categoria=articulo["categoria"])
            chunks.append(chunk)
    resumen = {
        "paginas": len(paginas),
        "secciones": len(secciones),
        "secciones_restringidas": sorted(s.id for s in secciones if s.restringida),
        "chunks": len(chunks),
        "tokens_max": max(c["tokens"] for c in chunks),
        "tokens_promedio": round(sum(c["tokens"] for c in chunks) / len(chunks), 1),
        "pasos_partidos": sum(s.pasos_partidos for s in secciones),
        "pii_enmascarada": dict(sorted(pii_total.items())),
        "sha256": doc.sha256,
    }
    return chunks, resumen


def secciones_modificadas(chunks: list[dict]) -> set[str]:
    """Procedimientos del manual cuyo texto cambió entre la versión vigente y las anteriores."""
    def normal(texto: str) -> str:  # los saltos de línea dependen de cómo cayó el texto en la página
        return " ".join(texto.split())

    manuales = [c for c in chunks if c["doc_type"] == "manual"]
    vigente = {c["seccion"]: normal(c["text"]) for c in manuales if c["vigente"]}
    return {c["seccion"] for c in manuales if not c["vigente"] and vigente.get(c["seccion"]) != normal(c["text"])}


def procesar_tickets(doc: Documento, modificadas: set[str], version_vigente: str) -> tuple[list[dict], dict]:
    """Cada ticket del índice es un chunk. Los de prueba quedan fuera: sirven para evaluar.

    Un ticket deja de estar vigente si se resolvió con una versión anterior de un procedimiento
    que después cambió, porque su solución ya no aplica.
    """
    pii_total: Counter[str] = Counter()
    chunks = []
    lineas = (config.RAIZ / doc.ruta).read_text(encoding="utf-8").splitlines()
    for numero, linea in enumerate(lineas, start=1):
        t = json.loads(linea)
        if t["particion"] != "indice":
            continue
        partes = []
        for campo in ("resumen", "texto", "diagnostico", "solucion"):
            texto, encontrados = enmascarar(t[campo])
            pii_total.update(encontrados)
            partes.append(texto)
        texto = (f"Ticket {t['ticket_id']} · {partes[0]}\nReporte: {partes[1]}\n"
                 f"Diagnóstico: {partes[2]}\nSolución: {partes[3]}")
        obsoleto = t["version_manual"] != version_vigente and t["seccion"] in modificadas
        chunks.append({
            **_base(doc),
            "chunk_id": f"F3-{t['ticket_id']}",
            "text": texto,
            "page": numero,  # en F3 la «página» es el número de registro del JSONL
            "page_end": numero,
            "version": t["version_manual"],
            "seccion": t["ticket_id"],
            "titulo_seccion": partes[0],
            "capitulo": "Tickets resueltos",
            "roles_permitidos": list(doc.roles_por_defecto),
            "vigente": not obsoleto,
            "unidad": f"F3:{t['ticket_id']}",
            "seccion_manual": t["seccion"],
            "categoria": t["categoria"],
            "prioridad": t["prioridad"],
            "tokens": contar_tokens(texto),
        })
    resumen = {
        "tickets_indexados": len(chunks),
        "no_vigentes": sum(not c["vigente"] for c in chunks),
        "secciones_modificadas": sorted(modificadas),
        "tokens_max": max(c["tokens"] for c in chunks),
        "tokens_promedio": round(sum(c["tokens"] for c in chunks) / len(chunks), 1),
        "pii_enmascarada": dict(sorted(pii_total.items())),
        "sha256": doc.sha256,
    }
    return chunks, resumen


# ---------------------------------------------------------------- 6. Indexación

def ingestar(manifiesto: Path = config.MANIFIESTO) -> dict:
    documentos = [d for d in cargar_manifiesto(manifiesto) if d.en_indice]
    for doc in documentos:
        verificar_hash(doc)
    todos, resumen = [], {}
    for doc in [d for d in documentos if d.formato.startswith("PDF")]:
        chunks, resumen[doc.id] = procesar_pdf(doc)
        todos.extend(chunks)
    modificadas = secciones_modificadas(todos)
    version_vigente = next(d.version for d in documentos if d.doc_type == "manual" and d.vigente)
    for doc in [d for d in documentos if d.doc_type == "ticket"]:
        chunks, resumen[doc.id] = procesar_tickets(doc, modificadas, version_vigente)
        todos.extend(chunks)

    config.INDICES.mkdir(exist_ok=True)
    with config.CHUNKS.open("w", encoding="utf-8", newline="\n") as f:
        for c in todos:
            f.write(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n")
    config.RESUMEN_INGESTA.write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return resumen


def cargar_chunks(ruta: Path = config.CHUNKS) -> list[dict]:
    if not ruta.exists():
        raise FileNotFoundError("No hay índice. Corre primero: uv run python scripts/ingestar.py")
    return [json.loads(linea) for linea in ruta.read_text(encoding="utf-8").splitlines() if linea]
