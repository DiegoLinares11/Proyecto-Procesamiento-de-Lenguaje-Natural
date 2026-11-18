# Plan de cierre por fases

Trabajaremos cada fase por separado. La distribución anterior de tareas entre integrantes no
condiciona este plan: Diederich y Codex completarán el trabajo técnico y prepararán la entrega.

| Fase | Trabajo | Criterio para terminar | Estado |
|---|---|---|---|
| 1. Conexión por suscripción | Comprobar autenticación, cuota y una respuesta estructurada con la sesión local de ChatGPT/Codex | Inferencia real sin API key, JSON válido y evidencia sin credenciales | Completada el 17 de noviembre de 2026 |
| 2. Migración del proveedor | Sustituir las llamadas de Anthropic en agente, clasificador, generador, F3 y evaluadores por una conexión local de Codex | Los flujos usan la suscripción, conservan sus contratos y no tienen fallback a API keys | Completada; validación local y prueba real acotada documentadas |
| 3. Correcciones funcionales | Corregir el saneamiento de entrada, el acceso al PDF N2, el estado de error persistente y el aislamiento del documento envenenado | Reproducciones verificadas y pruebas de regresión pertinentes | Completada; 238 pruebas pasaron, 20 de PostgreSQL omitidas |
| 4. Seguridad | Incorporar Presidio para nombres, medir recall en 30 textos con PII sembrada y documentar los 12 ataques | Recall ≥ 0.95 y matriz con amenaza, componente, comportamiento esperado, resultado observado y mitigación | Completada el 18 de noviembre de 2026; recall 55/56 y 12/12 criterios en Codex-BM25 |
| 5. Banco oficial | Revisar y congelar los 42 casos; recoger 20 tickets escritos por una persona que no redactó F3 | `evaluacion/banco.jsonl` validado y tickets independientes reservados para evaluación | Banco congelado con revisión técnica de IA. Los 20 tickets de autoría humana declarada se reservaron y evaluaron. La revisión humana del banco sigue pendiente. |
| 6. Evaluación final | Ejecutar los tres sistemas, revisar respuestas a mano y realizar la autopsia de fallos | Métricas y análisis reproducibles con el nuevo proveedor; sin reutilizar resultados históricos como actuales | Comparación completa con 88 ejecuciones y calificación de juez y Ragas. R11 de BM25 se completó en un segundo intento registrado. Quedan la revisión manual de respuestas y el análisis de fallos. |
| 7. Entrega y defensa | Completar informe de 10–15 páginas y demo de 15 minutos | Demo verificada con consulta nominal, citas, abstención, herramientas, seguridad y diagnóstico de una falla real | Pendiente |

Los 20 tickets deben tener autoría humana real. Codex puede preparar el formulario y analizar
las respuestas; no se presentarán tickets generados por IA como escritos a mano. La revisión
humana de las respuestas también debe registrarse como tal.

## Ampliación solicitada el 18 de noviembre

El usuario pidió que Codex realizara el trabajo técnico y redactara veinte casos con lenguaje
natural. Se crearon como **sintéticos de IA**, con referencias y justificación de etiquetas;
no se firmaron declaraciones humanas ni se rellenó el conjunto humano con ellos. La revisión
de los 42 oráculos también se registró como técnica de IA. Esta ampliación del trabajo no
certifica el requisito académico de autoría o revisión humana independiente.

La base local PostgreSQL 17/pgvector está preparada con 240 registros de historial y 564
fragmentos en cada índice BGE-M3/MiniLM. Hay un entorno `.venv` aislado y modelos locales
descargados. La suite conjunta actual pasó **576 pruebas sin omisiones**. Se corrigieron
cinco criterios que podían admitir falsos positivos en acciones/aprobaciones antes de medir
el banco; no se alteraron sus preguntas ni expectativas congeladas.

La medición de los veinte sintéticos obtuvo macro-F1 **1.000/1.000** en el LLM y
**0.883598/0.699941** en TF-IDF (categoría/prioridad). Es una evaluación técnica pequeña con
etiquetas de IA, sin representación de usuarios reales ni acreditación humana. Los primeros
intentos fallidos y el incidente de suspensión de la Mac se conservaron.

Evidencias: [revisión técnica del banco](../resultados/revision_tecnica_ia/reporte.md),
[análisis de los sintéticos](../resultados/cierre_tecnico/analisis_sinteticos.md),
[guía de ejecución](EJECUCION_LOCAL.md). La evaluación oficial completó las 88 ejecuciones
y la calificación con juez y Ragas. [Reporte final](../resultados/codex_suscripcion/evaluacion/banco/reporte.md).

## Resultado de la fase 1

Se utilizó la sesión **ya iniciada de ChatGPT en Codex CLI**, mediante el modo oficial
`codex exec`. No se copiaron tokens de autenticación ni se configuró una API key.
Esta es una conexión local mediante Codex; no equivale a registrar una aplicación independiente
con Sign in with ChatGPT ni a conectar todavía el backend de este proyecto.

Antes de inferir, las consultas de metadatos `account/read` y `account/rateLimits/read` indicaron:

- Autenticación `chatgpt` y permiso de uso incluido activo (`ordinaryUsageAllowed: true`).
- Cuota semanal consumida: 28 % en ese momento.
- Sin límite alcanzado y sin saldo de créditos adicionales.

La prueba ejecutó un único prompt fijo para obtener
`{"estado":"conexion_correcta","suma":5}`. Terminó correctamente en 5.54 segundos,
sin llamadas a herramientas observadas. La salida se validó contra el JSON esperado y se
exigió un evento `turn.completed` satisfactorio.

La inferencia se hizo en una carpeta temporal vacía, con sandbox de solo lectura,
configuración personal omitida, sesión efímera, método de acceso forzado a ChatGPT y
proveedor OpenAI. El entorno del proceso hijo se construyó con una lista permitida de
variables del sistema, sin API keys ni proveedores alternativos. Se desactivaron shell,
ejecución de comandos, apps, plugins, hooks, navegador y subagentes. Los registros crudos
y las credenciales no se guardaron en el repositorio.

Evidencia: [prueba_fase_1.json](../resultados/conexion_suscripcion/prueba_fase_1.json).
Es una prueba de conexión, no una medición de calidad o latencia del RAG.

**La suscripción sí consume uso incluido.** La prueba reportó 12 367 tokens de entrada y
22 de salida, incluyendo las instrucciones internas de Codex. No existe una garantía de
uso ilimitado ni un interruptor de CLI que prohíba consumir créditos al agotarse la cuota.
Por eso la fase 2 debe comprobar el permiso de uso incluido y detenerse si se agota o no
puede verificarse, sin comprar créditos ni cambiar a una API key. La selección del modelo
y la concurrencia deben considerar la cuota disponible.

## Alcance de la fase 2

La fase 2 está completada. El agente, clasificador, generador, F3, juez y Ragas usan
`ClienteModelo`, mediante Codex local autenticado con ChatGPT. Pasaron 189 pruebas offline;
20 pruebas de PostgreSQL se omitieron porque la base no estaba configurada. También pasó
una prueba real de LangGraph con dos llamadas a Codex y una cita verificable, usando un
clasificador y una búsqueda preparados para la prueba. No acredita todavía el pipeline
completo con embeddings, PostgreSQL ni los resultados finales del banco.

Ver [reporte de la fase 2](../resultados/conexion_suscripcion/reporte_fase_2.md) y
[evidencia del grafo](../resultados/conexion_suscripcion/prueba_fase_2_grafo.json).
Los resultados ya guardados de Claude/Anthropic mantienen su procedencia.

La conexión nueva valida los esquemas y deja que LangGraph controle las herramientas,
permisos y aprobaciones humanas del proyecto. Las guardas del adaptador se verificaron
con procesos falsos, incluidos errores de autenticación, cuota, formato, herramientas y plazo.
La evaluación adversaria integral queda para la fase 4. Ragas se adaptó al mismo cliente y su integración se comprobó
offline, sin inferencias reales. Falta la evaluación final de fidelidad con el banco oficial.
Se medirán por separado tokens, cuota y costo incremental de API.

Las evaluaciones de generación y del clasificador LLM, la demo y el banco del proveedor nuevo escriben
en `config.RESULTADOS_SUSCRIPCION`, cuya ruta es `resultados/codex_suscripcion/`. No sobrescriben
las carpetas históricas de Anthropic. `/api/evaluacion` busca primero el resumen nuevo del banco;
si no existe, muestra el anterior con `historico=true` y `proveedor=anthropic_historico`. La evidencia
de conexión de la fase 1 permanece en `resultados/conexion_suscripcion/` y no es un benchmark RAG.

La sesión seguirá siendo local y personal. La demo utilizará el backend de esta máquina;
las credenciales de Codex no se incorporarán al frontend, al repositorio ni a un despliegue
compartido.

### Preparación y límites de ejecución

- Disponer de Python ≥ 3.11 para el conector; el proyecto fija Python 3.11 y `uv` prepara ese entorno.
- Instalar Codex CLI o usar el binario de ChatGPT. En esta Mac está en
  `/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex`. `CODEX_BIN` permite indicar
  otra ruta; si está vacío, el cliente busca `codex` en `PATH`.
- Verificar `codex --version` e iniciar sesión con `codex login`, usando ChatGPT. Si se emplea
  `CODEX_BIN`, los comandos equivalentes son `"$CODEX_BIN" --version` y `"$CODEX_BIN" login`.
  No se requiere una API key ni se registra una aplicación OAuth propia.
- Ejecutar `uv run python scripts/verificar_suscripcion.py` para consultar metadatos de autenticación,
  modelos y cuota. No inicia una inferencia ni consume tokens de modelo. La variante `--probar`
  realiza **una inferencia mínima real** y sí consume tokens/cuota; no hace falta para consultar
  esos metadatos ni mide calidad del sistema RAG.
- Las ejecuciones reales se rechazan si el cliente no puede verificar autenticación y uso incluido,
  si alguna ventana aplicable registra un uso de 80 % o más, si la cuota está agotada o si hay
  créditos adicionales disponibles. No hay fallback a API keys ni a otros proveedores. El 80 %
  es un umbral conservador de la aplicación; no es una predicción del consumo de la siguiente
  llamada. Esta política requiere comprobar el estado antes de las inferencias; la fase 1 no
  garantiza acceso ilimitado ni crédito cero en cualquier uso futuro de la cuenta.
- El cargo incremental de API de la ruta por suscripción es US$0. Se siguen registrando los tokens
  y consumiendo la cuota incluida; la suscripción tiene su propio precio y límites. Los costos de
  resultados históricos de Anthropic no se ponen a cero ni se mezclan con esta métrica nueva.
- F3 usa un hilo por defecto, conserva sus parciales y detiene el lote si falla cuota, autenticación
  o proveedor. Migrar el código no implica regenerar sus 300 tickets ni cambiar el manifiesto.

La validación conjunta de la fase 2 terminó: suite offline, build de la demo, contrato real JSON
y ciclo del grafo con dos llamadas reales. No se regeneró F3 ni se ejecutó el banco de evaluación.
Las correcciones funcionales posteriores se registran a continuación.

## Resultado de la fase 3

Las cuatro correcciones quedaron implementadas y verificadas sin inferencias reales:

- El límite del grafo acepta solo `ticket_id`, `rol` y `texto`; sanea antes del checkpoint y
  rechaza estado prefabricado. Reanudar admite únicamente `Command(resume=...)` saneado.
- Los manuales PDF completos requieren N2. N1 conserva sus fragmentos permitidos; los enlaces
  admitidos incluyen el rol antes del ancla de página. Esta es la política de roles de la demo.
- Un ticket nuevo reinicia el estado operativo y puede recuperarse de un error previo del modelo
  sin heredar mensajes, evidencia, presupuesto ni revisión. La traza y el uso se conservan como
  auditoría. Un hilo con una solicitud pendiente no se reemplaza con otro ticket.
- La simulación envenenada usa recursos propios con un mapa inmutable y copia profunda de la
  búsqueda. No modifica el registro global ni el resultado de otra solicitud concurrente.

Durante la revisión se cerró también la recuperación de aprobaciones: una decisión inválida crea
otra pausa que N2 puede reanudar, sin repetir modelos, herramientas ni solicitudes ya resueltas.
La API y el modal muestran el motivo; el diagrama refleja el bucle de aprobación.

La suite completa pasó con **238 pruebas y 20 omitidas por PostgreSQL no configurado**. El build
de la demo también pasó. Son pruebas con modelos falsos y checkpoints en memoria; no sustituyen
el ensayo con PostgreSQL ni la evaluación final. No se regeneraron fuentes ni resultados históricos.

Ver [reporte de fase 3](../resultados/correcciones_fase3/reporte.md) y
[resumen automatizado](../resultados/correcciones_fase3/validacion.json).
La fase 4 se completó posteriormente; sigue la fase 5, banco oficial y tickets manuales.

## Resultado de la fase 4

Se incorporaron Presidio y spaCy locales, con modelos fijados de español e inglés. Los textos,
respuestas y argumentos de herramientas se sanean antes de persistirlos; si falta el detector,
el sistema retiene el texto y devuelve un error seguro.

En los 30 textos sintéticos congelados se detectaron **55 de 56 entidades**: recall estricto y
efectivo de **0.9821**, con 2 FP y 1 FN. PERSON alcanzó **24/25 (0.96)**. Ninguno de los 24 negativos
técnicos anotados resultó afectado. Las reevaluaciones conservan sus manifiestos y configuraciones;
no constituyen nuevos holdouts ciegos ni sustituyen los 20 tickets manuales.

Los 12 ataques A01–A12 cumplieron sus criterios observables con Codex real, BM25 del manual y un
voto del clasificador. Hubo **2 WARN y 10 ALLOW**; no fueron 12 BLOCK. Las acciones se simularon
en memoria. La corrida local con un modelo hostil falso conserva dos fallos semánticos (10/12).
Esta variante no sustituye la evaluación final del RAG híbrido ni autentica roles en producción.

La validación final en un entorno aislado terminó con salida 0: **328 pruebas aprobadas y 20
omitidas por PostgreSQL no configurado**. También terminó con salida 0 la medición local de PII.
Se preservó el incidente previo de incompatibilidad entre paquetes globales y el entorno de revisión.

Ver [reporte de fase 4](../resultados/seguridad/reporte_fase_4.md),
[medición PII](../resultados/seguridad/pii/20261118T065310.327723Z_bb528095/reporte.md) y
[matriz real de ataques](../resultados/seguridad/ataques/codex-bm25/20261118T062717.558294Z/tabla.md).
Sigue la fase 5: revisar los 42 casos, congelar `banco.jsonl` y obtener los 20 tickets de autoría humana
independiente. La ejecución de los tres sistemas y la autopsia de fallos corresponden a la fase 6.

## Preparación de la fase 5

Se reescribieron los 42 casos con asistencia de IA y se congeló el banco `1.0.0`. La validación
offline comprueba composición, fuentes, páginas, roles, ausencia de duplicados completos normalizados
con borrador/dev/F3 y hashes de banco, corpus, índice y registro de revisión. No se ejecutó el banco
ni se ajustaron modelos, prompts o umbrales con sus preguntas. Las expectativas SQL se contrastaron
offline con los registros de F3 que forman el historial, sin consultar PostgreSQL.

La autoría IA está declarada. Queda pendiente la revisión por un integrante que no redactó la fuente
correspondiente; `evaluacion/revision_humana_banco.csv` tiene sus 42 filas sin veredictos, nombres ni
fechas inventados. La congelación técnica no acredita esa independencia ni un nuevo holdout ciego.

La plantilla `evaluacion/tickets_manuales/plantilla.csv` se preparó con 20 filas vacías para nuevas
capturas. El importador verifica 20 textos, sus etiquetas, los datos del conjunto y las coincidencias
exactas con otros conjuntos. Reserva el conjunto fuera del índice, el entrenamiento y los ejemplos
del prompt.

El evaluador admite ese conjunto aparte, conserva cada medición parcial y registra el primer intento
antes de llamar al modelo. Reordenar las mismas filas no permite iniciar otra variante de evaluación.
La preparación técnica pasó **379 pruebas, con 20 omitidas por PostgreSQL**.

Se añadió después la captura desde el frontend en **Tickets de evaluación**: guardar borradores,
validar, congelar e iniciar explícitamente la evaluación con progreso y resultados. La captura no
requiere PostgreSQL ni hace inferencias. La suite ampliada pasó **452 pruebas, con 20 omitidas**;
el flujo se revisó con datos de prueba aislados en escritorio, tableta, móvil y teclado.
Ver [guía de pantalla](CAPTURA_TICKETS.md) y
[verificación de la captura](../resultados/captura_web/reporte.md).

Ver [reporte y siguientes pasos](../resultados/preparacion_fase5/reporte.md),
[guía del banco](../evaluacion/LEEME_banco.md) y
[formato humano](../evaluacion/tickets_manuales/LEEME.md).
La fase 6 evaluó los tres sistemas y completó la medición de los 20 tickets de autoría humana
declarada. El resumen publica las métricas agregadas. Los textos y los datos de captura quedan en
la instalación local. [Resumen de clasificación](../resultados/cierre_tecnico/clasificador_20_manuales.json).

## Referencias oficiales consultadas

- [Autenticación de Codex](https://learn.chatgpt.com/docs/auth).
- [Ejecución desde scripts y salidas JSON](https://learn.chatgpt.com/docs/non-interactive-mode).
- [Metadatos de cuenta y cuota del app-server](https://learn.chatgpt.com/docs/app-server).
- [Cuotas y créditos de Codex](https://learn.chatgpt.com/docs/pricing).
- [Uso de créditos en planes personales](https://help.openai.com/en/articles/12642688-using-credits-for-flexible-usage-in-chatgpt-personal-plans).
