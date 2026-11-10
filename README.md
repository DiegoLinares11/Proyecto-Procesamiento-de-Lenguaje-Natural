# Asistente NLP/RAG agéntico para tickets de soporte de TI

Proyecto final de CC3103 - Procesamiento de Lenguaje Natural, Universidad del Valle de Guatemala.

Asistente que ayuda al agente de soporte de nivel 1 a clasificar tickets de TI y resolverlos con
procedimientos vigentes y citas verificables. Se abstiene cuando no hay evidencia y no ejecuta
acciones críticas sin aprobación humana. Todos los datos son ficticios o públicos.

**Equipo:** Diego Linares, Christian Echeverría, Andy Fuentes y Diederich Solis.

**Estado:** fase 3, RAG terminado. Detalle en [resultados/rag/reporte_rag.md](resultados/rag/reporte_rag.md)
y, para la línea base, en [resultados/linea_base/reporte_linea_base.md](resultados/linea_base/reporte_linea_base.md).

Con las mismas 37 consultas de validación:

| Métrica | Línea base (BM25, solo F1) | RAG (híbrida + reranker + τ) |
|---|---|---|
| Recall@5 / MRR | 0.72 / 0.64 | 0.95 / 0.93 |
| Abstención correcta | 0.81 | 0.95 |
| Falsas abstenciones | 7 de 30 | 2 de 30 |
| Latencia P95 por ticket | 6.4 s | 6.2 s |
| Costo por ticket | US$0.0074 | US$0.0078 |

Clasificador TF-IDF de la línea base: macro-F1 0.94 en categoría y 0.96 en prioridad, inflado por los datos
sintéticos. Estos números salen de un set de validación interno; los definitivos salen del banco oficial de la fase 4.

## Qué hay aquí

| Ruta | Contenido |
|---|---|
| `datos/f1_manual/` | F1: manual ficticio de la mesa de ayuda. Fuente en Markdown y PDFs de las versiones 2026-1 y 2026-2 |
| `datos/f2_microsoft/` | F2: 24 artículos de soporte de Microsoft (CC BY 4.0) en un commit fijo, el Markdown original y el PDF |
| `datos/f3_tickets/` | F3: 300 tickets resueltos sintéticos y los metadatos de su generación |
| `datos/manifiesto.json` | Registro de fuentes: permiso, licencia, formato, versión, vigencia y hash SHA-256 |
| `src/tickets_rag/` | Código: ingesta, PII, BM25, embeddings, pgvector, búsqueda híbrida, generación, contrato y métricas |
| `scripts/` | Pasos del pipeline, en el orden de abajo |
| `evaluacion/validacion_dev.jsonl` | 37 consultas de validación interna. No es el banco oficial de la fase 4 |
| `resultados/linea_base/` | Fase 2: métricas de la línea base, calculadas con las primeras 22 consultas |
| `resultados/rag/` | Fase 3: comparación de configuraciones y generación de ambos sistemas con las 37 consultas |
| `docker-compose.yml` | PostgreSQL con pgvector, solo en 127.0.0.1:5433 |
| `tests/` | Pruebas automáticas, sin llamadas a la API; las de pgvector se saltan si la base no está levantada |

## Cómo correrlo

Requiere [uv](https://docs.astral.sh/uv/) y Docker. uv instala Python 3.11 y las dependencias fijadas en
`uv.lock`, con PyTorch para CUDA en Windows y Linux. Con pip, usa `requirements.txt` y agrega
`--extra-index-url https://download.pytorch.org/whl/cu128`.

```bash
uv sync
cp .env.example .env    # completa ANTHROPIC_API_KEY y POSTGRES_PASSWORD; el .env nunca se sube
docker compose up -d
uv run pytest
```

Pipeline:

```bash
uv run python scripts/construir_f1.py          # PDFs de F1 (salida determinista)
uv run python scripts/construir_f2.py          # descarga F2 en el commit fijo y arma su PDF
uv run python scripts/generar_f3.py            # redacta F3 con Haiku 5.5 (requiere API key)
uv run python scripts/ingestar.py              # verifica hashes, limpia, segmenta y escribe los chunks
uv run python scripts/indexar_vectores.py      # embeddings BGE-M3 y MiniLM en pgvector
uv run python scripts/evaluar_recuperacion.py  # compara BM25, vectores, RRF y reranker contra la línea base
uv run python scripts/evaluar_clasificador.py  # macro-F1 de TF-IDF con regresión logística
uv run python scripts/evaluar_generacion.py --sistema linea_base   # requiere API key
uv run python scripts/evaluar_generacion.py --sistema rag          # requiere API key y Docker
```

F1, F2 y F3 ya están en el repo: no hace falta regenerarlos para evaluar. Si cambias un documento a
propósito, registra su nuevo hash con `uv run python scripts/ingestar.py --actualizar-hashes`.

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
