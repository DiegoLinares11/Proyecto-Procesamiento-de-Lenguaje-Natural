"""Guardrails de entrada y de salida (sección 13 del anteproyecto).

Entrada, antes de cualquier modelo y antes de guardar nada en el checkpointer:
- BLOCK: secretos (contraseñas escritas, claves de API, llaves privadas, CVV) o texto inválido.
  El texto se retiene y no llega al modelo: una contraseña no se puede enmascarar con confianza.
- WARN: posible inyección de instrucciones. Sigue, marcado para revisión humana; el prompt además
  trata el ticket como dato.
- REDACT: había datos personales y se enmascararon.
- ALLOW: nada que tratar.

Salida, antes de responder:
- Las citas deben estar entre la evidencia que devolvieron las herramientas y ser visibles para el rol.
- La respuesta se vuelve a enmascarar por si el modelo copió algún dato personal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tickets_rag.pii import enmascarar

MAX_CARACTERES = 4000
RE_TICKET = re.compile(r"^TCK-\d{4}-\d{5}$")

# Una contraseña escrita: la palabra clave seguida de un valor con algún dígito o símbolo.
# «mi contraseña es incorrecta» no cuenta; «mi contraseña es Perrito123» sí.
SECRETOS = {
    "contraseña": re.compile(
        r"(?i)\b(contrase(?:ñ|n)a|clave|password|passwd|pwd)\b[^\n.]{0,15}?(?:\bes\b|:|=)\s*"
        r"[\"'«]?(?=\S*[\d!@#$%^&*_\-])[^\s\"'»]{6,}"),
    "pin": re.compile(r"(?i)\bpin\b[^\n.]{0,15}?(?:\bes\b|:|=)\s*\d{4,8}\b"),
    "clave_api": re.compile(r"\b(sk-[A-Za-z0-9_\-]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,})\b"),
    "llave_privada": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "cvv": re.compile(r"(?i)\b(cvv|cvc|c[óo]digo de seguridad)\b\s*(?:es|:|=)?\s*\d{3,4}\b"),
}

INYECCION = [
    re.compile(r"(?i)\bignor(?:a|ar|e)\b.{0,25}\b(instrucciones|reglas|indicaciones|instructions|rules)\b"),
    re.compile(r"(?i)\bolvida\b.{0,25}\b(instrucciones|reglas|todo lo anterior)\b"),
    re.compile(r"(?i)\b(muestra|revela|imprime|dime|copia)\b.{0,30}\b(prompt|instrucciones)\b.{0,20}\b(sistema|iniciales|internas)\b"),
    re.compile(r"(?i)\b(system prompt|prompt de sistema|modo desarrollador|developer mode|jailbreak)\b"),
    re.compile(r"(?i)\b(act[uú]a como|ahora eres|a partir de ahora eres)\b"),
    re.compile(r"(?i)</?(system|fragmento|fragmentos|ticket)>"),
]


@dataclass
class DecisionEntrada:
    decision: str                     # ALLOW, WARN, REDACT o BLOCK
    texto_seguro: str                 # lo único que pasa al grafo
    pii: dict[str, int] = field(default_factory=dict)
    motivos: list[str] = field(default_factory=list)

    def para_traza(self) -> dict:
        return {"decision": self.decision, "pii": self.pii, "motivos": self.motivos}


def validar_sesion(ticket_id: str, rol: str) -> None:
    """Datos de la sesión, no del texto: si están mal, es un error del llamador, no del usuario."""
    if not RE_TICKET.match(ticket_id):
        raise ValueError(f"ticket_id inválido: {ticket_id!r}")
    if rol not in ("N1", "N2"):
        raise ValueError(f"rol inválido: {rol!r}")


def revisar_entrada(texto: str) -> DecisionEntrada:
    if not isinstance(texto, str) or not texto.strip():
        return DecisionEntrada("BLOCK", "[TICKET VACÍO]", motivos=["texto_vacio"])
    if len(texto) > MAX_CARACTERES:
        return DecisionEntrada("BLOCK", "[TEXTO RETENIDO]", motivos=[f"texto_mayor_a_{MAX_CARACTERES}_caracteres"])
    secretos = [nombre for nombre, rx in SECRETOS.items() if rx.search(texto)]
    if secretos:
        return DecisionEntrada("BLOCK", "[TEXTO RETENIDO: CONTIENE UN SECRETO]", motivos=[f"secreto:{s}" for s in secretos])
    texto_seguro, pii = enmascarar(texto)
    if any(rx.search(texto) for rx in INYECCION):
        return DecisionEntrada("WARN", texto_seguro, pii, ["posible_inyeccion"])
    if pii:
        return DecisionEntrada("REDACT", texto_seguro, pii)
    return DecisionEntrada("ALLOW", texto_seguro)


@dataclass
class RevisionSalida:
    valida: bool
    answer: str
    errores: list[str] = field(default_factory=list)
    pii_en_respuesta: dict[str, int] = field(default_factory=dict)


def revisar_salida(answer: str, citas: list[str], evidencia: dict[str, dict], rol: str, abstiene: bool) -> RevisionSalida:
    errores = []
    if not answer.strip():
        errores.append("la respuesta está vacía")
    inventadas = [c for c in citas if c not in evidencia]
    if inventadas:
        errores.append(f"cita fragmentos que no devolvió ninguna herramienta: {inventadas}")
    prohibidas = [c for c in citas if c in evidencia and rol not in evidencia[c].get("roles", ["N1", "N2"])]
    if prohibidas:
        errores.append(f"cita fragmentos que el rol {rol} no puede ver: {prohibidas}")
    if not abstiene and not citas:
        errores.append("no cita ninguna fuente")
    limpia, pii = enmascarar(answer)
    return RevisionSalida(not errores, limpia, errores, pii)
