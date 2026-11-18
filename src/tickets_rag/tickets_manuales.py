"""Recepción de veinte tickets humanos reservados para evaluar categoría y prioridad.

Valida datos de autoría y duplicados exactos normalizados. Conserva las declaraciones legacy.
No demuestra autoría humana ni independencia semántica, no redacta textos y no llama
clasificadores, NER ni modelos remotos.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

from tickets_rag import config

CARPETA = config.EVALUACION / "tickets_manuales"
MANUALES = CARPETA / "congelado" / "tickets.jsonl"
CAMPOS_CSV = ("ticket_id", "texto", "categoria", "prioridad")
IDS = tuple(f"MAN-{i:02d}" for i in range(1, 21))
# Las mismas etiquetas de Clasificacion/F3, definidas por el manual 1.3 y 1.4.
CATEGORIAS = ("ACCESO", "CORREO", "EQUIPOS", "RED", "APLICACIONES", "OTRO")
PRIORIDADES = ("ALTA", "MEDIA", "BAJA")
DECLARACIONES = (
    "autoria_humana", "no_redacto_f3", "sin_ia_en_redaccion", "sin_copia_de_otros_conjuntos",
    "sin_datos_personales_reales", "reserva_exclusiva_evaluacion",
)
EXCLUSIONES = ("entrenamiento", "ejemplos_few_shot", "ajuste_prompt", "indice", "seleccion_variantes")
REFERENCIAS = {
    "f3": ("datos/f3_tickets/tickets.jsonl", "texto"),
    "desarrollo": ("evaluacion/validacion_dev.jsonl", "question"),
    "banco_oficial": ("evaluacion/banco.jsonl", "question"),
    "banco_borrador": ("evaluacion/banco_borrador.jsonl", "question"),
}
REFERENCIA_SINTETICOS = ("evaluacion/tickets_sinteticos/tickets.jsonl", "texto")
PROCEDENCIA_DATOS_AUTOR = {
    "tipo": "persona_independiente_f3_indicada",
    "registro": "nombre_y_fecha",
    "verificacion": "no_verificada",
}


class ErrorTicketsManuales(ValueError):
    """Mensajes sin textos, etiquetas libres ni nombres recibidos del archivo de entrada."""

    def __init__(self, errores):
        self.errores = tuple(errores)
        super().__init__("\n".join(self.errores))


def _sha(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def normalizar_texto(texto: str) -> str:
    return " ".join(unicodedata.normalize("NFC", texto).split()).casefold()


def validar_autoria(meta: dict) -> dict:
    errores = []
    campos = {"estado", "autor", "fecha_redaccion"}
    if not isinstance(meta, dict) or set(meta) not in (campos, campos | {"declaraciones"}):
        raise ErrorTicketsManuales(["Autoría: se requieren estado, autor y fecha_redaccion; las declaraciones sólo pertenecen al formato anterior."])
    if meta["estado"] != "declarado":
        errores.append("Autoría: sigue pendiente; complete los datos de la persona que escribió los textos.")
    autor = meta["autor"]
    if not isinstance(autor, str) or not autor.strip() or autor.strip().casefold() in {"pendiente", "por confirmar"}:
        errores.append("Autoría: falta identificar a la persona responsable de los veinte textos.")
    fecha = meta["fecha_redaccion"]
    try:
        parsed = date.fromisoformat(fecha)
        if parsed.isoformat() != fecha or parsed > date.today():
            raise ValueError
    except (ValueError, TypeError):
        errores.append("Autoría: fecha_redaccion debe ser una fecha real YYYY-MM-DD, sin fecha futura.")
    if "declaraciones" in meta:
        declaraciones = meta["declaraciones"]
        if not isinstance(declaraciones, dict) or set(declaraciones) != set(DECLARACIONES):
            errores.append("Autoría: faltan declaraciones requeridas del formato anterior o hay campos desconocidos.")
        elif any(declaraciones[d] is not True for d in DECLARACIONES):
            errores.append("Autoría: las seis declaraciones del formato anterior deben ser true booleano, incluida independencia de F3 y ausencia de IA.")
    if errores:
        raise ErrorTicketsManuales(errores)
    return {**meta, "autor": autor.strip()}


def leer_csv(datos: bytes) -> list[dict]:
    try:
        lector = csv.DictReader(io.StringIO(datos.decode("utf-8-sig"), newline=""))
        if lector.fieldnames is None or len(lector.fieldnames) != 4 or set(lector.fieldnames) != set(CAMPOS_CSV):
            raise ErrorTicketsManuales(["CSV: use exactamente las columnas ticket_id,texto,categoria,prioridad."])
        filas = list(lector)
    except (UnicodeError, csv.Error):
        raise ErrorTicketsManuales(["CSV: formato inválido; guarde como CSV UTF-8 con las cuatro columnas de la plantilla."]) from None
    if any(None in fila or any(v is None for v in fila.values()) for fila in filas):
        raise ErrorTicketsManuales(["CSV: hay filas con una cantidad incorrecta de columnas."])
    return filas


def cargar_referencias(raiz: Path = config.RAIZ, *, incluir_sinteticos: bool = False) -> tuple[dict[str, set[str]], list[dict]]:
    textos, fuentes, errores = {}, [], []
    referencias = dict(REFERENCIAS)
    if incluir_sinteticos and (raiz / REFERENCIA_SINTETICOS[0]).exists():
        referencias["sinteticos_ia"] = REFERENCIA_SINTETICOS
    for nombre, (relativa, campo) in referencias.items():
        ruta = raiz / relativa
        if not ruta.is_file():
            if nombre != "banco_borrador":
                errores.append(f"Referencias: falta {nombre}; no se puede congelar sin comprobar sus duplicados.")
            continue
        raw = ruta.read_bytes()
        try:
            filas = [json.loads(l) for l in raw.decode("utf-8").splitlines() if l.strip()]
            if not filas or any(not isinstance(f.get(campo), str) or not f[campo].strip() for f in filas):
                raise ValueError
        except (ValueError, UnicodeError, AttributeError):
            errores.append(f"Referencias: {nombre} no tiene registros válidos para contrastar textos.")
            continue
        textos[nombre] = {normalizar_texto(f[campo]) for f in filas}
        fuentes.append({"nombre": nombre, "ruta": relativa, "sha256": _sha(raw), "registros": len(filas)})
    # El manifiesto conserva la procedencia del resto del corpus, además del hash de F3.
    ruta = raiz / "datos/manifiesto.json"
    if not ruta.is_file():
        errores.append("Referencias: falta el manifiesto del corpus.")
    else:
        fuentes.append({"nombre": "manifiesto_corpus", "ruta": "datos/manifiesto.json", "sha256": _sha(ruta.read_bytes())})
    if errores:
        raise ErrorTicketsManuales(errores)
    return textos, fuentes


def validar_filas(filas: list[dict], referencias: dict[str, set[str]]) -> list[dict]:
    errores, salida, vistos, ids = [], [], {}, set()
    if len(filas) != 20:
        errores.append("CSV: se requieren exactamente veinte filas de tickets.")
    for n, fila in enumerate(filas, 1):
        if set(fila) != set(CAMPOS_CSV) or any(not isinstance(v, str) for v in fila.values()):
            errores.append(f"Fila {n}: estructura inválida.")
            continue
        f = {k: v.strip() for k, v in fila.items()}
        if f["ticket_id"] not in IDS or f["ticket_id"] in ids:
            errores.append(f"Fila {n}: identificador inválido o repetido; use MAN-01 a MAN-20 una vez cada uno.")
        ids.add(f["ticket_id"])
        clave = normalizar_texto(f["texto"])
        if not clave:
            errores.append(f"Fila {n}: falta el texto humano; una fila vacía no es un ticket.")
        elif clave in vistos:
            errores.append(f"Fila {n}: texto duplicado de la fila {vistos[clave]}.")
        else:
            vistos[clave] = n
        if f["categoria"] not in CATEGORIAS:
            errores.append(f"Fila {n}: categoría inválida.")
        if f["prioridad"] not in PRIORIDADES:
            errores.append(f"Fila {n}: prioridad inválida.")
        for nombre, existentes in referencias.items():
            if clave and clave in existentes:
                errores.append(f"Fila {n}: texto ya presente en {nombre}; no acredita un ticket independiente.")
        salida.append({**f, "particion": "manuales", "uso": "evaluacion_reservada", "procedencia": "humano_declarado"})
    if errores:
        raise ErrorTicketsManuales(errores)
    return salida


def balance(filas: list[dict]) -> dict:
    return {campo: {e: sum(f[campo] == e for f in filas) for e in etiquetas}
            for campo, etiquetas in (("categoria", CATEGORIAS), ("prioridad", PRIORIDADES))}


def preparar_manuales(csv_ruta: Path, autoria_ruta: Path, *, salida: Path | None = None,
                      raiz: Path = config.RAIZ) -> dict:
    """Valida sin escribir si salida=None; congela solo después de superar todos los controles."""
    try:
        csv_raw, meta_raw = csv_ruta.read_bytes(), autoria_ruta.read_bytes()
        meta = json.loads(meta_raw.decode("utf-8"))
    except (OSError, ValueError, UnicodeError):
        raise ErrorTicketsManuales(["Entrada: no se pudo leer el CSV o el JSON de autoría."]) from None
    autoria = validar_autoria(meta)
    referencias, fuentes = cargar_referencias(raiz, incluir_sinteticos=True)
    filas = validar_filas(leer_csv(csv_raw), referencias)
    distribucion = balance(filas)
    avisos = [f"Balance recomendado: faltan etiquetas de {c}; el anteproyecto no fija cuotas por clase."
              for c, cuenta in distribucion.items() if any(n == 0 for n in cuenta.values())]
    resumen = {"tickets": len(filas), "balance": distribucion, "avisos": avisos,
               "autoria": "declarada; no constituye prueba independiente", "congelado": salida is not None}
    if salida is None:
        return resumen
    if salida.exists():
        raise ErrorTicketsManuales(["Salida: ya existe; conserve el conjunto congelado o elija otra carpeta nueva."])
    datos = "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in filas).encode("utf-8")
    artefactos = {"tickets.jsonl": datos, "fuente.csv": csv_raw, "autoria.json": meta_raw}
    formato_legacy = "declaraciones" in autoria
    manifiesto = {"version": 1 if formato_legacy else 2, "estado": "congelado", "conjunto": "tickets_manuales", "tickets": 20,
                  "fecha_congelacion_utc": datetime.now(timezone.utc).isoformat(),
                  "autoria": autoria, "alcance_autoria": "declaración humana; no prueba ni certificación" if formato_legacy else
                  "datos de una persona independiente de F3 indicados por quien captura; no prueba ni certificación",
                  "uso_permitido": "evaluacion_final_clasificador", "excluido_de": list(EXCLUSIONES),
                  "duplicados": "NFC, espacios colapsados y casefold; no detecta paráfrasis ni demuestra independencia",
                  "balance": distribucion, "avisos": avisos,
                  "artefactos_sha256": {n: _sha(raw) for n, raw in artefactos.items()},
                  "fuentes_referencia": fuentes, "validador_sha256": _sha(Path(__file__).read_bytes())}
    if not formato_legacy:
        manifiesto["procedencia_declarada"] = dict(PROCEDENCIA_DATOS_AUTOR)
    salida.mkdir(parents=True)
    for nombre, raw in artefactos.items():
        (salida / nombre).write_bytes(raw)
    (salida / "manifiesto.json").write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return resumen


def cargar_manuales(ruta: Path = MANUALES, *, raiz: Path = config.RAIZ, verificar_fuentes: bool = True) -> list[dict]:
    """Carga un holdout congelado y verifica sus hashes antes de permitir su evaluación."""
    ruta = Path(ruta)
    try:
        manifiesto = json.loads((ruta.parent / "manifiesto.json").read_text(encoding="utf-8"))
        if ruta.name != "tickets.jsonl" or manifiesto["estado"] != "congelado" or manifiesto["tickets"] != 20:
            raise ValueError
        if manifiesto["uso_permitido"] != "evaluacion_final_clasificador" or set(manifiesto["excluido_de"]) != set(EXCLUSIONES):
            raise ValueError
        validar_autoria(manifiesto["autoria"])
        version = manifiesto.get("version")
        if type(version) is not int or version not in {1, 2}:
            raise ValueError
        if version == 2 and ("declaraciones" in manifiesto["autoria"]
                             or manifiesto.get("procedencia_declarada") != PROCEDENCIA_DATOS_AUTOR):
            raise ValueError
        if version == 1 and "declaraciones" not in manifiesto["autoria"]:
            raise ValueError
        if set(manifiesto["artefactos_sha256"]) != {"tickets.jsonl", "fuente.csv", "autoria.json"}:
            raise ValueError
        for nombre, esperado in manifiesto["artefactos_sha256"].items():
            if _sha((ruta.parent / nombre).read_bytes()) != esperado:
                raise ValueError
        if validar_autoria(json.loads((ruta.parent / "autoria.json").read_text(encoding="utf-8"))) != manifiesto["autoria"]:
            raise ValueError
        if verificar_fuentes:
            # Incorporar una referencia nueva no invalida congelaciones históricas.
            # Las nuevas capturas sí contrastan y fijan los sintéticos si existen.
            incluye_sinteticos = any(f["nombre"] == "sinteticos_ia" for f in manifiesto["fuentes_referencia"])
            _, fuentes = cargar_referencias(raiz, incluir_sinteticos=incluye_sinteticos)
            if fuentes != manifiesto["fuentes_referencia"]:
                raise ValueError
        filas = [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]
        if any(f.get("particion") != "manuales" or f.get("uso") != "evaluacion_reservada"
               or f.get("procedencia") != "humano_declarado" for f in filas):
            raise ValueError
        basicas = [{k: f[k] for k in CAMPOS_CSV} for f in filas]
        validar_filas(basicas, {})
        if validar_filas(leer_csv((ruta.parent / "fuente.csv").read_bytes()), {}) != filas:
            raise ValueError
        return filas
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise ErrorTicketsManuales(["Conjunto manual: falta congelación válida o cambiaron los artefactos, la autoría o el corpus de referencia."]) from None
