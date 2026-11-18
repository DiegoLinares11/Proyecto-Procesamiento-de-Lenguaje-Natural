# Fase 2: migración a la suscripción de ChatGPT/Codex

La implementación utiliza la sesión personal local de Codex. Se retiraron las llamadas y la
dependencia directa de Anthropic. No se copiaron credenciales ni se configuraron API keys.
Esta validación corresponde a la migración, no a la evaluación final de calidad del proyecto.

## Cambios

- `ClienteModelo` centraliza sesión, cuota, proceso de inferencia, esquemas y errores sanitizados.
- Agente, generador, clasificador, juez, Ragas y generador de F3 usan el mismo contrato.
- El modelo devuelve solicitudes de herramientas como JSON. LangGraph valida argumentos y
  permisos, ejecuta las herramientas del proyecto y conserva la aprobación humana de N2.
- Los cinco votos del clasificador se ejecutan en secuencia. El primer error detiene los
  pendientes; el timeout de herramienta anterior no deja inferencias duplicadas en segundo plano.
- Ragas conserva las métricas reales de su versión 0.4.4, mediante un adaptador estructurado.
  Los bloqueos de sesión/cuota se propagan y detienen la evaluación. Las métricas fallidas
  quedan como `None`, incluido el conteo de hechos incorrectos cuando el juez no pudo medirlo.
- Se registran modelos solicitados, proveedor y tokens sin sumar la caché dos veces. El costo
  registrado es el incremental de API: US$0 por esta ruta. La cuota y el precio del plan son aparte.
- Los nuevos resultados generativos van a `resultados/codex_suscripcion/`. La demo distingue
  resultados actuales e históricos; no se sobrescribieron evaluaciones de Claude ni datos F3.

## Condiciones de ejecución

Antes de cada llamada se comprueban autenticación ChatGPT, modelo disponible, permiso explícito
de uso incluido, ausencia de créditos adicionales y uso menor del 80 % en las ventanas aplicables.
Si falta información o falla una condición, no se inicia la inferencia. No hay fallback de la
aplicación a API keys, otro proveedor ni otro modelo. El preflight tiene un plazo global de 20 s;
la inferencia, de 90 s. Las llamadas se serializan dentro de cada proceso del proyecto.

El proceso hijo recibe un entorno limitado sin claves ni endpoints alternativos, una carpeta
temporal vacía y sandbox de solo lectura. Se omiten configuración personal, reglas y contexto del
proyecto; se desactivan herramientas del host, conectores, plugins, hooks, navegador y subagentes.
Los MCP detectados se deshabilitan con una definición de transporte inerte compatible con el CLI.
Se usa sesión efímera y los archivos temporales se eliminan al terminar.

La respuesta requiere salida de proceso satisfactoria, `turn.completed`, conteos válidos y JSON
conforme al esquema. Una llamada a herramientas del host detectada en el stream detiene el proceso;
la prevención depende también de las opciones de desactivación y el sandbox. Solo se admite el
aviso informativo exacto del CLI sobre su host de Code Mode desactivado; cualquier otro error
se rechaza. Ese aviso no renueva el plazo de ejecución.

La CLI no ofrece una barrera transaccional de «solo uso incluido». La cuenta puede consumirse desde
otras sesiones mientras corre una llamada. Las comprobaciones conservadoras reducen ese riesgo,
pero no garantizan uso ilimitado ni sustituyen los controles de créditos de la cuenta.

## Validación observada

| Verificación | Resultado y alcance |
|---|---|
| Suite completa offline | **189 pasaron, 20 omitidas**, sin fallos. Las omitidas necesitan PostgreSQL preparado. Se bloqueó el binario real durante pytest para impedir inferencias accidentales. |
| Esquemas y proceso del proveedor | Procesos falsos verifican auth/cuota, JSON incompleto o inválido, ausencia de fallback, entorno sin claves, herramientas no permitidas, limpieza y timeouts. |
| Juez y Ragas | 30 pruebas con clientes falsos y las métricas reales de Ragas, incluidos bloqueos de cuota y valores `None`. No son puntajes del banco oficial. |
| Respuesta JSON real | Codex devolvió `conexion_correcta=true`: 5 288 tokens de entrada y 17 de salida en la prueba exitosa. |
| Grafo real acotado | Dos llamadas a Codex: solicitud de `search_docs`, resultado de la herramienta y respuesta final con cita válida. [Evidencia JSON](prueba_fase_2_grafo.json). |
| Demo React/Vite | Build satisfactorio con Node 24 en copia temporal. No equivale a un ensayo visual o una defensa en vivo. |
| Procedencia de resultados | API verificada con datos temporales: prefiere evaluación nueva y etiqueta el legado como histórico. |
| Dependencias | Lock y exportación actualizados; ninguna versión restante cambió. Se eliminó `anthropic` y se declaró `jsonschema` directamente. `uv lock --check` y `git diff --check` pasaron. |

La prueba del grafo utilizó LangGraph y el proveedor reales, un checkpointer en memoria y dobles
para clasificador y búsqueda. El fragmento citado proviene del corpus existente; no se midió
recuperación vectorial ni desempeño del clasificador. Se utilizaron índices temporales de una
ingesta previa de las mismas fuentes para la suite. No se creó un `.env` ni una base de datos,
no se regeneraron fuentes y no se ejecutó una evaluación masiva.

Entorno observado: Python 3.11, Codex CLI `0.167.0-alpha.4.1`; generador y clasificador configurados
como `gpt-6.2-sol`, juez como `gpt-6.2-astra`. La disponibilidad se vuelve a verificar al ejecutar.
Los tiempos de las pruebas acotadas no deben atribuirse a la latencia final del pipeline.

## Continuación

Corresponde la fase 3 del [plan de cierre](../../docs/PLAN_CIERRE.md): saneamiento de entrada,
acceso al PDF N2, recuperación del estado de error y aislamiento del documento envenenado.
Las métricas finales y el ensayo completo de la demo permanecen en sus fases respectivas.
