"""Pipeline de ingesta en seis fases (sección 5.3 del enunciado).

1. Carga: lee el manifiesto y verifica el hash SHA-256 de cada documento.
2. Extracción: texto de cada página del PDF, conservando la sangría.
3. Limpieza: quita encabezados y pies de página, normaliza Unicode y enmascara datos personales.
4. Segmentación: un chunk por procedimiento, de máximo 450 tokens de BGE-M3; nunca parte un paso.
5. Metadatos: fuente, página, versión, vigencia, roles permitidos y hash en cada chunk.
6. Indexación: escribe los chunks en indices/; el índice BM25 se arma al cargarlos.
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
RE_ENCABEZADO = re.compile(r"^.+ · Manual de Mesa de Ayuda de TI · Versión \d{4}-\d$")
RE_PIE = re.compile(r"^Página \d+$")
RE_CAPITULO = re.compile(r"^Capítulo \d+: .+$")
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

def extraer_paginas(ruta: Path) -> list[str]:
    return [p.extract_text(extraction_mode="layout") for p in PdfReader(ruta).pages]


# ---------------------------------------------------------------- 3. Limpieza

def limpiar_pagina(texto: str) -> list[tuple[int, str]]:
    """Devuelve (sangría, texto) por línea, sin encabezado ni pie. Una línea vacía es ''."""
    lineas = []
    for linea in texto.splitlines():
        linea = unicodedata.normalize("NFC", linea.replace("\xa0", " ")).rstrip()
        limpia = re.sub(r" {2,}", " ", linea.strip())
        if RE_ENCABEZADO.match(limpia) or RE_PIE.match(limpia):
            continue
        sangria = len(linea) - len(linea.lstrip(" "))
        lineas.append((sangria if limpia else 0, limpia))
    return lineas


def estructurar(paginas: list[list[tuple[int, str]]]) -> list[Seccion]:
    """Reconstruye procedimientos, pasos y párrafos a partir de las líneas limpias.

    Un paso empieza con «N. » y tiene sangría; sus líneas siguientes también la tienen, aunque
    pase a otra página. Un párrafo no tiene sangría y termina en una línea vacía.
    """
    secciones: list[Seccion] = []
    capitulo = ""
    actual: Seccion | None = None
    abierta: Unidad | None = None

    for numero, lineas in enumerate(paginas, start=1):
        for sangria, texto in lineas:
            indentada = sangria >= 2
            if not texto:
                if abierta is not None and abierta.tipo == "parrafo":
                    abierta = None
                continue
            if not indentada and RE_CAPITULO.match(texto):
                capitulo, abierta = texto, None
                continue
            if not indentada and (m := RE_PROCEDIMIENTO.match(texto)):
                actual = Seccion(id=m.group(1), titulo=m.group(2), capitulo=capitulo, pagina=numero)
                secciones.append(actual)
                abierta = None
                continue
            if actual is None:  # portada y texto antes del primer procedimiento
                continue
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


def _unidades_que_caben(seccion: Seccion, presupuesto: int) -> list[Unidad]:
    """Un párrafo demasiado largo se parte por oraciones; un paso nunca se parte."""
    salida = []
    for u in seccion.unidades:
        if contar_tokens(u.texto) <= presupuesto:
            salida.append(u)
        elif u.tipo == "paso":
            raise ValueError(f"El paso de {seccion.id} supera {presupuesto} tokens; divídelo en la fuente.")
        else:
            salida.extend(Unidad("parrafo", o, u.pagina) for o in RE_ORACION.split(u.texto))
    return salida


def segmentar(seccion: Seccion) -> list[tuple[str, list[Unidad]]]:
    """Agrupa las unidades en chunks. Repite al inicio del siguiente las unidades completas
    que suman hasta SOLAPAMIENTO_TOKENS, para no perder el contexto en el corte."""
    cabecera = encabezado(seccion)
    presupuesto = config.MAX_TOKENS_CHUNK - contar_tokens(cabecera) - 1
    unidades = _unidades_que_caben(seccion, presupuesto)
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

    if not grupos:  # procedimiento sin cuerpo: queda solo el título
        return [(cabecera, [])]
    return [(cabecera + "\n" + "\n".join(unidades[k].texto for k in g), [unidades[k] for k in g]) for g in grupos]


# ---------------------------------------------------------------- 5. Metadatos y 6. Indexación

def procesar_documento(doc: Documento) -> tuple[list[dict], dict]:
    paginas = [limpiar_pagina(t) for t in extraer_paginas(config.RAIZ / doc.ruta)]
    secciones = estructurar(paginas)
    pii_total: Counter[str] = Counter()
    for s in secciones:
        for u in s.unidades:
            u.texto, encontrados = enmascarar(u.texto)
            pii_total.update(encontrados)

    chunks = []
    for s in secciones:
        roles = ["N2"] if s.restringida else list(doc.roles_por_defecto)
        for texto, unidades in segmentar(s):
            paginas_chunk = [u.pagina for u in unidades] or [s.pagina]
            chunks.append({
                "chunk_id": f"{doc.id}-c{len(chunks) + 1:03d}",
                "text": texto,
                "source": Path(doc.ruta).name,
                "page": min(paginas_chunk),
                "page_end": max(paginas_chunk),
                "version": doc.version,
                "hash": doc.sha256,
                "doc_id": doc.id,
                "doc_type": doc.doc_type,
                "seccion": s.id,
                "titulo_seccion": s.titulo,
                "capitulo": s.capitulo,
                "roles_permitidos": roles,
                "vigente": doc.vigente,
                "fecha_version": doc.fecha_version,
                "idioma": doc.idioma,
                "tokens": contar_tokens(texto),
            })
    resumen = {
        "paginas": len(paginas),
        "secciones": len(secciones),
        "secciones_restringidas": sorted(s.id for s in secciones if s.restringida),
        "chunks": len(chunks),
        "tokens_max": max(c["tokens"] for c in chunks),
        "tokens_promedio": round(sum(c["tokens"] for c in chunks) / len(chunks), 1),
        "pii_enmascarada": dict(sorted(pii_total.items())),
        "sha256": doc.sha256,
    }
    return chunks, resumen


def ingestar(manifiesto: Path = config.MANIFIESTO) -> dict:
    documentos = [d for d in cargar_manifiesto(manifiesto) if d.en_indice]
    todos, resumen = [], {}
    for doc in documentos:
        verificar_hash(doc)
        chunks, resumen[doc.id] = procesar_documento(doc)
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
