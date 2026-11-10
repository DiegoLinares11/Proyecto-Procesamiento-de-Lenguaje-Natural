# Asistente NLP/RAG agéntico para tickets de soporte de TI

Proyecto final de CC3103 - Procesamiento de Lenguaje Natural, Universidad del Valle de Guatemala.

Asistente que ayuda al agente de soporte de nivel 1 a clasificar tickets de TI y resolverlos con
procedimientos vigentes y citas verificables. Se abstiene cuando no hay evidencia y no ejecuta
acciones críticas sin aprobación humana. Todos los datos son ficticios o públicos.

**Equipo:** Diego Linares, Christian Echeverría, Andy Fuentes y Diederich Solis.

**Estado:** fase 2, línea base terminada. Detalle en
[resultados/linea_base/reporte_linea_base.md](resultados/linea_base/reporte_linea_base.md).

| Línea base | Resultado |
|---|---|
| Recuperación BM25 | Recall@5 0.90, MRR 0.76, sin fugas de permisos |
| Generación con citas (Sonnet 5.5) | Contrato JSON válido 100 %, abstención correcta 0.91, latencia P95 7.7 s, US$0.0075 por ticket |
| Clasificador TF-IDF | Macro-F1 0.94 en categoría y 0.96 en prioridad, inflado por los datos sintéticos |

Estos números salen de un set de validación interno; los definitivos salen del banco oficial de la fase 4.

## Qué hay aquí

| Ruta | Contenido |
|---|---|
| `datos/f1_manual/` | F1: manual ficticio de la mesa de ayuda. Fuente en Markdown y PDFs de las versiones 2026-1 y 2026-2 |
| `datos/f3_tickets/` | F3: 300 tickets resueltos sintéticos y los metadatos de su generación |
| `datos/manifiesto.json` | Registro de fuentes: permiso, formato, versión, vigencia y hash SHA-256 |
| `src/tickets_rag/` | Código: ingesta, enmascarado de PII, BM25, clasificador, generación, contrato y métricas |
| `scripts/` | Pasos del pipeline, en el orden de abajo |
| `evaluacion/validacion_dev.jsonl` | 22 consultas de validación interna. No es el banco oficial de la fase 4 |
| `resultados/linea_base/` | Métricas y trazas de la línea base |
| `tests/` | Pruebas automáticas, sin llamadas a la API |

## Cómo correrlo

Requiere [uv](https://docs.astral.sh/uv/). Instala Python 3.11 y las dependencias fijadas en `uv.lock`
(también hay un `requirements.txt` para pip).

```bash
uv sync
cp .env.example .env    # y pega tu ANTHROPIC_API_KEY; el .env nunca se sube
uv run pytest
```

Pipeline de la línea base:

```bash
uv run python scripts/construir_f1.py          # genera los PDFs de F1 (salida determinista)
uv run python scripts/ingestar.py              # verifica hashes, limpia, segmenta e indexa
uv run python scripts/evaluar_recuperacion.py  # Recall@5, MRR y Precision@5 de BM25
uv run python scripts/generar_f3.py            # redacta F3 con Haiku 5.5 (requiere API key)
uv run python scripts/evaluar_clasificador.py  # macro-F1 de TF-IDF con regresión logística
uv run python scripts/evaluar_generacion.py    # BM25 + prompt estructurado con citas (requiere API key)
```

F1 y F3 ya están en el repo: no hace falta regenerarlos para evaluar. Si cambias un PDF a propósito,
registra su nuevo hash con `uv run python scripts/ingestar.py --actualizar-hashes`.

## Decisiones de la línea base

- **Fuente única (MVP):** el índice solo tiene F1. F2, F3, la búsqueda híbrida y el reranking se agregan
  en la fase 3 si mejoran una métrica frente a esta línea base.
- **Segmentación por estructura:** un chunk por procedimiento, de máximo 450 tokens del tokenizer de
  BGE-M3, con 50 de solapamiento. Un paso numerado nunca se parte, aunque cruce de página.
- **Permisos y vigencia dentro de la búsqueda:** BM25 solo puntúa los chunks permitidos para el rol y
  vigentes; la versión anterior solo se recupera si la consulta la pide.
- **PII antes de todo:** correos, teléfonos, DPI y tarjetas se enmascaran antes de indexar y antes de
  llamar al modelo. Los nombres de personas necesitan NER y quedan para Presidio en la fase de seguridad.
- **Citas verificables:** el modelo elige qué fragmentos cita; la fuente y la página salen de los
  metadatos del chunk. Una cita que no está entre lo recuperado provoca un reintento y luego abstención.
- **F3 con semilla:** la semilla fija categoría, prioridad, escenario, fechas y PII ficticia; el modelo
  solo redacta el texto. La prioridad sigue las reglas del procedimiento 1.4 del manual.

## Uso de IA generativa

El texto de los tickets de F3 lo redactó Claude Haiku 5.5 con los parámetros que fija la semilla. Claude
también se usó como apoyo para escribir el manual ficticio y el código; el equipo revisó todo y responde
por ello.
