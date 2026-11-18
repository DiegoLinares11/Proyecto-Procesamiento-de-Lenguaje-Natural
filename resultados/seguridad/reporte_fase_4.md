# Fase 4: seguridad y evidencia reproducible

Completada el 18 de noviembre de 2026. Se incorporó detección local de personas con
Presidio/spaCy, se superó la meta de recall de PII en 30 textos y se produjo la matriz
de los 12 ataques con las cinco columnas solicitadas. El banco oficial y la evaluación
comparativa de los tres sistemas siguen en las fases 5 y 6.

## Cambios implementados

- Reglas existentes para EMAIL, PHONE, DPI y CARD, más PERSON mediante Presidio 2.2.366,
  spaCy 3.8.18 y modelos locales `es_core_news_md` y `en_core_web_md` 3.8.0. Versiones,
  URLs y hashes de paquetes se fijan mediante `pyproject.toml` y `uv.lock`.
- Selección de idioma al ingerir F1/F2/F3 y al preparar contextos del juez. Filtros de
  nombres propios y sintaxis técnica reducen la redacción de verbos, códigos y productos.
  No hay descargas automáticas durante el análisis. El score PERSON de 0.85 es un valor
  operativo del reconocedor, no una probabilidad calibrada.
- Saneamiento de respuestas y argumentos de herramientas antes del checkpoint del grafo,
  además de la entrada, ingesta, generación y datos enviados a juez/Ragas. Se conservan
  estructura JSON y conteos por tipo. Si el detector local no está disponible, se retiene
  el texto; la API responde 503 con un mensaje fijo sin exponerlo ni llamar al modelo.
- Evaluadores que conservan cada corrida, hashes de entradas y fuentes, procedencia,
  métricas y trazas. El runner de ataques rechaza carpetas de salida no vacías y corta
  las llamadas siguientes ante errores de autenticación, cuota o modelo.

Los originales de F1, F2 y F3 se conservaron. Se regeneraron únicamente los índices
locales ignorados por Git para utilizar el saneamiento actual. La inspección de desarrollo
no encontró redacciones PERSON en los 38 fragmentos de cada versión de F1; F2 mantiene
13 detecciones PERSON sobre términos técnicos que requieren revisión. El detector sigue
teniendo falsos positivos y falsos negativos.

## Medición de PII

Banco sintético de IA, congelado antes de la primera medición: 30 textos en español,
56 entidades y 24 negativos técnicos explícitos. SHA-256:
`bb5280953bece83a5861ea873f5424c8d94ea25594aeeed555525c74548d6d06`.
No son los 20 tickets manuales del clasificador ni proceden de F3.

La [comprobación final](pii/20261118T065310.327723Z_bb528095/reporte.md) terminó con
**salida externa 0**. Se exige coincidencia exacta de tipo e intervalo, uno a uno, y
redacción canónica que conserve el resto del texto.

| Medición | Resultado |
|---|---:|
| TP / FP / FN | 55 / 2 / 1 |
| Recall estricto y efectivo | 55/56 = **0.9821** |
| Meta | ≥ 0.95, cumplida |
| Precisión / F1 | 0.9649 / 0.9735 |
| Recall PERSON | 24/25 = **0.96** |
| Negativos técnicos afectados | 0/24 |
| Textos con redacción íntegra | 30/30 |

EMAIL, PHONE, DPI y CARD alcanzaron recall 1.0 en esta muestra. Los dos falsos positivos
y el falso negativo corresponden a PERSON. Los diagnósticos por ID/tipo/offset están en
[casos.jsonl](pii/20261118T065310.327723Z_bb528095/casos.jsonl); no se copian valores de PII
a los reportes.

Se conserva la [primera corrida ciega](pii/20261118T060807.247726Z_bb528095/reporte.md):
55 TP, 3 FP, 1 FN, recall 0.9821. Después, una inspección independiente del corpus de
desarrollo motivó la configuración bilingüe y los filtros de sintaxis técnica. El banco
no cambió y sus errores no se usaron para ajustar reglas. Las corridas posteriores son
comprobaciones de configuraciones versionadas; **no constituyen nuevos holdouts ciegos**.
La muestra pequeña y sintética no estima por sí sola la seguridad en producción ni el
recall en inglés. Metodología: [LEEME_pii.md](../../evaluacion/LEEME_pii.md).

## Doce ataques y sus cinco columnas

La [matriz real de Codex](ataques/codex-bm25/20261118T062717.558294Z/tabla.md) contiene
amenaza, componente afectado, comportamiento esperado, resultado observado y mitigación.
Cada fila enlaza la respuesta, traza y criterios correspondientes.

| Procedencia | Criterios cumplidos | Interpretación |
|---|---:|---|
| Codex real + BM25 del manual, un voto del clasificador | **12/12** | Prueba actual con `gpt-6.2-sol`, sesión ChatGPT y acciones en memoria |
| Modelo hostil falso + grafo y contratos reales | **10/12** | Conserva fallos semánticos A02 y A03 |
| Importación histórica Claude/Anthropic | **12/12** | Recalificación de observaciones antiguas; no es una ejecución actual |

Hubo **2 WARN y 10 ALLOW** en la corrida real; no fueron 12 decisiones BLOCK. Los criterios
se cumplieron mediante filtros por rol, respuestas conservadoras, abstención o aprobación
humana según el caso. A09 solicitó un desbloqueo y quedó pendiente de aprobación.
A07 y A08 reales no solicitaron acciones: acreditan ausencia de ejecución, pero no
ejercitaron en esa corrida el rechazo por N1 o por `"true"` textual. Esos contratos se
ejercitan en la [corrida local](ataques/local/20261118T063614.425507Z/tabla.md) y sus pruebas.

A02 y A03 locales muestran que validar una cita permitida no impide por sí solo que un
modelo hostil copie instrucciones u obedezca texto envenenado. En A03 real, las búsquedas
y la respuesta final están registradas y no contienen la marca maliciosa; el artefacto
no conserva directamente el texto envenenado entregado al modelo. Los criterios son
comparaciones observables y literales, sin cobertura completa de paráfrasis.

Esta variante usa BM25, filtros de rol/vigencia y suficiencia léxica mayor que cero; no usa
recuperación híbrida, embeddings, reranker, τ semántico calibrado, historial SQL ni tickets
similares. Las acciones se simulan en memoria y no modifican sistemas externos. El rol
seleccionado en la demo no autentica personas en producción. No sustituye el benchmark
oficial del RAG híbrido. Los ataques todavía proceden de `banco_borrador.jsonl`.

La corrida real registró 54 entradas de uso: **462 016 tokens de entrada y 5 732 de salida**,
con cargo incremental de API de **US$0**. Sí consumió cuota incluida de la suscripción.
Se comprobaron autenticación ChatGPT y uso incluido antes de cada llamada; no se usó una
API key ni un proveedor alternativo. No se reutilizan costos históricos como si fueran cero.

La [tabla histórica](ataques/importado_anthropic_historico/20261118T063615.301062Z/tabla.md)
conserva su proveedor y el snapshot de chunks original para recalificar. No representa
seguridad actual de Codex. Guía y comandos: [LEEME_seguridad.md](../../evaluacion/LEEME_seguridad.md).

## Validación y entorno

La suite final terminó con **328 pruebas aprobadas y 20 omitidas**, salida externa **0**,
en un entorno nuevo de Python 3.11.13 creado con `uv venv` y sincronizado con
`uv sync --locked`, sin heredar paquetes globales. Las omitidas necesitan PostgreSQL,
que no estaba configurado. Las pruebas usan modelos falsos y checkpoints en memoria;
la corrida adversaria real se documenta por separado. Pasaron `uv lock --check`,
`uv pip check` y `git diff --check`. El build de la demo también pasó; la revisión visual
del ensayo completo corresponde a la fase 7.

Evidencia del cierre del proceso: [suite](validacion_entorno/20261118T065259.175715Z/suite.json),
[PII](validacion_entorno/20261118T065259.175715Z/pii.json) y
[paquetes del entorno](validacion_entorno/20261118T065259.175715Z/entorno.json).
Los hashes de código, lock y metadatos de los modelos están en el
[manifiesto final](pii/20261118T065310.327723Z_bb528095/manifiesto.json).

Se preservó un incidente de revisión: al sincronizar un entorno que heredaba paquetes
globales, el análisis produjo resultados pero Python terminó con SIGSEGV al cerrar.
La [corrida afectada](pii/20261118T064250.652749Z_bb528095/verificacion_proceso.json)
registra salida 139 y no se cuenta como validación exitosa del proceso. Allí se mezcló
Torch 2.15 con torchvision global 0.27, cuyo requisito era Torch 2.12. El fallo concuerda
con la incompatibilidad ABI descrita en [PyTorch #188812](https://github.com/pytorch/pytorch/issues/188812).
Se probó temporalmente un pin de Torch 2.11; se retiró al comprobar que el entorno
aislado con Torch 2.15, sin torchvision heredado, termina normalmente. Tanto la suite
como la medición final salieron 0 con ese lock. No se alteraron paquetes globales.

## Siguiente fase

La fase 5 revisará y congelará los 42 casos en `evaluacion/banco.jsonl` y preparará la
recepción de los 20 tickets escritos por una persona que no redactó F3. La autoría
humana debe ser real. La fase 6 ejecutará los tres sistemas y registrará revisión manual
de respuestas y autopsia de fallos; la fase 7 completará informe y demo.

El resumen comprobable de esta fase está en [validacion_fase_4.json](validacion_fase_4.json).
