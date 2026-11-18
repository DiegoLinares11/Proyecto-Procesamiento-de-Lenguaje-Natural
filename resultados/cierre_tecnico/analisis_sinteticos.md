# Análisis técnico de los veinte tickets sintéticos

**Informe de IA (Codex), no revisión humana.** Corrida `6cc46dfe-2946-4c55-84ed-f5621804f8ce`; modelo `gpt-6.2-sol`, variante `juegos_criterios`, cinco juegos, cinco votos secuenciales, criterios vigentes y esfuerzo `low`. Se completaron 20/20 tickets. Los textos y las etiquetas son de IA, con revisión humana pendiente: **no satisfacen los veinte tickets escritos a mano; ese requisito sigue en 0/20**.

## Resultado comprobado

| Sistema | Macro-F1 categoría | Macro-F1 prioridad | Categoría correcta | Prioridad correcta | Ambos campos correctos |
| --- | ---: | ---: | ---: | ---: | ---: |
| TF-IDF + regresión logística | 0.883598 | 0.699941 | 18/20 | 14/20 | 13/20 |
| LLM | 1.000000 | 1.000000 | 20/20 | 20/20 | 20/20 |

Los valores se recalcularon directamente del journal con las seis categorías y tres prioridades, y coinciden con [resumen.json](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/resumen.json). TF-IDF presenta ocho errores de etiqueta en siete tickets: dos de categoría y seis de prioridad. El LLM no tiene errores de categoría o prioridad en estos veinte casos; también coincide en el tipo auxiliar de los veinte. TF-IDF se entrenó exclusivamente con 240 tickets F3 de partición `indice`, sin incorporar los sintéticos.

## Análisis de los errores de TF-IDF

La referencia normativa es el manual vigente: [1.3, categorías, F1-2026-2-c003](../../datos/f1_manual/manual_mesa_ayuda.md#13-categorías-de-ticket) y [1.4, prioridades, F1-2026-2-c004](../../datos/f1_manual/manual_mesa_ayuda.md#14-prioridades-y-tiempos-de-atención). MEDIA corresponde a trabajo afectado con alternativa temporal; ALTA, a bloqueo sin alternativa, afectación colectiva, proceso crítico o seguridad; BAJA, a consultas y solicitudes programables. Se mantuvieron las etiquetas congeladas.

| Caso y evidencia | TF-IDF: esperado → observado | Lectura del texto y criterio |
| --- | --- | --- |
| [SYN-02](../../evaluacion/tickets_sinteticos/tickets.jsonl#L2) · [resultado, fila 4](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L4) | prioridad: MEDIA → BAJA | El desbloqueo por autoservicio permite seguir temporalmente, pero el bloqueo recurrente hace perder veinte minutos: corresponde MEDIA, no una consulta menor. Manual 1.4. |
| [SYN-07](../../evaluacion/tickets_sinteticos/tickets.jsonl#L7) · [resultado, fila 14](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L14) | prioridad: MEDIA → BAJA | La reunión está afectada y se usa llamada telefónica como alternativa, sin poder presentar normalmente. Teams pertenece a CORREO. Manual 1.4. |
| [SYN-09](../../evaluacion/tickets_sinteticos/tickets.jsonl#L9) · [resultado, fila 18](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L18) | prioridad: ALTA → BAJA | El único equipo no entrega imagen; no existe préstamo y la persona no puede empezar tareas. Manual 1.4. |
| [SYN-12](../../evaluacion/tickets_sinteticos/tickets.jsonl#L12) · [resultado, fila 24](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L24) | categoria: EQUIPOS → ACCESO; prioridad: BAJA → ALTA | El objeto es un mouse que funciona; el cambio es programable y se niegan tareas bloqueadas. Periférico implica EQUIPOS; ausencia de bloqueo y programación implican BAJA. Manual 1.3 y 1.4. |
| [SYN-13](../../evaluacion/tickets_sinteticos/tickets.jsonl#L13) · [resultado, fila 26](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L26) | prioridad: ALTA → MEDIA | Varios puestos pierden cable y Wi-Fi; el área queda detenida. Afectar a varias personas basta para ALTA. Manual 1.4. |
| [SYN-18](../../evaluacion/tickets_sinteticos/tickets.jsonl#L18) · [resultado, fila 36](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L36) | prioridad: BAJA → MEDIA | La instalación del lector PDF se programa para la siguiente semana y no hay archivos actuales bloqueados. Manual 1.4. |
| [SYN-20](../../evaluacion/tickets_sinteticos/tickets.jsonl#L20) · [resultado, fila 40](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L40) | categoria: OTRO → CORREO | La petición es una constancia de vacaciones y orientación al área administrativa. El canal chat no convierte el contenido en correo o TI. Manual 1.3. |

El patrón observable es la dificultad de TF-IDF para preservar el objeto principal, el impacto, las negaciones y el carácter programable al asignar etiquetas. Esta es una descripción de las salidas; no una explicación causal de sus pesos. No se inspeccionaron coeficientes ni se hicieron contrafactuales, por lo que no se afirma que una palabra o typo determinado haya causado un error.

## Votos, procedencia y consumo

Los 20 resultados declaran cinco corridas válidas cada uno: **100 votos válidos reportados**. Las sumas de `votos` son 100 para categoría, 100 para prioridad y 100 para tipo: son tres campos de las mismas cien corridas, no trescientas inferencias. Los 20/20 registros declaran `codex_subscription` y autenticación `chatgpt`; los veinte son unánimes en los tres campos y ninguno solicita revisión por desacuerdo. La unanimidad no es una probabilidad calibrada ni valida independencia humana. No se auditó aquí cada stream CLI por separado.

La corrida completa reporta **773,129 tokens de entrada y 2,775 de salida**, con **US$0.00 de cargo incremental API**. La ruta consume cuota incluida y no es uso gratuito o ilimitado; la cifra excluye el precio de la suscripción y cualquier consumo no cuantificado del intento fallido anterior.

## Latencia activa y tiempo de pared

“Activa” es el campo `latencia_llm_s` medido con `perf_counter`, no CPU pura ni tiempo exclusivo del servidor: incluye los cinco votos y el adaptador. “Pared” se calcula con los timestamps UTC `inicio`/`resultado` de cada ticket. Se conservan ambos relojes, sin corregir respuestas ni reemplazar observaciones.

| Caso | Activa reportada (s) | Pared del journal (s) | Pared − activa (s) |
| --- | ---: | ---: | ---: |
| [SYN-01, filas 1/2](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L2) | 111.522 | 1009.479 | 897.957 |
| [SYN-02, filas 3/4](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L4) | 38.408 | 38.409 | 0.001 |
| [SYN-03, filas 5/6](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L6) | 27.636 | 27.637 | 0.001 |
| [SYN-04, filas 7/8](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L8) | 50.155 | 50.156 | 0.001 |
| [SYN-05, filas 9/10](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L10) | 50.635 | 50.636 | 0.002 |
| [SYN-06, filas 11/12](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L12) | 30.158 | 30.159 | 0.001 |
| [SYN-07, filas 13/14](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L14) | 45.822 | 45.823 | 0.001 |
| [SYN-08, filas 15/16](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L16) | 52.136 | 52.137 | 0.001 |
| [SYN-09, filas 17/18](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L18) | 50.312 | 50.314 | 0.001 |
| [SYN-10, filas 19/20](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L20) | 30.169 | 30.170 | 0.001 |
| [SYN-11, filas 21/22](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L22) | 30.517 | 30.517 | 0.001 |
| [SYN-12, filas 23/24](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L24) | 27.639 | 27.640 | 0.001 |
| [SYN-13, filas 25/26](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L26) | 33.638 | 33.639 | 0.001 |
| [SYN-14, filas 27/28](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L28) | 27.769 | 27.769 | 0.001 |
| [SYN-15, filas 29/30](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L30) | 34.482 | 34.483 | 0.001 |
| [SYN-16, filas 31/32](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L32) | 29.234 | 29.235 | 0.001 |
| [SYN-17, filas 33/34](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L34) | 31.170 | 31.170 | 0.001 |
| [SYN-18, filas 35/36](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L36) | 27.793 | 27.794 | 0.001 |
| [SYN-19, filas 37/38](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L38) | 33.637 | 33.638 | 0.001 |
| [SYN-20, filas 39/40](../codex_suscripcion/clasificador_sinteticos/6cc46dfe-2946-4c55-84ed-f5621804f8ce/mediciones_parciales.jsonl#L40) | 27.556 | 27.557 | 0.001 |

La suma activa es **790.389 s** y la suma de intervalos de pared por ticket, **1688.363 s**. Media activa: 39.519 s; mediana activa: 32.403 s; P95 activo: 55.106 s (interpolación lineal). El registro completo, que también incluye intervalos entre tickets, abarca 1689.092 s de pared. La media activa de los otros diecinueve casos, sin borrar SYN-01, es 35.730 s.

SYN-01 muestra **111.522 s activos frente a 1009.479 s de pared**, diferencia de 897.957 s. El [incidente registrado desde pmset](incidente_suspension.json) documenta `Maintenance Sleep` entre 03:38:54 y 03:53:54 −0600, una suspensión de 900 s dentro del intervalo. Es coherente con la demora de pared: no corresponde atribuir esos quince minutos a latencia del proveedor. Las cifras de ambos relojes difieren aproximadamente dos segundos de los 900 s registrados; no se fuerza una igualdad ni se resta 900 a la latencia activa. El incidente no demuestra la causa de los timeouts anteriores.

## Intento anterior y configuración

El UUID anterior `59ee02ab-1fc7-4248-8bff-b6500e4fde6e` se conserva como **incompleto, 0/20 tickets medidos**, con error `timeout` en SYN-01 y métricas nulas. Su plan `9c5d607f2c3a08b282f4f7964546917189a33e394f5b6118e9717a74d943212b` no registraba `timeout_modelo_s`; usó el límite anterior de 90 s según el contexto de ejecución. No se añade ese dato retroactivamente al artefacto. Entre su evento de inicio y error transcurrieron 116.104 s, duración del intento de ticket, no una medida aislada del deadline de un voto.

La corrida final registra explícitamente timeout de **240 s**, reintentos Python **0**, y un plan distinto `cbb19ef307a67010ceab7a75c53703ed23ffdf20d1ad5e793cbb355eea8b515b`. El timeout se aplica a cada llamada individual al modelo, no a la suma de los cinco votos ni a todo el ticket. Se mantienen UUID separados: no se mezcla la medición final con el fallo. Dataset y cinco hashes de prompts son iguales entre ambos UUID. Cero tickets completos en el anterior no significa cero llamadas o cero cuota consumida; ese consumo no está cuantificado. [Artefactos del intento anterior](../codex_suscripcion/clasificador_sinteticos/59ee02ab-1fc7-4248-8bff-b6500e4fde6e/corrida.json).

## Hipótesis previa y límites

La tensión textual entre `REGLAS_EXTRA` (BAJA si se puede seguir trabajando) y el manual 1.4 (MEDIA con alternativa temporal) **no quedó confirmada como fallo en esta corrida**: el LLM acertó las seis etiquetas MEDIA y las veinte prioridades. No se puede inferir qué instrucción pesó. Se conservan prompts y etiquetas; no se usa este resultado para ajustar los veinte reservados y volver a presentarlos como prueba independiente.

Estos veinte casos son una muestra pequeña y deliberadamente variada, redactada y anotada por IA, sin revisión humana independiente ni muestreo representativo. F1=1 describe esta corrida técnica; no demuestra generalización a tickets reales, fiabilidad productiva o calibración de la confianza. El análisis también es de IA y no se acredita como la revisión humana exigida. No se ejecutaron nuevas inferencias ni se tocó el proceso del banco oficial. Las huellas de entradas y los cálculos por caso quedan en [analisis_sinteticos.json](analisis_sinteticos.json).
