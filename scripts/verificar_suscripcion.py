"""Comprueba Codex sin inferir. --probar realiza UNA inferencia fija y consume cuota incluida."""

import argparse
import json

from pydantic import BaseModel

from tickets_rag import config
from tickets_rag.modelo import ClienteModelo, ErrorModelo


class Conexion(BaseModel):
    conexion_correcta: bool


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probar", action="store_true", help="consume cuota con una respuesta JSON mínima")
    args = parser.parse_args()
    cliente = ClienteModelo()
    try:
        if not args.probar:
            print(json.dumps(cliente.verificar(), ensure_ascii=False, indent=2))
            return
        r = cliente.generar(modelo=config.MODELO_GENERADOR, sistema="Prueba de conexión. Devuelve solo el JSON solicitado.",
                            mensajes=[{"role": "user", "content": "Devuelve conexion_correcta=true."}],
                            esquema=Conexion, esfuerzo="low")
        if not r.parsed_output.conexion_correcta:
            raise ErrorModelo("formato")
        print(json.dumps({"prueba": "correcta", "modelo": r.model, "proveedor": r.proveedor,
                          "autenticacion": r.modo_autenticacion, "resultado": r.parsed_output.model_dump(),
                          "tokens_entrada": r.usage.input_tokens, "tokens_salida": r.usage.output_tokens,
                          "costo_api_incremental_usd": 0.0}, ensure_ascii=False, indent=2))
    except ErrorModelo as error:
        print(json.dumps({"prueba": "detenida", "codigo": error.codigo, "mensaje": str(error)}, ensure_ascii=False))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
