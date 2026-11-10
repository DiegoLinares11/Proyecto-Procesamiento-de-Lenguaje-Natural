# Reporte de la fase 3: RAG

Fecha: 10 de noviembre de 2026.

## Qué se agregó

| Componente | Línea base (fase 2) | Fase 3 |
|---|---|---|
| Fuentes en el índice | F1 | F1 y F2 para procedimientos; F3 como canal aparte de casos similares |
| Recuperación | BM25 | BM25 + BGE-M3 en pgvector, fusionados con RRF (k = 60, pesos 0.5/0.5) |
| Reordenamiento | No | bge-reranker-v2-m3 sobre los 20 mejores, entrega los 5 primeros |
| Abstención | Solo el modelo | Umbral τ sobre el score del reranker, y después el modelo |

## Corpus

| Fuente | Contenido | Chunks |
|---|---|---|
| F1 | Manual ficticio, versiones 2026-1 y 2026-2 | 76 |
| F2 | 24 artículos de Microsoft (Outlook, Teams, Windows, VPN, Entra ID), commit `aee5deb`, CC BY 4.0, en inglés | 248 |
| F3 | 240 tickets del índice; los 60 de prueba quedan fuera. 17 no vigentes porque se resolvieron con un procedimiento que después cambió | 240 |

La PII sembrada en los tickets indexados quedó enmascarada al 100 % (108 de 108 valores). En F2 quedan
4 falsos positivos de teléfono: números de 8 dígitos dentro de un volcado de memoria del artículo de
pantallas azules.

## Problemas que salieron al agregar F2

1. **Ciclo infinito en la segmentación.** Una oración o fila de tabla más grande que el presupuesto de
   tokens nunca avanzaba. Ahora se parte por palabras como último recurso, y el ciclo falla con un error
   si una unidad no cabe.
2. **Pasos pegados.** El modo layout de pypdf redondea las posiciones a caracteres y en algunas páginas
   perdía la sangría de los pasos. En la versión 2026-2, los pasos 3 y 4 de 5.4 quedaban como un párrafo.
   La extracción ahora usa la posición real de cada línea en puntos. Una prueba verifica que los pasos del
   manual quedan completos en ambas versiones.
3. **Falsas tarjetas.** El volcado de memoria `0000000000000000` pasaba la validación de Luhn. Una tarjeta
   ahora debe empezar como una red real (3 a 6) y no puede ser un solo dígito repetido.
4. **Falsa sección.** «802.11 frames are translated...» se tomaba como la sección 802.11. Ahora una sección
   solo cuenta si su número es del capítulo o artículo en curso.

## Comparación de recuperación

37 consultas de validación interna, evaluadas por unidad: procedimiento, artículo o ticket. Todas las
configuraciones, salvo la línea base y la última, buscan en F1 y F2.

| Configuración | Recall@5 | MRR | Precision@5 | Latencia media |
|---|---|---|---|---|
| Línea base: BM25 solo en F1 | 0.72 | 0.64 | 0.18 | 0.001 s |
| BM25 | 0.83 | 0.77 | 0.27 | 0.001 s |
| MiniLM | 0.70 | 0.63 | 0.28 | 0.02 s |
| BGE-M3 | 0.85 | 0.83 | 0.39 | 0.03 s |
| RRF 0.3/0.7 | 0.95 | 0.86 | 0.41 | 0.03 s |
| **RRF 0.5/0.5** | **0.95** | **0.87** | 0.35 | 0.03 s |
| RRF 0.7/0.3 | 0.90 | 0.88 | 0.32 | 0.03 s |
| **RRF + reranker** | **0.95** | **0.93** | **0.40** | 2.9 s |
| RRF + reranker con tickets mezclados | 0.40 | 0.38 | 0.17 | 2.4 s |

Ninguna configuración devolvió fragmentos no permitidos para el rol.

| Recall@5 por tipo | Línea base | RRF + reranker |
|---|---|---|
| Directa (5) | 1.00 | 1.00 |
| Paráfrasis (5) | 0.80 | 1.00 |
| Identificador exacto (4) | 0.75 | 1.00 |
| Compuesta (3) | 1.00 | 1.00 |
| Ambigua (2) | 0.50 | 0.50 |
| Vigencia (2) | 1.00 | 1.00 |
| Permisos (2) | 1.00 | 1.00 |
| Pregunta en español, respuesta en F2 en inglés (7) | 0.21 | 0.93 |

## Decisiones

- **BGE-M3 en lugar de MiniLM.** Supera a MiniLM por 0.15 de Recall@5 y 0.20 de MRR. MiniLM trunca los
  textos a 128 tokens, y la mayoría de los chunks son más largos.
- **RRF 0.5/0.5.** Da el mejor recall. Con 0.7/0.3 el MRR sube apenas, pero el recall en las preguntas
  respondidas por F2 baja de 1.00 a 0.79, porque BM25 casi no empareja español con inglés.
- **El reranker se queda.** Sube el MRR de 0.87 a 0.93 y el recall en consultas ambiguas de 0.25 a 0.50.
  Cuesta 2.9 s por consulta en la GPU, dentro de la meta de 20 s de P95 por ticket. Bajar los candidatos
  de 20 a 10 es una opción si la latencia importa más adelante.
- **Los tickets van en un canal aparte.** Mezclados con los procedimientos, llenan el top 5 porque están
  escritos con las mismas palabras que usan los usuarios. Así, el recall cae a 0.40, y a 0 en paráfrasis
  y permisos. Como canal de casos similares sí sirven: en 22 de 24 consultas, al menos uno de los 3 tickets
  recuperados se resolvió con el procedimiento correcto, y nunca devolvió tickets obsoletos.
- **τ = 0.0045 y no 0.30.** El reranker no separa limpiamente lo que tiene respuesta de lo que no. Hay
  paráfrasis informales con score 0.005, y «impresora 3D» saca 0.023 por compartir el tema de las
  impresoras. Con 0.30 el sistema se abstendría en 6 de 30 consultas con respuesta. Por eso τ funciona
  como primer filtro barato y el modelo decide los casos dudosos.

## Generación: línea base contra RAG

Mismo modelo (Sonnet 5.5), mismo prompt y las mismas 37 consultas.

| Métrica | Línea base | RAG | Meta |
|---|---|---|---|
| Validez del contrato JSON | 100 % | 100 % | 100 % |
| Abstención correcta | 0.81 | **0.95** | ≥ 0.90 |
| Falsas abstenciones | 0.23 (7 de 30) | **0.07 (2 de 30)** | ≤ 0.10 |
| Abstenciones omitidas | 0 de 7 | 0 de 7 | 0 |
| Precisión de citas por unidad | 0.67 | 0.76 | ≥ 0.90 |
| Latencia media / P95 | 3.4 s / 6.4 s | 3.9 s / 6.2 s | ≤ 10 s / ≤ 20 s |
| Costo por ticket | US$0.0074 | US$0.0078 | ≤ US$0.03 |

- **Falsas abstenciones de la línea base:** 5 de las 7 son preguntas que solo F2 responde, como el error
  0x8004010F o el código que no llega por SMS.
- **Falsas abstenciones de RAG:** «No me deja entrar», donde abstenerse con revisión humana es lo esperado
  para una consulta ambigua, y «Quiero ver el correo del trabajo en mi celular». En este último el
  procedimiento 7.1 sí llegó al contexto, pero solo dice que se atiende como CORREO, sin dar los pasos.
- **τ resolvió 6 de las 7 preguntas sin respuesta sin llamar al modelo,** y el modelo resolvió la séptima.
- **Precisión de citas:** casi todas las citas «imprecisas» son citas de apoyo correctas, como el
  procedimiento 8.2 cuando la respuesta menciona una aprobación, o el artículo de Microsoft que
  complementa al manual. La métrica por unidad las cuenta como error, así que la revisión de si cada
  cita sustenta lo afirmado le toca al juez LLM de la fase 4.

## Limitaciones

- **El set de validación es interno y pequeño.** Lo escribió el mismo autor del manual, y solo tiene 7
  consultas sin respuesta, así que τ es frágil: hay que confirmarlo con el banco oficial.
- **Nombres sin enmascarar.** Los nombres de personas en los tickets siguen visibles hasta integrar
  Presidio en la fase de seguridad.
- **Versiones de PyTorch distintas.** En macOS se instala desde PyPI y la versión no coincide con la de
  CUDA en Windows y Linux.

## Pendiente

- **Fase de herramientas:** el grafo en LangGraph, con `search_docs` (procedimientos), un canal de casos
  similares, `query_tickets`, `take_action` con aprobación de N2 y `escalate`.
- **Clasificador few-shot:** con Haiku 5.5 y confianza por votación de 5 corridas.
- **Tickets a mano:** los 20 tickets escritos a mano, por alguien que no redactó F3.
- **Banco oficial y Ragas** en la fase 4.

## Cómo reproducir

```bash
docker compose up -d
uv run python scripts/ingestar.py
uv run python scripts/indexar_vectores.py
uv run python scripts/evaluar_recuperacion.py
uv run python scripts/evaluar_generacion.py --sistema linea_base
uv run python scripts/evaluar_generacion.py --sistema rag
```
