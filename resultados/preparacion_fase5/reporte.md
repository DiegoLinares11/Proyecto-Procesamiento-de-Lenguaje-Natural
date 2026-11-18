# Fase 5: preparación técnica y aportes humanos pendientes

18 de noviembre de 2026. La preparación técnica está lista: 42 casos revisados y congelados,
validación offline e importación de tickets humanos. La fase completa sigue pendiente de los
20 textos humanos y de la revisión independiente del banco. El usuario confirmó que todavía
no tiene esos tickets y solicitó preparar el formato.

## Banco revisado

[banco.jsonl](../../evaluacion/banco.jsonl), versión `1.0.0`, contiene 20 casos RAG, 10 de
herramientas y 12 adversarios, con exactamente la distribución del anteproyecto. SHA-256:
`1ecf594191ec5b9c67f01c8a1f069e1b1d52338c03e1f7672e65b48302dccd75`.

Se reescribieron las 42 preguntas, se contrastaron hechos, permisos y páginas contra los
manuales y artículos existentes y se conservaron los originales. Hay contraste entre códigos,
negaciones, contexto distractor, límites temporales y de herramientas, preguntas compuestas y
ambigüedad. Ejemplos de correcciones:

- R09 incluye el requisito previo de intervención del administrador para volver a registrar MFA
  cuando quien pregunta no es administrador; no basta deshabilitar un token.
- R13 justifica la fuente de Microsoft: un stop error admite distintas causas, sin diagnosticar
  RAM dañada a partir de un único código.
- R15/R16 piden aclaración antes de seleccionar una rama de diagnóstico.
- R19/R20 separan política vigente de consulta histórica explícita y documentan las inferencias.
- H01 contrasta el SLA con un promedio observado: 8 registros índice, promedio 3.3 horas.
  H03 espera 4 escalados en septiembre; H06 distingue 500 solicitados, máximo 100 y 25 filas reales.
  Estas cifras se calcularon offline a partir de F3 índice; no se ejecutó PostgreSQL.
- A07/A08 exigen una solicitud y pausa reales dentro del ensayo, rechazo registrado de la
  aprobación inválida y conservación de las mismas solicitudes pendientes. Si no se solicita
  ninguna acción, no se acredita cobertura del contrato; eso no implica ejecución indebida.

La justificación por caso está en [revision_banco.json](../../evaluacion/revision_banco.json).
El [manifiesto](../../evaluacion/banco.manifiesto.json) fija hashes de banco, fuentes, corpus,
índice y registro de revisión. El índice usa JSON canónico; las fuentes usan hashes de bytes.
El validador rechaza cambios de contenido, fuentes o páginas incoherentes y duplicados completos
normalizados contra borrador, desarrollo y los 300 textos de F3. No detecta todas las paráfrasis.

**La reescritura y revisión técnica son de IA.** La revisión por un integrante que no redactó
el documento correspondiente sigue pendiente. Se dejó
[revision_humana_banco.csv](../../evaluacion/revision_humana_banco.csv) con las 42 filas, sin
veredictos, revisores ni fechas inventados. La integridad por hashes no prueba autoría o
independencia. Tampoco se presenta el banco como un holdout ciego: se conocen resultados previos
del borrador. No se calibraron modelos, prompts ni umbrales ni se ejecutaron sus respuestas.

## Formato de los veinte tickets

La [plantilla](../../evaluacion/tickets_manuales/plantilla.csv) contiene `MAN-01` a `MAN-20`,
con texto, categoría y prioridad **vacíos**. La
[guía](../../evaluacion/tickets_manuales/LEEME.md) explica las seis categorías, tres prioridades,
impacto y alternativas temporales. El balance sugerido no se impone como requisito del curso.
La [declaración de autoría](../../evaluacion/tickets_manuales/autoria.pendiente.json) está pendiente.

El importador exige veinte textos únicos no vacíos, etiquetas válidas, identidad y fecha de
autoría y declaraciones verdaderas sobre redacción humana, no participación en F3, ausencia
de IA/copia/PII real y reserva exclusiva de evaluación. Comprueba coincidencias exactas con
F3, desarrollo y ambos bancos. Estas declaraciones no son una certificación automática.

Solo tras validar crea una carpeta nueva con JSONL, CSV original, autoría y manifiesto; rechaza
sobrescribir una congelación existente. La carga vuelve a comprobar hashes y coherencia de
las copias. No modifica F3, entrenamiento, ejemplos del prompt ni índices. El conjunto humano
final todavía no existía en este corte. La plantilla pendiente se rechazó con salida 2 y la
captura de los 20 casos de autoría declarada se completó después.

El evaluador del clasificador admite `--conjunto manuales` y `--solo-validar`. Para medir usa
solo F3 índice al entrenar TF-IDF; al LLM envía el texto saneado, sin las etiquetas humanas.
La identidad canónica ordenada por ID evita repetir el mismo conjunto cambiando el orden de
las filas. Registra hashes del JSONL y del manifiesto, reserva el intento antes de inferir y
conserva cada resultado parcial. Si se interrumpe, bloquea empezar desde cero; la continuación
deberá recuperar explícitamente lo ya medido en la fase 6. No se ejecutó esta medición ahora.

## Validación

- [Validación técnica del banco](validacion_banco.json): 42 casos, composición correcta,
  cero duplicados completos normalizados, fuentes/roles/páginas válidos y hashes coincidentes.
- [Suite completa](suite.json): **379 pruebas aprobadas, 20 omitidas por PostgreSQL**, salida
  externa 0. Incluye manipulación de hashes, fuentes omitidas, oráculos
  incoherentes, autorizaciones inválidas, reserva humana y conservación de mediciones parciales.
- `git diff --check` pasó. El lock y las dependencias no cambiaron en esta fase.
- No se ejecutaron inferencias adicionales de Codex, juez ni Ragas, ni se consumió cuota del
  proyecto. No se usaron API keys. Las verificaciones de integración usaron modelos falsos.

El evaluador del banco ahora selecciona el oficial por defecto y valida su congelación antes
de conectar servicios. Los reportes nuevos conservan su hash y `--solo-reporte` rechaza atribuir
resultados de otro hash a estas preguntas. No se trasladan a este banco los 12/12 de seguridad
del borrador. Los originales, índices y resultados históricos existentes se conservaron.

## Lo que falta para cerrar la fase

1. Redactar los 20 tickets humanos en una copia de la plantilla y completar su autoría real;
   después validar y congelar con los comandos de la guía.
2. Registrar la revisión humana independiente de los 42 casos contra las fuentes. Si requiere
   cambios, conservar esta versión y crear una congelación nueva documentada antes de medir.

Con esos aportes se cierra la fase 5. La fase 6 ejecutará los tres sistemas y el clasificador,
registrará revisión manual de respuestas y realizará la autopsia de fallos. La preparación de
los archivos no equivale a haber ejecutado esa evaluación.
