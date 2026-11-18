"""Saneamiento de valores libres antes de persistir respuestas y argumentos del modelo."""

import json

from tickets_rag.pii import enmascarar


def sanear_valores(valor, conteos=None):
    """Conserva claves, tipos y estructura; enmascara únicamente los valores de texto."""
    if isinstance(valor, str):
        limpio, encontrados = enmascarar(valor)
        if conteos is not None:
            for tipo, cantidad in encontrados.items():
                conteos[tipo] = conteos.get(tipo, 0) + cantidad
        return limpio
    if isinstance(valor, list):
        return [sanear_valores(v, conteos) for v in valor]
    if isinstance(valor, dict):
        return {k: sanear_valores(v, conteos) for k, v in valor.items()}
    return valor


def sanear_bloques(bloques: list[dict], conteos=None) -> list[dict]:
    salida = []
    for bloque in bloques:
        b = dict(bloque)
        if b.get("type") == "tool_use":
            b["input"] = sanear_valores(b["input"], conteos)
        elif b.get("type") == "text":
            try:
                datos = json.loads(b["text"])
            except (ValueError, TypeError):
                b["text"] = sanear_valores(b["text"], conteos)
            else:
                b["text"] = json.dumps(sanear_valores(datos, conteos), ensure_ascii=False)
        salida.append(b)
    return salida
