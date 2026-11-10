"""Detección y enmascarado de datos personales con expresiones regulares.

Cada valor se reemplaza por su tipo, por ejemplo [EMAIL_REDACTED], para conservar el sentido
del texto sin el dato. Las detecciones se devuelven como conteos por tipo, nunca con el valor.

Los nombres de personas necesitan un modelo de NER; quedan para la integración con Presidio
en la fase de seguridad.
"""

from __future__ import annotations

import re
from collections import Counter

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


def enmascarar(texto: str) -> tuple[str, dict[str, int]]:
    """Devuelve el texto enmascarado y cuántos datos de cada tipo se encontraron."""
    encontrados: Counter[str] = Counter()

    def correo(m: re.Match[str]) -> str:
        if m.group(0).lower() in CORREOS_INSTITUCIONALES:
            return m.group(0)
        encontrados["EMAIL"] += 1
        return "[EMAIL_REDACTED]"

    def tarjeta(m: re.Match[str]) -> str:
        digitos = re.sub(r"\D", "", m.group(0))
        if len(set(digitos)) == 1 or not luhn_valido(digitos):
            return m.group(0)
        encontrados["CARD"] += 1
        return "[CARD_REDACTED]"

    def dpi(m: re.Match[str]) -> str:
        encontrados["DPI"] += 1
        return "[DPI_REDACTED]"

    def telefono(m: re.Match[str]) -> str:
        encontrados["PHONE"] += 1
        return "[PHONE_REDACTED]"

    # El orden importa: primero los patrones más largos, para que un número de tarjeta
    # no se confunda con un teléfono.
    texto = RE_EMAIL.sub(correo, texto)
    texto = RE_TARJETA.sub(tarjeta, texto)
    texto = RE_DPI.sub(dpi, texto)
    texto = RE_TELEFONO.sub(telefono, texto)
    return texto, dict(encontrados)
