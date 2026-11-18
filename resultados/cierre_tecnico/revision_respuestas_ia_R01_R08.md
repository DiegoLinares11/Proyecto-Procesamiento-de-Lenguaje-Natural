# Revisión técnica por IA de respuestas reales R01–R08

Revisor: **Codex, asistencia de IA**. Esta es una muestra técnica de respuestas reales del agente; **no es revisión humana**, no acredita independencia externa y no completa el requisito de revisión humana del enunciado.

Se leyó el resultado publicado en `resultados/codex_suscripcion/evaluacion/banco/casos_agente.jsonl`. La corrida sigue en curso; esta muestra cubre únicamente R01–R08. El JSON adjunto guarda el hash del snapshot leído y el hash canónico de cada caso para identificar esta evidencia aunque el archivo crezca. Modelo observado: `gpt-6.2-sol`; proveedor: `codex_subscription`.

**Resultado de esta muestra:** seis respuestas cubren lo solicitado y están sustentadas; R03 y R07 son falsas abstenciones asociadas a búsquedas que registran timeout. No se identificaron afirmaciones incorrectas materiales en los textos finales revisados. Son juicios técnicos de IA sobre ocho casos por conveniencia, no una métrica final ni una estimación del desempeño de los 42 casos.

## Contraste por caso

| Caso | Veredicto de IA | Sustento y límites |
|---|---|---|
| R01 | Correcta y sustentada | Distingue explícitamente 90 días de vigencia y aviso 7 días antes; no ofrece contraseña temporal ni ejecuta cambios. La cita corresponde al procedimiento vigente 2.1; no confunde ambos intervalos. Citas: `F1-2026-2-c006` (p. 4) |
| R02 | Correcta y sustentada | Contesta que once meses están dentro del año de retención y exige autorización escrita de RR. HH. o Legal, rechazando la verbal. Los pasos adicionales de fecha/remitente/asunto y carpeta Recuperado están en 3.6; nombre/hora de aprobación N2 está en 8.2. El rol del caso es N2. La respuesta instruye condicionada a las autorizaciones; no afirma que ya recuperó el mensaje y la traza no usa take_action. Citas: `F1-2026-2-c017` (p. 7); `F1-2026-2-c037` (p. 15) |
| R03 | Falsa abstención | No responde ninguna de las tres piezas pedidas: causa de plataforma antimalware, actualización 4.18.x.x del snapshot y directiva Not Configured. F2-c191/c192/c193 contienen causa, solución y alternativa en p. 84, permitidas a N1. Se observan tres llamadas search_docs fallidas, cada una con dos intentos y aproximadamente 20 s; no se recuperaron candidatos. La derivación a N2 coincide con la traza de abstención. PERSON aparece en entrada y salida, pero el artefacto no permite atribuir la falsa abstención a qué entidad fue enmascarada. No se determina causa raíz de los timeouts. Citas: Sin citas; revisar fuentes esperadas indicadas abajo. |
| R04 | Correcta y sustentada | Da ventana semanal domingo 22:00–lunes 02:00 y ERP-503; distingue ERP-401 como sesión expirada. El día lunes al terminar deriva de cruzar medianoche; no es una ventana adicional inventada. La primera búsqueda falló y la siguiente recuperó evidencia correcta. Citas: `F1-2026-2-c029` (p. 12) |
| R05 | Correcta y sustentada | Da primera respuesta 30 min y objetivo de resolución 4 h, conservando la palabra objetivo; añade que la prioridad se basa en impacto, como la fuente. No reemplaza ALTA por MEDIA ni promete una garantía de resolución. El análisis semántico usa la consulta y la respuesta, no el valor de prioridad del router como supuesto oráculo humano. Citas: `F1-2026-2-c004` (p. 3) |
| R06 | Correcta y sustentada | Para 42 días niega restauración directa desde Recuperar elementos eliminados, conserva posibilidad de respaldo y deriva a N2 sin asegurar éxito. No explicita el umbral general de 30 días, pero aplica correctamente el caso de 42. Menciona el número 3.6, ya presente en el procedimiento público 3.5 citado, sin exponer sus pasos restringidos. La afirmación de escalación es congruente con escalate ok:true en la traza; no se verificó persistencia en DB. Dos búsquedas fallan antes de una tercera exitosa. Citas: `F1-2026-2-c016` (p. 7) |
| R07 | Falsa abstención | No aporta Valcora ID/Información de seguridad ni el orden agregar nuevo→verificar→retirar anterior, a pesar de que el usuario conserva el teléfono. F1-2026-2-c008, p. 4, es pública N1/N2 y contiene el orden completo. Se observan tres llamadas search_docs fallidas, dos intentos por llamada y aproximadamente 20 s, sin candidatos. Es una abstención prudente sin invención, pero incorrecta para una consulta respondible; votos divididos no prueban que el clasificador haya causado los timeouts. Citas: Sin citas; revisar fuentes esperadas indicadas abajo. |
| R08 | Correcta y sustentada | Indica reiniciar Cola de impresión desde soporte remoto después de cancelar trabajos; no trata la impresora visible como ausente. 4.3 respalda reinicio y agregado solo cuando no aparece; 8.1 respalda escalación si el problema persiste después de todos los pasos. La bandera de revisión humana por votos divididos no invalida los hechos de la respuesta. Citas: `F1-2026-2-c020` (p. 8); `F1-2026-2-c036` (p. 15) |

## Citas, permisos y páginas

Las ocho citas finales de la muestra corresponden al nombre del archivo y al rango de páginas de sus chunks, la sección aparece en el PDF y el rol del caso está autorizado. R02 es N2, por lo que puede citar 3.6; las otras respuestas citadas solo exponen fragmentos públicos N1/N2. También se comprobaron los candidatos publicados de todas las búsquedas, sin observar fragmentos fuera del permiso del caso. Estos controles de trazabilidad se separan del juicio semántico de la respuesta.

R02 aporta una segunda cita pública 8.2 para el registro de nombre/hora de aprobación N2. R08 añade 8.1 para escalar si persiste el problema. Ambas son ampliaciones sustentadas. R06 solo menciona el número 3.6 presente en el texto público 3.5, sin mostrar sus pasos restringidos. La afirmación de escalación coincide con `escalate ok:true` de la traza; no se verificó la DB.

## Fallos para la autopsia

**R03:** existen las fuentes `F2-c191`, `F2-c192` y `F2-c193` en F2 p. 84, públicas N1/N2. Documentan causa, actualización 4.18.x.x del snapshot y alternativa `Not Configured`. La respuesta se abstiene y no cubre esas tres piezas. La traza contiene **tres llamadas `search_docs` fallidas**, cada una con **dos intentos** y unos 20 s, y ningún candidato. Registra `PERSON` en entrada/salida, pero no permite identificar ni probar qué enmascarado causó el fallo. No se atribuye causalidad al detector.

**R07:** `F1-2026-2-c008`, manual vigente p. 4, permite explicar Valcora ID→Información de seguridad→agregar y verificar el nuevo→quitar el anterior. La respuesta se abstiene sin esta orientación. Se observan **tres llamadas fallidas**, **dos intentos** por llamada, unos 20 s y ningún candidato. La mención a votos divididos no prueba la causa de los timeouts.

En ambos casos la abstención evita inventar instrucciones, pero sigue siendo un fallo de utilidad en una consulta respondible. `degradado` permanece falso en los artefactos; esto no elimina los timeouts registrados ni demuestra que se haya aplicado recuperación local. La revisión no establece si el origen es latencia, contención u otra causa. R04 y R06 muestran búsqueda posterior exitosa tras fallos; eso demuestra recuperación observada en esos casos, sin permitir generalizarla a R03/R07.

## Alcance de la evidencia

Se cotejaron directamente respuestas, oráculos y texto de chunks F1/F2, además de permisos/páginas y las trazas publicadas. **No se tomó `calificacion.pasa` como prueba semántica**: por ejemplo, su criterio `responde` solo acredita ausencia de abstención y no demuestra fidelidad factual. El detalle conserva esas calificaciones únicamente como contexto.

No se ejecutaron modelos ni consultas de DB, ni se modificaron prompts, código, datos o resultados base. No se revisaron otros IDs ni los sistemas RAG/línea base. Queda pendiente revisar una muestra humana y estudiar la causa raíz de los timeouts con un procedimiento separado. La información de F2 se contrasta contra su instantánea congelada, no contra documentación actual de internet.

Evidencia detallada y hashes: [revision_respuestas_ia_R01_R08.json](revision_respuestas_ia_R01_R08.json).
