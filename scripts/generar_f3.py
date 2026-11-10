"""Genera F3: tickets resueltos sintéticos. La semilla fija los parámetros; Haiku 5.5 redacta.

Uso:
    uv run python scripts/generar_f3.py --simular      # muestra el prompt de un ticket, sin API
    uv run python scripts/generar_f3.py --muestra 5    # redacta 5 tickets en muestra.jsonl
    uv run python scripts/generar_f3.py                # redacta los 300 en tickets.jsonl

Necesita ANTHROPIC_API_KEY en el .env. El resultado se guarda en el repo: no se regenera en
cada corrida, porque el texto del modelo no es determinista.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import anthropic
from pydantic import BaseModel, Field, ValidationError

from tickets_rag import config
from tickets_rag.f3 import DESCRIPCION_PERFIL, SEMILLA, Parametros, generar_parametros
from tickets_rag.ingesta import cargar_chunks

CARPETA = config.DATOS / "f3_tickets"
MODELO = config.MODELO_CLASIFICADOR
INTENTOS = 3
# Etiquetas y frases de los parámetros: si el texto las copia, el clasificador acertaría por la frase.
PALABRAS_PROHIBIDAS = re.compile(
    r"\b(ACCESO|CORREO|EQUIPOS|RED|APLICACIONES|OTRO|ALTA|MEDIA|BAJA)\b|prioridad|procedimiento \d"
    r"|(?i:alternativa temporal|ninguna alternativa|molestia menor|incidente de seguridad)"
)

SISTEMA = """Redactas tickets ficticios para un proyecto académico de procesamiento de lenguaje natural.
Primero escribes como un colaborador de Corporación Valcora, una organización ficticia de Guatemala,
que reporta un problema a la mesa de ayuda de TI. Después escribes como el agente que lo atendió.

Reglas:
- Español natural de Guatemala. Respeta el tono y el largo.
- Varía cómo empieza el mensaje: muchos tickets reales no saludan ni se despiden.
- No copies frases de los parámetros. Cuenta el impacto con detalles concretos de la situación
  (qué no puede hacer, quiénes más están afectados, qué está usando mientras tanto).
- Si hay errores de escritura, que se noten: sin tildes, abreviaturas como «q», «xq», «compu» o
  «porfa», y alguna palabra mal escrita.
- El texto del usuario no menciona categorías, prioridades ni números de procedimiento.
- Si se te dan datos personales ficticios, cópialos exactamente igual dentro del texto del usuario.
- No inventes otros datos personales.
- El diagnóstico y la solución siguen el procedimiento de referencia de esa versión del manual,
  sin inventar pasos. Si el resultado dice que se escaló a N2, la solución lo menciona."""

LARGOS = {"breve": "1 o 2 oraciones", "media": "de 3 a 5 oraciones", "detallada": "de 6 a 9 oraciones"}


class TicketRedactado(BaseModel):
    texto: str = Field(description="Mensaje del usuario tal como llegó a la mesa de ayuda")
    resumen: str = Field(description="Título corto del ticket, de 4 a 10 palabras")
    diagnostico: str = Field(description="Diagnóstico del agente en 1 o 2 oraciones")
    solucion: str = Field(description="Lo que hizo el agente, según el procedimiento de referencia")


def procedimiento(chunks: list[dict], seccion: str, version: str) -> str:
    textos = [c["text"] for c in chunks if c["doc_id"] == f"F1-{version}" and c["seccion"] == seccion]
    return "\n".join(textos)


def prompt(p: Parametros, referencia: str) -> str:
    pii = "; ".join(d["valor"] for d in p.pii_sembrada) or "ninguno"
    secundario = p.descripcion_secundaria or "ninguno"
    escalado = " N1 no pudo resolverlo y lo escaló a N2." if p.escala_a_n2 else ""
    return f"""<parametros>
Situación: {p.descripcion} Detalle: {p.detalle}.
Impacto: {DESCRIPCION_PERFIL[p.perfil]}
Segundo problema, mencionado brevemente al final: {secundario}
Quién escribe: {p.solicitante}, del área de {p.departamento}. Incluye su nombre: {"sí" if p.incluye_nombre else "no"}.
Canal: {p.canal}. Tono: {p.tono}. Largo del mensaje: {LARGOS[p.longitud]}.
Errores de ortografía o de escritura rápida: {"sí" if p.errores_ortograficos else "no"}.
Datos personales ficticios que deben aparecer tal cual: {pii}
Resultado del ticket: {p.estado}.{escalado}
</parametros>

<procedimiento version="{p.version_manual}">
{referencia}
</procedimiento>"""


def problemas(p: Parametros, t: TicketRedactado) -> list[str]:
    errores = [f"falta el dato {d['valor']}" for d in p.pii_sembrada if d["valor"] not in t.texto]
    if m := PALABRAS_PROHIBIDAS.search(t.texto):
        errores.append(f"el texto del usuario no debe decir «{m.group(0)}»")
    return errores


def redactar(cliente: anthropic.Anthropic, p: Parametros, referencia: str) -> tuple[dict | None, dict]:
    uso = {"entrada": 0, "salida": 0, "intentos": 0}
    mensajes = [{"role": "user", "content": prompt(p, referencia)}]
    for _ in range(INTENTOS):
        uso["intentos"] += 1
        try:
            r = cliente.messages.parse(
                model=MODELO,
                max_tokens=6000,
                system=SISTEMA,
                messages=mensajes,
                output_format=TicketRedactado,
                output_config={"effort": "low"},
            )
        except ValidationError:  # respuesta cortada o JSON incompleto: se intenta de nuevo
            continue
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as error:
            print(f"{p.ticket_id}: {type(error).__name__}", file=sys.stderr)
            continue
        uso["entrada"] += r.usage.input_tokens
        uso["salida"] += r.usage.output_tokens
        if r.stop_reason == "refusal" or r.parsed_output is None:
            continue
        errores = problemas(p, r.parsed_output)
        if not errores:
            return {**p.como_dict(), **r.parsed_output.model_dump(), "modelo": r.model}, uso
        mensajes = mensajes[:1] + [
            {"role": "assistant", "content": r.parsed_output.model_dump_json()},
            {"role": "user", "content": "Corrige esto y vuelve a redactar: " + "; ".join(errores)},
        ]
    return None, uso


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--simular", action="store_true", help="imprime el prompt de un ticket sin llamar a la API")
    parser.add_argument("--muestra", type=int, default=0, help="redacta solo N tickets en muestra.jsonl")
    parser.add_argument("--hilos", type=int, default=8)
    args = parser.parse_args()

    chunks = cargar_chunks()
    parametros = generar_parametros()
    if args.simular:
        p = parametros[0]
        print(SISTEMA, "\n\n", prompt(p, procedimiento(chunks, p.seccion, p.version_manual)))
        return

    config.cargar_entorno()
    cliente = anthropic.Anthropic()
    lote = parametros[: args.muestra] if args.muestra else parametros
    salida = CARPETA / ("muestra.jsonl" if args.muestra else "tickets.jsonl")
    parcial = salida.with_suffix(".parcial.jsonl")
    CARPETA.mkdir(parents=True, exist_ok=True)

    # Lo ya redactado en una corrida anterior que se cortó no se vuelve a pagar.
    tickets = {}
    if parcial.exists():
        for linea in parcial.read_text(encoding="utf-8").splitlines():
            if linea:
                t = json.loads(linea)
                tickets[t["ticket_id"]] = t
        print(f"Retomando: {len(tickets)} tickets ya redactados", file=sys.stderr)
    pendientes = [p for p in lote if p.ticket_id not in tickets]

    fallidos = []
    totales = {"entrada": 0, "salida": 0, "intentos": 0}
    with ThreadPoolExecutor(max_workers=args.hilos) as pool, parcial.open("a", encoding="utf-8", newline="\n") as f:
        futuros = {
            pool.submit(redactar, cliente, p, procedimiento(chunks, p.seccion, p.version_manual)): p.ticket_id
            for p in pendientes
        }
        for n, futuro in enumerate(as_completed(futuros), start=1):
            ticket, uso = futuro.result()
            for k in totales:
                totales[k] += uso[k]
            if ticket:
                tickets[ticket["ticket_id"]] = ticket
                f.write(json.dumps(ticket, ensure_ascii=False) + "\n")
                f.flush()
            else:
                fallidos.append(futuros[futuro])
            if n % 25 == 0 or n == len(pendientes):
                print(f"{n}/{len(pendientes)} redactados", file=sys.stderr)

    with salida.open("w", encoding="utf-8", newline="\n") as f:
        for tid in sorted(tickets):
            f.write(json.dumps(tickets[tid], ensure_ascii=False) + "\n")
    if not fallidos:
        parcial.unlink()

    costo = config.costo_usd(MODELO, totales["entrada"], totales["salida"])
    metadatos = {
        "modelo": MODELO,
        "semilla": SEMILLA,
        "solicitados": len(lote),
        "generados": len(tickets),
        "fallidos": sorted(fallidos),
        "fecha_generacion": date.today().isoformat(),
        "version_prompt": hashlib.sha256((SISTEMA + prompt(lote[0], "")).encode()).hexdigest()[:16],
        "tokens_entrada": totales["entrada"],
        "tokens_salida": totales["salida"],
        "llamadas": totales["intentos"],
        "costo_usd": round(costo, 4),
    }
    if not args.muestra:
        (CARPETA / "generacion.json").write_text(json.dumps(metadatos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadatos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
