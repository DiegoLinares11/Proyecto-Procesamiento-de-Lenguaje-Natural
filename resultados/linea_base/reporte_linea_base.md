# Reporte de la línea base (fase 2)

Fecha: 9 de noviembre de 2026. Responsable: Diego Linares.

## Qué es la línea base

Es la variante mínima medible contra la que se compara todo lo que se agregue en la fase 3.

| Componente | Línea base |
|---|---|
| Índice | Solo F1, versiones 2026-1 y 2026-2: 76 chunks |
| Recuperación | BM25 (rank_bm25), con filtro de rol y vigencia dentro de la búsqueda |
| Generación | Claude Sonnet 5.5 con salida estructurada, sobre el top 5 de BM25, con citas verificadas y abstención |
| Clasificación | TF-IDF de palabras y de caracteres con regresión logística |

## Datos

- **F1:** 15 páginas por versión y 38 procedimientos, 6 de ellos solo para N2. Entre las versiones cambian
  cinco cosas: el restablecimiento de contraseña, el tiempo de desbloqueo, la cuota del buzón, el
  cliente VPN y los días para cerrar un ticket sin respuesta.
- **F3:** 300 tickets resueltos sintéticos, redactados por Claude Haiku 5.5 con parámetros fijados por
  semilla. 240 quedan para el índice y el entrenamiento, y 60 se reservan para prueba, estratificados por
  categoría. 100 tickets traen PII ficticia (128 valores) y 32 mencionan un segundo problema. Costo de
  la generación: US$0.18, más una corrida anterior que se cortó y no quedó registrada.
- **Validación:** 22 consultas internas en `evaluacion/validacion_dev.jsonl`: 5 directas, 3 paráfrasis,
  3 con identificadores exactos, 3 compuestas, 2 ambiguas, 2 sin respuesta, 2 de vigencia y 2 de
  permisos. Las escribió el mismo autor del manual, así que los resultados probablemente salen
  optimistas. No sustituyen al banco oficial de la fase 4.

## Resultados

### Recuperación (BM25, top 5)

| Recall@5 | MRR | Precision@5 | Fugas de permisos |
|---|---|---|---|
| 0.90 | 0.76 | 0.22 | 0 |

| Tipo de consulta | Casos | Recall@5 | MRR |
|---|---|---|---|
| Directa | 5 | 1.00 | 0.87 |
| Paráfrasis | 3 | 0.67 | 0.50 |
| Identificador exacto | 3 | 1.00 | 1.00 |
| Compuesta | 3 | 1.00 | 1.00 |
| Ambigua | 2 | 0.50 | 0.50 |
| Vigencia | 2 | 1.00 | 0.60 |
| Permisos | 2 | 1.00 | 0.63 |

- **Fallas:** «La computadora va lentísima» no recupera el procedimiento 4.1, porque no comparte
  palabras con «Equipo lento». «No me deja entrar» no recupera ni 2.1 ni 2.2.
- **Sin respuesta:** las 2 consultas sin respuesta igual devolvieron fragmentos. Con BM25 solo no hay un
  score que permita abstenerse.
- **Precision@5 baja por construcción:** casi todas las consultas tienen un solo procedimiento relevante,
  así que su máximo es 0.20 por caso.

### Generación (BM25 + Sonnet 5.5)

| Métrica | Resultado | Meta del anteproyecto |
|---|---|---|
| Validez del contrato JSON | 100 % | 100 % |
| Abstención correcta | 0.91 (20 de 22) | ≥ 0.90 |
| Falsas abstenciones | 0.10 (2 de 20) | ≤ 0.10 |
| Abstenciones omitidas | 0 de 2 | 0 |
| Precisión de citas por sección | 0.77 | ≥ 0.90 |
| Latencia media / P95 | 3.6 s / 7.7 s | ≤ 10 s / ≤ 20 s |
| Costo por ticket | US$0.0075 | ≤ US$0.03 |

- **Las dos falsas abstenciones:** «lentísima», porque BM25 no trajo el procedimiento correcto y el modelo
  dijo con razón que no tenía evidencia, y «No me deja entrar». En este último, abstenerse con revisión
  humana es justo el comportamiento esperado para una consulta ambigua, aunque la métrica estricta lo
  cuente como falla.
- **La abstención la resolvió el modelo:** en las 2 consultas sin respuesta, BM25 devolvió fragmentos, pero
  el modelo declaró que no alcanzaban.
- **La precisión de citas penaliza citas de apoyo.** Por ejemplo, un caso de phishing cita además el
  procedimiento de escalamiento 8.1, que es correcto pero no estaba en la lista esperada. El juez LLM de
  la fase 4 debe revisar si cada cita sustenta lo afirmado.
- **Respaldo del servidor:** quedó activado (`fallbacks: "default"`), pero no se usó: las 22 respuestas
  las dio Sonnet 5.5.

### Clasificación (TF-IDF, 60 tickets reservados)

| Objetivo | Macro-F1 | Accuracy |
|---|---|---|
| Categoría | 0.94 | 0.93 |
| Prioridad | 0.96 | 0.97 |

## Lectura de los resultados

1. **La paráfrasis es el punto débil de BM25.** Justifica la búsqueda híbrida con BGE-M3 en la fase 3.
2. **BM25 no ofrece un umbral para abstenerse.** El score normalizado del reranker que propone el
   anteproyecto resuelve justo esto.
3. **TF-IDF ya supera la meta de 0.80 con F3, y eso es una alerta, no un logro.** Los datos sintéticos
   tienen señales demasiado limpias: «no es urgente» aparece en 64 de los 65 tickets que lo mencionan, y
   todos son de prioridad BAJA. Comparar el clasificador few-shot contra TF-IDF solo con F3 diría poco.
   Esa comparación debería hacerse con los 20 tickets escritos a mano que propone el anteproyecto.
4. **El set de validación es interno.** Los números definitivos salen del banco oficial de la fase 4.

## Pendiente para la fase 3

- Búsqueda híbrida (BM25 + BGE-M3 con RRF), reranker y umbral de abstención τ.
- Agregar F2 y F3 al índice, y medir si mejoran frente a esta línea base.
- Clasificador few-shot con Haiku 5.5 y confianza por votación de 5 corridas.
- Escribir los 20 tickets a mano para el clasificador, por alguien que no redactó F3.
- Enmascarar nombres de personas con Presidio.

## Cómo reproducir

```bash
uv sync
uv run python scripts/ingestar.py
uv run python scripts/evaluar_recuperacion.py
uv run python scripts/evaluar_clasificador.py
uv run python scripts/evaluar_generacion.py   # requiere ANTHROPIC_API_KEY en el .env
```
