# Reporte de la fase de herramientas y orquestación

Fecha: 15 de noviembre de 2026.

## Qué se agregó

| Pieza | Qué hace |
|---|---|
| Historial en PostgreSQL | Tabla `tickets` con los 240 tickets del índice, enmascarados y sin solicitante. Los 60 de prueba hacen de tickets nuevos |
| Roles mínimos | `tickets_lectura`: solo SELECT sobre el historial. `tickets_acciones`: inserta solicitudes y escalamientos y cambia su estado; no borra ni lee el historial |
| 6 herramientas | `search_docs`, `buscar_casos_similares`, `classify`, `query_tickets`, `take_action`, `escalate`, con esquema Pydantic y `strict: true` |
| Grafo en LangGraph | Guardrail de entrada, router, agente ⇄ herramientas, guardrail de salida, aprobación humana con `interrupt` y checkpointer en PostgreSQL |

## Decisiones de diseño

- **Router fijo con herramientas por ruta.** El clasificador elige la ruta y el modelo solo ve las
  herramientas permitidas en ella:

  | Ruta | Herramientas |
  |---|---|
  | procedimiento | search_docs, buscar_casos_similares, escalate |
  | datos | query_tickets, search_docs |
  | accion | search_docs, take_action, escalate |
  | fuera_de_dominio | search_docs, escalate |

  Todas las rutas, menos la de datos, pueden consultar el manual, así que un error del router se corrige
  con evidencia.
- **Lo que el modelo no decide.** El rol y el ticket salen de la sesión, no de los argumentos. El modelo
  tampoco puede aprobar acciones: `take_action` solo deja la solicitud pendiente y el grafo se pausa
  hasta que una persona N2 decide.
- **El guardrail de entrada corre antes del grafo.** El checkpointer guarda todo el estado en PostgreSQL;
  así solo guarda el texto enmascarado y nunca una contraseña. Con un secreto, el ticket se rechaza sin
  llamar a ningún modelo.
- **Abstención en tres niveles.** El umbral τ sobre el reranker, el modelo que declara que no hay
  evidencia y la validación de citas, con un reintento. Al abstenerse, el ticket se escala a N2, salvo
  que esté fuera de dominio.
- **Límites.** Cada herramienta tiene 10 s y un reintento ante fallas pasajeras. Hay máximo 5 llamadas a
  herramientas por ticket; después, el modelo tiene que responder. Ninguna consulta usa SQL libre, y
  ninguna devuelve más de 100 filas.

## Clasificador few-shot (Haiku 5.5, 5 votos)

**Problema encontrado:** con el mismo prompt, las 5 corridas casi siempre coincidían, con confianza 1.0
en 57 de 60 tickets. La confianza por votación no detectaba ningún error.

**Cambios**, ajustados con 40 tickets de desarrollo del historial y no con los 60 de prueba:

- Cada voto usa un juego distinto de ejemplos, fijado por semilla.
- Se agregó la regla «la prioridad depende del impacto, no del tono».
- Hay caché del prompt por juego.

| Variante (40 de desarrollo) | F1 categoría | F1 prioridad | Votos unánimes | Errores en unánimes | US$/ticket |
|---|---|---|---|---|---|
| Original | 0.972 | 0.779 | 37 | 7 de 9 | 0.00062 |
| Juegos distintos | 0.972 | 0.769 | 28 | 4 de 9 | 0.00055 |
| **Juegos + criterios** | **0.972** | **0.796** | 31 | 3 de 8 | **0.00056** |
| Juegos + criterios, effort medium | 0.926 | 0.799 | 33 | 5 de 10 | 0.00063 |

**Umbral de revisión.** Con el 0.6 del anteproyecto, ningún ticket iba a revisión. Se cambió a revisar
cuando algún voto discrepa: en desarrollo, eso manda el 28 % a revisión y atrapa 5 de 8 errores.

**Resultado final con los 60 de prueba,** corrido una sola vez:

| | Antes | Ahora | TF-IDF |
|---|---|---|---|
| Macro-F1 categoría | 0.967 | **0.981** | 0.942 |
| Macro-F1 prioridad | 0.794 | **0.869** | 0.960 |
| Tickets con error | 14 | 9 | — |
| A revisión humana | 0 | 12 (atrapan 3 de 9 errores) | — |
| Tickets mandados a otra ruta | 3–4 | 0 | — |
| Costo por ticket | US$0.0027 | US$0.0005 | — |

TF-IDF gana en prioridad porque aprendió frases repetidas de los tickets sintéticos. La comparación
que vale es con los 20 tickets escritos a mano, que siguen pendientes.

## Demostración de punta a punta

Siete tickets, uno por camino, con Sonnet 5.5, herramientas reales y checkpointer en PostgreSQL
(`scripts/demo_grafo.py`):

| Caso | Guardrail | Ruta | Resultado | Latencia | Costo |
|---|---|---|---|---|---|
| Error 0x8004010F (F2) | ALLOW | procedimiento | Responde con 4 citas de F2, F1 y F3 | 14.1 s | US$0.033 |
| VPN con teléfono en el texto | REDACT | procedimiento | Procedimiento 5.2, sin escalar de más | 9.7 s | US$0.022 |
| Conteo de octubre | ALLOW | datos | Cita la consulta `sql-1`; los números coinciden | 6.8 s | US$0.012 |
| Restablecer MFA | ALLOW | accion | Pausa, N2 aprueba y la ejecución queda simulada | 9.7 s | US$0.019 |
| Feriados | ALLOW | fuera_de_dominio | Se abstiene sin escalar | 9.1 s | US$0.018 |
| Contraseña en el texto | BLOCK | — | Rechazo sin llamar al modelo | 0.0 s | US$0 |
| Inyección + caché de Teams | WARN | procedimiento | No revela el prompt, responde con F2 y queda marcado | 12.4 s | US$0.026 |

**Latencia:** 10.3 s de media y 14.1 s de máximo. El P95 cumple la meta de 20 s, pero la media se pasa
un poco de la de 10 s.

**Costo:** el caso de F2 cuesta US$0.033 y se pasa de la meta de US$0.03, por los fragmentos largos en
inglés.

## Limitaciones y pendientes

- **Los casos de herramientas no son el banco oficial.** El enunciado pide 10 casos de herramientas.
  Ya están cubiertos con pruebas automáticas (herramienta equivocada, parámetros fuera de rango,
  confirmación humana y servicio caído), pero el banco oficial con esos casos es de la fase de evaluación.
- **Nombres sin enmascarar.** Los nombres de personas siguen visibles hasta integrar Presidio, en la fase
  de seguridad.
- **Párrafos unidos (resuelto).** La extracción unía los párrafos de una línea seguidos. Se corrigió el
  15 de noviembre usando el interlineado de todo el documento; se reindexó y se repitió la comparación de
  la fase 3, y Recall@5, MRR y τ quedaron iguales. El clasificador y la demostración se midieron antes
  del arreglo, cuando las definiciones de 1.3 venían en un solo párrafo con el mismo texto.
- **El anteproyecto quedó desactualizado en tres puntos:** el umbral de revisión ahora es «unanimidad»
  y no 0.6, τ vale 0.0045 y los tickets van en un canal aparte.

## Cómo reproducir

```bash
docker compose up -d
uv run python scripts/preparar_bd.py
uv run python scripts/evaluar_clasificador_llm.py --conjunto desarrollo
uv run python scripts/evaluar_clasificador_llm.py --conjunto prueba --variante juegos_criterios
uv run python scripts/demo_grafo.py
uv run python scripts/atender_ticket.py "Outlook se queda en Procesando" --rol N1
```
