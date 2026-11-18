"""PII local: regex de identificadores y Presidio/spaCy para personas en español e inglés.

Cada valor se reemplaza por su tipo, por ejemplo [EMAIL_REDACTED], para conservar el sentido
del texto sin el dato. Las detecciones se devuelven como conteos por tipo, nunca con el valor.

Los offsets siempre corresponden al texto original. No se descargan modelos ni se llama a servicios
externos al analizar: si el modelo local falta o falla, se retiene el texto con ErrorPII.
"""

from __future__ import annotations

import re
import threading
from collections import Counter
from dataclasses import dataclass

from tickets_rag.config import CORREOS_INSTITUCIONALES

RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Los límites excluyen letras, guiones y acentos graves, para no tomar direcciones de memoria
# de un volcado (fffff807`aa74f4c4) como datos personales.
# Tarjetas de 15 o 16 dígitos que empiezan como una red real (3 a 6); se confirman con Luhn
RE_TARJETA = re.compile(r"(?<![\w`-])[3-6](?:[ -]?\d){13,14}\d(?![\w`-])")
# DPI de Guatemala: 13 dígitos, a veces en grupos 4-5-4
RE_DPI = re.compile(r"(?<![\w`-])\d{4}[ -]?\d{5}[ -]?\d{4}(?![\w`-])")
# Teléfonos de Guatemala: 8 dígitos que empiezan con 2-7, con +502 opcional
RE_TELEFONO = re.compile(r"(?<![\w`-])(?:\+?502[ -]?)?[2-7]\d{3}[ -]?\d{4}(?![\w`-])")

MODELO_PERSONAS = "es_core_news_md"
VERSION_MODELO_PERSONAS = "3.8.0"
MODELOS_PERSONAS = {"es": MODELO_PERSONAS, "en": "en_core_web_md"}
COMPONENTES_PERSONAS = {
    "es": ["tok2vec", "morphologizer", "attribute_ruler", "ner"],
    "en": ["tok2vec", "tagger", "attribute_ruler", "ner"],
}
CONFIGURACION_DETECTOR = "presidio_spacy_pos_bilingue_v2"
SCORE_PERSONAS = 0.85  # Presidio usa un score fijo: spaCy no entrega probabilidad por entidad.

RE_PLACEHOLDER = re.compile(
    r"\[(?:(?:EMAIL|PHONE|DPI|CARD|PERSON)_REDACTED|TICKET VACÍO|TEXTO RETENIDO(?:: CONTIENE UN SECRETO)?)\]"
)
RE_IDENTIFICADOR = re.compile(
    r"(?<!\w)(?:TCK-\d{4}-\d{5}|F[123](?:-\d{4}-\d)?-c\d+|0x[0-9a-f]+|"
    r"[A-Z]{2,}(?:-[A-Z0-9]+)*-\d+|GS-[\w]+-[A-Z0-9]+|[a-f0-9]{4,}`[a-f0-9]+|"
    r"(?:\d{1,3}\.){3}\d{1,3}|(?:t[ée]cnic[oa]|agente|soporte|nivel)\s+N[12]|N[12])(?!\w)",
    re.IGNORECASE,
)
RE_ARCHIVO = re.compile(
    r"(?<![\w.])(?:[\w-]+\.)*(?:[\w-]+)\.(?:exe|dll|sys|msc|ini|etl|log|bat|cmd|ps1|txt|reg)(?!\w)",
    re.IGNORECASE,
)
RE_DIAGNOSTICO = re.compile(
    r"(?<!\w)(?:KB\d+|[0-9a-f]{8,}|[0-9a-f]{2}(?::[0-9a-f]{2}){2,}|"
    r"(?:[re]?(?:ax|bx|cx|dx|si|di|bp|sp|ip)|[cdefgs]s)\s*=\s*[0-9a-f]+|"
    r"(?:mov|lea|xor|push|pop|call|cmp|test|add|sub)\s+(?:qword|dword|word|byte|ptr|[re]?(?:ax|bx|cx|dx|si|di|bp|sp|ip))|"
    r"WIN\d+_DRIVER_FAULT|VIDEO_ENGINE_TIMEOUT_DETECTED|FOLLOWUP_IP|ANALYSIS_SESSION_ELAPSED_TIME|"
    r"LOGNAME_[A-Za-z0-9_]+|PagedPoolEnd|ndiscore|Srv|enabled\s*=\s*[\"']?(?:true|false|yes|no|[01]))(?!\w)",
    re.IGNORECASE,
)
RE_RUTA_USUARIO = re.compile(r"(?:[a-z]:[\\/]|/)(?:Users|home)[\\/][^\r\n;\"']+", re.IGNORECASE)
# Son los tres valores del contrato de prioridad, escritos en mayúsculas; no se eximen nombres.
RE_PRIORIDAD = re.compile(r"\b(?:ALTA|MEDIA|BAJA)\b")
# Vocabulario técnico del dominio, no nombres de personas ni ejemplos del banco de evaluación.
_TERMINOS_TECNICOS = (
    "Corporación Valcora", "Valcora ID", "Valcora", "Microsoft Authenticator", "Microsoft Teams",
    "Microsoft Outlook", "Microsoft", "Active Directory", "Entra ID", "Centro de Software",
    "Administrador de Credenciales", "Windows", "Outlook", "Teams", "Authenticator", "OneDrive",
    "SharePoint", "Office", "Excel", "Word", "PowerPoint", "Edge", "Chrome", "Linux", "Android",
    "iOS", "macOS", "VPN", "MFA", "ERP", "TI",
    "Archivo", "Rendimiento", "Notepad", "File Explorer", "PowerShell", "Print Spooler",
    "Lightspeed Rocket", "Alienware", "Intune", "Dism", "RestoreHealth", "Sfc", "WinDbg",
    "Debugger", "PoolMon", "Hyper-V", "WlanSvc", "SecMgr", "KB", "KD", "KM", "NAT", "GUID",
    "Binary", "Command", "Slmgr", "INI FILE", "vmss",
)
RE_TECNICO = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(t) for t in sorted(_TERMINOS_TECNICOS, key=len, reverse=True)) + r")(?!\w)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Deteccion:
    """Intervalo [inicio, fin) sobre str original; nunca incluye el valor detectado."""

    tipo: str
    inicio: int
    fin: int
    score: float


class ErrorPII(RuntimeError):
    """Falla cerrada con mensaje fijo, sin texto ni excepción remota o del modelo."""

    codigo = "pii_no_disponible"

    def __init__(self) -> None:
        super().__init__("No está disponible el detector local de datos personales; se retuvo el texto.")


_ANALIZADORES = {}
_CARGA = threading.Lock()
_INFERENCIA = threading.Lock()


def _crear_analizador(idioma: str):
    # Los imports y la carga son diferidos: generar F3 o comprobar Luhn no necesita NER.
    from importlib.metadata import version

    import spacy
    from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
    from presidio_analyzer.nlp_engine import NerModelConfiguration, SpacyNlpEngine
    from presidio_analyzer.predefined_recognizers import SpacyRecognizer

    modelo = MODELOS_PERSONAS[idioma]
    if not spacy.util.is_package(modelo) or version(modelo) != VERSION_MODELO_PERSONAS:
        raise ErrorPII()

    class MotorLocal(SpacyNlpEngine):
        def load(self):
            # El load de Presidio descarga modelos ausentes. Aquí solo se permite el paquete local.
            spacy.require_cpu()
            self.nlp = {idioma: spacy.load(modelo, exclude=["parser", "senter", "lemmatizer"])}
            if not set(COMPONENTES_PERSONAS[idioma]).issubset(self.nlp[idioma].pipe_names):
                raise ErrorPII()

    motor = MotorLocal(
        models=[{"lang_code": idioma, "model_name": modelo}],
        ner_model_configuration=NerModelConfiguration(
            model_to_presidio_entity_mapping={"PER": "PERSON", "PERSON": "PERSON"},
            labels_to_ignore=["ORG", "LOC", "MISC"], default_score=SCORE_PERSONAS,
        ),
    )
    motor.load()
    motor.ner_model_configuration.labels_to_ignore = sorted(
        set(motor.nlp[idioma].get_pipe("ner").labels) - {"PER", "PERSON"}
    )
    registro = RecognizerRegistry(supported_languages=[idioma], recognizers=[
        SpacyRecognizer(supported_language=idioma, supported_entities=["PERSON"]),
    ])
    return AnalyzerEngine(nlp_engine=motor, registry=registro, supported_languages=[idioma],
                          log_decision_process=False)


def _analizador_personas(idioma: str = "es"):
    if idioma not in MODELOS_PERSONAS:
        raise ErrorPII()
    if idioma not in _ANALIZADORES:
        with _CARGA:
            if idioma not in _ANALIZADORES:
                try:
                    _ANALIZADORES[idioma] = _crear_analizador(idioma)
                except Exception:
                    raise ErrorPII() from None
    return _ANALIZADORES[idioma]


def _personas(texto: str, idioma: str = "es") -> list[Deteccion]:
    try:
        analizador = _analizador_personas(idioma)
        # Un nombre dentro de Users/home sigue siendo PII. Separar barras ayuda al NER sin eximir
        # el contenido de la ruta, y cada carácter conserva su posición respecto del original.
        caracteres = list(texto)
        for m in RE_RUTA_USUARIO.finditer(texto):
            for i in range(m.start(), m.end()):
                if caracteres[i] in "\\/":
                    caracteres[i] = " "
        texto_ner = "".join(caracteres)
        with _INFERENCIA:
            artefactos = analizador.nlp_engine.process_text(texto_ner, idioma)
            if not artefactos.tokens.has_annotation("POS"):
                raise ErrorPII()
            resultados = analizador.analyze(text=texto_ner, language=idioma, entities=["PERSON"],
                                            nlp_artifacts=artefactos, score_threshold=0.0,
                                            return_decision_process=False)
            detecciones = []
            for r in resultados:
                span = artefactos.tokens.char_span(r.start, r.end, alignment_mode="expand")
                # No confundir verbos/etiquetas con personas ni arrastrar palabras ajenas al nombre.
                propios = [t for t in span if t.pos_ == "PROPN"] if span is not None else []
                if propios:
                    detecciones.append(Deteccion("PERSON", propios[0].idx,
                                                propios[-1].idx + len(propios[-1]), float(r.score)))
            return detecciones
    except Exception:
        raise ErrorPII() from None


def informacion_detector(idioma: str = "es") -> dict:
    """Carga/verifica el NER local y devuelve solo versiones; no analiza textos ni usa la red."""
    from importlib.metadata import version

    try:
        analizador = _analizador_personas(idioma)
        return {"local": True, "ner_disponible": True, "idioma": idioma,
                "modelo_personas": MODELOS_PERSONAS[idioma], "version_modelo_personas": version(MODELOS_PERSONAS[idioma]),
                "modelos": {i: {"nombre": m, "version": version(m), "componentes": list(COMPONENTES_PERSONAS[i])}
                            for i, m in MODELOS_PERSONAS.items()},
                "componentes_activos": analizador.nlp_engine.nlp[idioma].pipe_names,
                "configuracion": CONFIGURACION_DETECTOR,
                "filtro_personas": "NER_PERSON_con_limites_PROPN_sintaxis_tecnica_y_separadores_de_rutas_usuario",
                "spacy": version("spacy"),
                "presidio_analyzer": version("presidio-analyzer"), "score_personas": SCORE_PERSONAS,
                "tipos": ["PERSON", "EMAIL", "PHONE", "DPI", "CARD"]}
    except Exception:
        raise ErrorPII() from None


def luhn_valido(numero: str) -> bool:
    digitos = [int(d) for d in numero if d.isdigit()][::-1]
    total = 0
    for i, d in enumerate(digitos):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _solapan(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _restar(inicio: int, fin: int, protegidos: list[tuple[int, int]]) -> list[tuple[int, int]]:
    segmentos = [(inicio, fin)]
    for a, b in protegidos:
        siguientes = []
        for x, y in segmentos:
            if not _solapan((x, y), (a, b)):
                siguientes.append((x, y))
            else:
                if x < a:
                    siguientes.append((x, a))
                if b < y:
                    siguientes.append((b, y))
        segmentos = siguientes
    return segmentos


def detectar(texto: str, idioma: str = "es") -> list[Deteccion]:
    """Spans sin valores, ordenados por inicio y sin solapamientos; regex precede a PERSON.

    PERSON solo necesita NER si queda texto alfabético fuera de identificadores y marcadores.
    Una falla de NER aborta la detección completa: no se devuelve un resultado parcial silencioso.
    """
    if not isinstance(texto, str):
        raise TypeError("El detector requiere texto de tipo str.")
    if idioma not in MODELOS_PERSONAS:
        raise ErrorPII()
    protegidos = [(m.start(), m.end()) for patron in
                  (RE_PLACEHOLDER, RE_IDENTIFICADOR, RE_ARCHIVO, RE_DIAGNOSTICO, RE_PRIORIDAD, RE_TECNICO)
                  for m in patron.finditer(texto)]
    correos = list(RE_EMAIL.finditer(texto))
    protegidos.extend((m.start(), m.end()) for m in correos)
    candidatos = [Deteccion("EMAIL", m.start(), m.end(), 1.0) for m in correos
                  if m.group(0).lower() not in CORREOS_INSTITUCIONALES]
    for m in RE_TARJETA.finditer(texto):
        digitos = re.sub(r"\D", "", m.group(0))
        if len(set(digitos)) > 1 and luhn_valido(digitos):
            candidatos.append(Deteccion("CARD", m.start(), m.end(), 1.0))
    candidatos += [Deteccion(tipo, m.start(), m.end(), 1.0) for tipo, patron in
                   (("DPI", RE_DPI), ("PHONE", RE_TELEFONO)) for m in patron.finditer(texto)]
    prioridad = {"EMAIL": 0, "CARD": 1, "DPI": 2, "PHONE": 3}
    elegidos = []
    for d in sorted(candidatos, key=lambda d: (prioridad[d.tipo], d.inicio, -(d.fin - d.inicio))):
        if not any(_solapan((d.inicio, d.fin), (e.inicio, e.fin)) for e in elegidos):
            elegidos.append(d)
    protegidos += [(d.inicio, d.fin) for d in elegidos]
    restantes = _restar(0, len(texto), protegidos)
    if any(any(c.isalpha() for c in texto[a:b]) for a, b in restantes):
        for d in _personas(texto, idioma):
            if not (0 <= d.inicio < d.fin <= len(texto)):
                raise ErrorPII()
            for a, b in _restar(d.inicio, d.fin, protegidos):
                while a < b and (texto[a].isspace() or texto[a] in ",;:.!?¿¡()[]{}<>\"'"):
                    a += 1
                while b > a and (texto[b - 1].isspace() or texto[b - 1] in ",;:.!?¿¡()[]{}<>\"'"):
                    b -= 1
                if a < b and any(c.isalpha() for c in texto[a:b]):
                    elegidos.append(Deteccion("PERSON", a, b, d.score))
                    protegidos.append((a, b))
    return sorted(elegidos, key=lambda d: d.inicio)


def enmascarar(texto: str, idioma: str = "es") -> tuple[str, dict[str, int]]:
    """Devuelve el texto enmascarado y conteos por tipo, sin registrar valores detectados."""
    detecciones = detectar(texto, idioma=idioma)
    encontrados = Counter(d.tipo for d in detecciones)
    partes, cursor = [], 0
    for d in detecciones:
        partes.extend((texto[cursor:d.inicio], f"[{d.tipo}_REDACTED]"))
        cursor = d.fin
    partes.append(texto[cursor:])
    return "".join(partes), dict(encontrados)
