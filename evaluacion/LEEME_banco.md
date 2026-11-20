# Banco revisado, congelación y evaluación

`banco.jsonl` contiene 42 casos revisados con asistencia de Codex. Conserva los IDs y la
composición del anteproyecto, pero reescribe las preguntas y corrige sus expectativas contra
las fuentes. `banco_borrador.jsonl`, redactado originalmente con Claude, se conserva intacto.
La distribución anterior de tareas entre integrantes no condiciona este trabajo.

**Estado de autoría.** La reescritura y la revisión técnica se hicieron con IA. La revisión
humana posterior se registró en [la planilla del banco](revision_humana_banco.csv).
El [manifiesto](banco.manifiesto.json) indica el alcance y deja constancia de que no se
documentó una declaración de independencia respecto de la autoría de las fuentes.

La fase 5 del plan de cierre prepara este banco y los 20 tickets manuales. La evaluación de
los tres sistemas corresponde a la fase 6. La numeración del plan de cierre es distinta de
las fases generales del enunciado.

## Composición fija

| Grupo | Distribución | Total |
|---|---|---:|
| RAG | 5 directas, 3 paráfrasis, 3 identificadores, 3 compuestas, 2 ambiguas, 2 sin respuesta, 2 de vigencia | 20 |
| Herramientas | 2 nominales, 2 de herramienta errónea, 2 de parámetros fuera de rango, 2 de confirmación humana, 2 de servicio caído | 10 |
| Adversarios | 3 de inyección, 3 de permisos, 3 de acciones críticas, 3 de alucinación forzada | 12 |

`validacion_dev.jsonl` contiene las 37 preguntas usadas para calibrar y elegir la configuración
anterior. Los 20 tickets humanos son otro conjunto: no forman parte de estos 42 ni de F3.
Su formato está en [tickets_manuales/LEEME.md](tickets_manuales/LEEME.md).

## Preguntas, evidencia y oráculos

Cada caso conserva los campos `id`, `grupo`, `tipo`, `question`, `rol`, `version`,
`expected_behavior`, `hechos`, `hechos_incorrectos`, `expected_sources`, `expected_pages`,
`answerable` y `risk_level`. También especifica ruta informativa, herramientas esperadas o
prohibidas, falla simulada, decisión de aprobación y criterios verificables. Los adversarios
incluyen amenaza, componente y mitigación; el resultado observado se completará al ejecutarlos.

Las fuentes se identifican por unidad: `F1-2026-2:3.2`, `F2:<artículo>` o `SQL:<consulta>`.
Las páginas corresponden a los PDF existentes. Los hechos se separan en afirmaciones verificables;
las inferencias de calendario, impacto o diagnóstico se justifican en `revision_banco.json`.
En las preguntas ambiguas se espera pedir información, sin inventar una rama de diagnóstico.

Los criterios están definidos en `tickets_rag.banco.CRITERIOS`: respuesta o abstención,
revisión humana, citas SQL, ausencia de fuentes N2, acciones solicitadas/pendientes/ejecutadas,
rechazo de autorizaciones inválidas, ausencia de extracción del prompt o seguimiento de
instrucciones envenenadas y modo degradado. La ruta del router se reporta aparte. Validar
citas y comparar frases conocidas no demuestra toda la fidelidad semántica ni cubre paráfrasis.

En los ataques de aprobación se exige ejercitar la solicitud y la pausa. Si un modelo se niega
a solicitar una acción, puede actuar de forma segura sin cubrir el contrato que ese escenario
buscaba probar: debe distinguirse falta de cobertura de una ejecución indebida.

## Congelación técnica

```bash
uv run python scripts/validar_banco.py
uv run pytest tests/test_banco.py tests/test_banco_revision.py
```

Estos comandos no ejecutan LLM ni PostgreSQL. Necesitan `indices/chunks.jsonl` generado con la
ingesta actual. El validador comprueba exactamente los 42 IDs y su composición, no duplicados
completos normalizados con borrador/dev/F3, fuentes, roles, páginas y hashes del banco, fuentes,
registro de revisión e índice. El índice usa hash de JSON canónico; los archivos originales
usan SHA-256 de sus bytes. No demuestra independencia semántica, autoría ni verdad automática
de cada afirmación.

No modificar el banco congelado para mejorar una métrica. Si una corrección documentada resulta
necesaria, conservar esta versión y sus resultados, crear una versión nueva con su justificación
y volver a validar antes de medir. No recalcular silenciosamente los hashes de referencia.
Esta revisión humana se registró después de las corridas. Las correcciones que cambien el
contenido requieren una nueva congelación. El banco actual no se presenta como un holdout
ciego: se conocen resultados previos del borrador y las reevaluaciones no son muestras nuevas.

## Ejecutar en la fase 6

Primero preparar PostgreSQL, sus roles, el índice vectorial y los modelos de recuperación según
el README. Luego, con Codex autenticado con ChatGPT y cuota incluida disponible:

```bash
uv run python scripts/verificar_suscripcion.py
uv run python scripts/evaluar_banco.py --banco evaluacion/banco.jsonl --casos R01,H07 --sin-juez
uv run python scripts/evaluar_banco.py --banco evaluacion/banco.jsonl --juez-en agente
```

La segunda orden es un ensayo parcial; la tercera evalúa los tres sistemas y aplica juez/Ragas
solo al agente. Sin `--juez-en` también se juzgan los otros sistemas, con más consumo de cuota.
El script usa el banco oficial por defecto y verifica su congelación antes de conectar servicios.
**Estas corridas consumen tokens y cuota incluida**, con costo incremental de API US$0; no hay
uso ilimitado ni fallback a API keys. Las guardas del adaptador siguen vigentes.

Los resultados nuevos quedan en `resultados/codex_suscripcion/evaluacion/<banco>/`. Una selección
`--casos` usa `parcial/`; los resultados históricos de Anthropic permanecen aparte. Se registra
el hash del banco: `--solo-reporte` no permite atribuir resultados antiguos a preguntas nuevas.
No trasladar el 12/12 de ataques del borrador al banco revisado sin ejecutarlo.

## Después de medir

Registrar revisión humana de una muestra de respuestas, con fidelidad, cobertura, relevancia y
citas; explicar los desacuerdos con el juez. Preparar la autopsia de fallos por caso y sistema:
rasgo lingüístico, etapa que falla, evidencia, consecuencia y mitigación. Separar fallos de
recuperación, generación, herramientas, autorización y cobertura del ensayo. No reescribir la
pregunta para ocultar un fallo observado.
