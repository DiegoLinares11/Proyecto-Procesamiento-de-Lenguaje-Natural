"""Doce ataques con trazas separadas por procedencia. Por defecto no llama modelos ni DB.

--modo local: modelo hostil falso, guardas/grafo reales, BM25 y acciones en memoria.
--modo codex-bm25: clasificación y generación reales; BM25 manual, sin embeddings ni juez.
--modo codex-hibrido: recuperación híbrida real con conexión PostgreSQL de solo lectura.
--modo importar --artefacto ... --procedencia ...: recalifica evidencia existente, sin inferencias.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone

from tickets_rag import config
from tickets_rag.banco import BANCO_BORRADOR, cargar_banco
from tickets_rag.modelo import ErrorModelo
from tickets_rag.seguridad import (ClienteConCorte, LIMITES_LOCAL, MODOS, correr_ataque, escribir_informe, preparar_local,
                                   recursos_bm25, seleccionar_ataques, validar_importacion)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--modo", choices=MODOS, default="local")
    parser.add_argument("--banco", type=Path, default=BANCO_BORRADOR)
    parser.add_argument("--chunks", type=Path, default=config.CHUNKS)
    parser.add_argument("--salida", type=Path)
    parser.add_argument("--artefacto", type=Path)
    parser.add_argument("--procedencia", choices=("codex_subscription", "anthropic_historico"))
    parser.add_argument("--variante", help="Obligatoria al importar; describe la configuración de la corrida original")
    parser.add_argument("--corridas-clasificador", type=int, default=config.CORRIDAS_CLASIFICADOR)
    args = parser.parse_args()
    if args.corridas_clasificador < 1:
        parser.error("--corridas-clasificador debe ser positivo")
    if not args.chunks.is_file():
        parser.error("No existe --chunks. Genere/verifique la ingesta antes; este script no regenera fuentes.")
    chunks = [json.loads(l) for l in args.chunks.read_text(encoding="utf-8").splitlines() if l.strip()]
    casos = seleccionar_ataques(cargar_banco(args.banco))
    observaciones = {}
    conexion = None
    interrupcion = None
    if args.modo == "importar":
        if not (args.artefacto and args.procedencia and args.variante):
            parser.error("Importar requiere --artefacto, --procedencia y --variante explícitos.")
        filas = [json.loads(l) for l in args.artefacto.read_text(encoding="utf-8").splitlines() if l.strip()]
        observaciones = validar_importacion(filas, args.procedencia)
        procedencia, variante = args.procedencia, args.variante
        limites = ["Relectura de artefactos existentes; no se ejecutó el sistema actual ni se llamó un modelo.",
                   "Criterios literales y trazas disponibles; no sustituyen revisión manual ni ensayo de la demo."]
    elif args.modo == "local":
        procedencia, variante, limites = "simulado_local", "contratos_modelo_hostil_bm25", LIMITES_LOCAL
    else:
        if args.chunks.resolve() != config.CHUNKS.resolve():
            parser.error("En modo Codex --chunks debe ser el índice configurado; el clasificador también lee ese archivo.")
        from tickets_rag.clasificador_llm import ClasificadorLLM
        from tickets_rag.modelo import ClienteModelo

        config.cargar_entorno()
        cliente = ClienteConCorte(ClienteModelo())
        clasificador = ClasificadorLLM(cliente, corridas=args.corridas_clasificador)
        recursos = recursos_bm25(chunks, clasificador)
        if args.modo == "codex-hibrido":
            import dataclasses
            import psycopg
            from pgvector.psycopg import register_vector
            from tickets_rag import vectores
            from tickets_rag.lexico import IndiceBM25
            from tickets_rag.recuperacion import Configuracion, RecuperadorHibrido

            # vectores.conectar() crea la extensión: aquí se exige que ya exista y se abre
            # solo lectura desde la conexión inicial, antes de cualquier consulta.
            conexion = psycopg.connect(vectores.url_bd(), autocommit=True,
                                       options="-c default_transaction_read_only=on")
            register_vector(conexion)
            bm25 = IndiceBM25(chunks)
            recuperador = RecuperadorHibrido(chunks, Configuracion(tipos=["manual", "articulo"]), conexion=conexion, bm25=bm25)
            casos_similares = RecuperadorHibrido(chunks, Configuracion(tipos=["ticket"]), conexion=conexion, bm25=bm25)
            locales = dict(recursos.herramientas_locales)
            del locales["search_docs"]
            del locales["buscar_casos_similares"]
            recursos = dataclasses.replace(recursos, bm25=bm25, procedimientos=recuperador,
                                           casos=casos_similares, herramientas_locales=locales)
            recursos.calentar()
        procedencia, variante = "codex_subscription", f"{args.modo};clasificador_votos={args.corridas_clasificador}"
        limites = ["Clasificador/generador Codex reales, sin juez LLM; consume tokens y cuota incluida del plan.",
                   "Acciones/escala en memoria e historial SQL no disponible: no modifica la DB de acciones.",
                   "Rol seleccionado en demo local; no acredita autenticación de producción.",
                   "Comparaciones literales no descartan filtraciones por paráfrasis ni alucinaciones no cubiertas."]
        if args.modo == "codex-bm25":
            limites.append("Variante BM25 solo manual: coincidencia léxica>0; sin tickets similares, híbrido, reranker ni τ semántico calibrado.")
    nombre = args.modo if args.modo != "importar" else f"importado_{procedencia}"
    salida = args.salida or (config.RESULTADOS / "seguridad" / "ataques" / nombre /
                            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ"))
    if salida.exists() and any(salida.iterdir()):
        parser.error("La carpeta de salida ya contiene archivos. Use una salida nueva para conservar la procedencia de cada corrida.")

    def guardar():
        return escribir_informe(salida, casos, observaciones, chunks, args.banco, procedencia=procedencia,
                                variante=variante, limites=limites, fuente=args.artefacto, interrupcion=interrupcion)

    try:
        if args.modo != "importar":
            for caso in casos:
                if args.modo == "local":
                    recursos, cliente = preparar_local(caso, chunks)
                try:
                    observaciones[caso.id] = correr_ataque(caso, recursos, cliente)
                except ErrorModelo as error:
                    interrupcion = error.codigo  # Mensaje fijo del adaptador; sin stderr ni payloads.
                    print(f"Detenido en {caso.id}: {error}")
                    break
                except Exception as error:
                    interrupcion = f"error_local_{type(error).__name__}"
                    print(f"Detenido en {caso.id}: {interrupcion}; sin guardar payloads ni excepciones crudas.")
                    break
                guardar()  # Preserva cada observación antes de intentar el siguiente caso.
                print(f"{caso.id}: guardrail={observaciones[caso.id].get('guardrail')}; "
                      f"pausa={observaciones[caso.id].get('en_pausa_al_final')}; "
                      f"registros_uso={len(observaciones[caso.id].get('uso', []))}", flush=True)
        resumen = guardar()
    finally:
        if conexion is not None:
            conexion.close()
    print(json.dumps({k: resumen[k] for k in ("procedencia", "variante", "observados", "cumplen_criterios", "fallan", "pendientes")}, ensure_ascii=False))
    print(f"Tabla y evidencias: {salida}")
    return 2 if interrupcion else 0


if __name__ == "__main__":
    raise SystemExit(main())
