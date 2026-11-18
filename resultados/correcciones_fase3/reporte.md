# Fase 3: correcciones funcionales

Se corrigieron los cuatro fallos detectados en la revisión del proyecto. La validación completa
terminó con **238 pruebas satisfactorias, 20 omitidas y ningún fallo**. No hubo inferencias reales
ni consumo de cuota de modelos en esta fase. [Resumen automatizado](validacion.json).

## Fallos y comportamiento corregido

| Fallo | Comportamiento anterior | Resultado verificado |
|---|---|---|
| Entrada que parecía saneada | `texto_seguro` y un `guardrail` proporcionados por el llamador podían eludir la revisión; también podían inyectarse mensajes y evidencia. | Solo se aceptan `ticket_id`, `rol` y `texto`. Los secretos se bloquean y la PII se enmascara antes de guardar; campos internos y comandos de actualización/salto se rechazan sin persistirlos. |
| PDF completo sin control de rol | N1 tenía fragmentos restringidos, pero podía descargar el manual completo con sus procedimientos N2. | Ambos manuales completos devuelven 403 a N1 y 200 a N2. Microsoft sigue disponible a ambos roles. Los fragmentos permitidos conservan texto y cita; el enlace al PDF depende del permiso del documento completo. |
| Estado de error persistente | Un hilo seguía degradado tras recuperar el modelo; también podía heredar mensajes, evidencia y límites del ticket anterior. | Cada ticket reinicia el estado operativo y el éxito del modelo limpia su error. Se preservan traza y uso para auditoría; N1 no recibe el contexto N2 del ticket previo. |
| Simulación envenenada global | La modificación temporal de `HERRAMIENTAS` podía entregar instrucciones envenenadas a una consulta normal concurrente. | Cada variante recibe sus propios recursos y overrides inmutables. La búsqueda envenenada copia toda la salida antes de modificarla; el registro global, el corpus y la consulta normal permanecen intactos. |

## Límite de entrada y reutilización del hilo

La revisión ocurre en los métodos `stream`/`astream` del grafo, antes de los checkpoints, y cubre
también `invoke`/`ainvoke`. La API y `atender()` entregan la entrada canónica al mismo límite.
La decisión calculada por la API sirve para mostrar el evento inicial saneado, no para saltarse
la validación del grafo. Los errores de contrato no incluyen valores sensibles del llamador.

Al reanudar, se acepta únicamente `Command(resume=...)`; se rechazan `update`, `goto` y destinos
de otro grafo. Las decisiones inválidas se convierten a un marcador fijo antes de guardarlas,
y el identificador del aprobador pasa por el guardrail. Esto evita persistir campos arbitrarios
incluidos en una decisión inválida.

Un ticket nuevo limpia mensajes, evidencia, contadores, revisión, solicitudes finalizadas y
respuesta anterior. Mantiene traza y uso; cada inicio queda marcado con ticket e identificador
de ejecución. No se permite sustituir un hilo que aún tiene ejecución o solicitudes pendientes.

## Aprobaciones recuperables

La revisión encontró que una decisión inválida dejaba la solicitud pendiente, pero el grafo
terminaba sin un interrupt reanudable. Se corrigió junto con la protección de hilos pendientes:

- Una decisión N1, un booleano escrito como texto o un payload inválido mantienen una pausa.
- N2 puede volver a decidir en ese mismo hilo y sobre la misma solicitud.
- El nodo procesa un solo identificador pendiente por ejecución y guarda su resultado antes
  de pausar otra acción. Así no repite acciones ya resueltas al reanudar la segunda.
- Las referencias duplicadas a una solicitud se resuelven una sola vez por identificador.
- La API comunica el motivo seguro y si sigue pendiente; el modal y ambos diagramas reflejan
  la nueva pausa. No se emite una respuesta final mientras queden solicitudes pendientes.

## Evidencia y alcance de las pruebas

| Grupo | Comprobaciones |
|---|---|
| `test_fase3_entrada_estado.py` (31) | Forja de estado, secretos/PII en todos los checkpoints y escrituras pendientes, comandos inyectados, sesiones inválidas, sync/async, configuración enlazada, recuperación tras caída, reinicio del presupuesto, cambio N2→N1 y aprobaciones múltiples/duplicadas. |
| `test_fase3_fallas.py` (11) | Concurrencia normal/envenenada usando barreras y eventos, pool real de herramientas y dos grafos con modelos falsos; verifica el contexto que recibió cada modelo. También cubre copia profunda, anidación y excepciones sin contaminación. |
| `test_api.py` (18) | SSE, texto saneado, permisos y enlaces de PDF, política independiente del subset de chunks y decisión inválida seguida de N2 válida sin repetir herramientas/modelo. Incluye pruebas anteriores que siguen pasando. |
| Suite completa | 238 satisfactorias y 20 omitidas por PostgreSQL no configurado. El binario real de Codex estuvo bloqueado durante pytest. Se reutilizaron índices temporales de una ingesta previa de las mismas fuentes y la caché local del tokenizer. |
| Demo | Build React/Vite satisfactorio en copia temporal con Node 24 y dependencias existentes. Se regeneró el Mermaid del README directamente del grafo, sin base ni modelo. |

Las regresiones de PDF se comprobaron primero contra el comportamiento anterior: cinco pruebas
dirigidas fallaron por entregar el manual o exponer el enlace a N1. Las comprobaciones posteriores
pasaron. En concurrencia se usa el pool real, pero las búsquedas y los modelos son dobles de prueba;
esto verifica el aislamiento, no la resistencia semántica del LLM a la inyección.

## Límites y siguiente fase

La selección de N1/N2 sigue siendo parte de la demo local, sin autenticación de producción.
La autorización del PDF aplica al documento completo: N1 puede consultar sus fragmentos, pero
no descargar una copia del manual que contiene también procedimientos N2. La política no depende
de que el motor haya cargado todos los chunks; ambos manuales tienen contenido restringido.

La validación usó checkpoints en memoria. Las 20 pruebas de PostgreSQL, el ensayo visual en
navegador y la defensa completa siguen pendientes de sus entornos/fases. Estos cambios no borran
registros antiguos; LangGraph Studio puede guardar su entrada en almacenamiento propio antes de
invocar el grafo, por lo que se mantiene la indicación de usar solo datos ficticios en Studio.

No se regeneró F3 ni se alteraron corpus, resultados históricos o métricas del banco. Sigue la
fase 4 del [plan de cierre](../../docs/PLAN_CIERRE.md): Presidio, recall de PII y matriz de ataques.
