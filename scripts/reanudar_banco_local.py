"""Reanuda el banco canónico con su huella serializada, sin cambiar el evaluador.

El manifiesto JSON representa los pares de metas como listas. Se convierte la
huella recién calculada al mismo formato antes de la comparación de reanudación.
El evaluador sigue comprobando la huella completa y el bloqueo de la corrida.
"""

import json
import sys

import evaluar_banco
from tickets_rag.evaluacion_progreso import canonico


def main():
    if len(sys.argv) != 1:
        raise SystemExit("Este lanzador sólo reanuda la corrida canónica del banco oficial.")

    huella_original = evaluar_banco.huella_evaluacion

    def huella_serializada(*args, **kwargs):
        return json.loads(canonico(huella_original(*args, **kwargs)))

    salida = evaluar_banco.config.RESULTADOS_SUSCRIPCION / "evaluacion/banco"
    manifiesto = salida / "manifiesto_evaluacion.json"
    if not manifiesto.is_file():
        raise SystemExit("Falta el manifiesto de evaluación que se quiere reanudar.")
    with manifiesto.open(encoding="utf-8") as archivo:
        if json.load(archivo).get("estado") == "completo":
            raise SystemExit("La evaluación canónica ya está completa.")
    evaluar_banco.huella_evaluacion = huella_serializada
    sys.argv[1:] = ["--salida", str(salida), "--reanudar"]
    evaluar_banco.main()


if __name__ == "__main__":
    main()
