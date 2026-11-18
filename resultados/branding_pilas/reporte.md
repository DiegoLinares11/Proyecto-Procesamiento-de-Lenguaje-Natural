# UI de ¡PILAS!

Fecha: 18 de noviembre de 2026. Cambio local de presentación solicitado por el usuario.

La interfaz adopta el nombre **¡PILAS!**, su firma horizontal y símbolo originales. Se aplicaron azul `#1149A8`, marfil `#F4F3F1`, lima `#D8F64E`, tinta `#112240` y Open Sans. El PDF de origen permanece intacto; los activos provienen de su página 2, sin redibujar el logo. `extraccion_marca.json` y `optimizacion_logo.json` documentan su procedencia y fidelidad.

La atención combina un bloque para el ticket y otro para la respuesta, con trazabilidad desplegable. Los ejemplos se ubican en una sección bento de seis categorías con un panel compartido de casos; elegir categoría no envía solicitudes, mientras que elegir un caso conserva el envío automático original y muestra el aviso de cuota. Se eliminó la columna larga de ejemplos que dejaba la mitad de la pantalla vacía. El nuevo estado `grupoEjemplo` controla únicamente esta selección visual.

La identidad también se aplica a captura de tickets, evaluación, citas, aprobación y grafo. Rojo/error y verde/éxito mantienen su significado. Las pantallas se adaptan a escritorio, tableta, paisaje y móvil, con navegación por teclado, retorno de foco y movimiento reducido.

Vistas finales: [atención en escritorio](atencion_1440.png), [ejemplos de seguridad en bento](bento_seguridad_1440.png), [captura real vacía](captura_real_1440.png) y [móvil](captura_real_320.png).

## Alcance conservado

- `reducir`, `atender`, `decidir`, `usarEjemplo`, efectos de carga, payloads, roles y props funcionales permanecen idénticos a la copia anterior al cambio PILAS.
- Los 56 archivos protegidos de backend, scripts, comunicación, nodos y datos coinciden por SHA-256 con esa copia. La captura JSX tampoco se modificó.
- La empresa Valcora se conserva en el corpus y sus ejemplos; PILAS identifica la aplicación.
- PRO Procesos no se modificó y no se visitó durante esta adaptación de marca. Su referencia previa fue de lectura.
- No se crearon tickets humanos ni resultados académicos. La captura real sigue en revisión 0 y 0/20.
- No se realizaron llamadas reales a modelos, commits, push ni despliegues.

## Validación

El build Vite final terminó correctamente. `git diff --check` no detectó errores de espacios.

`qa_navegador.json` registra nueve escenarios del flujo de captura con almacenamiento temporal aislado y fixtures expresamente sintéticos: persistencia, conflicto entre pestañas, validación, autoría de prueba, congelación, recarga y evaluación falsa sólo tras clic explícito.

`qa_flujos.json` y `movil_modales/qa_flujos.json` registran ocho grupos cada uno con API/SSE simulados: atención, contrato JSON, fuentes, PDF y roles, denegación, abstención, cuatro payloads de aprobación, fallas, envío de ejemplo, métricas históricas, menú, teclado y movimiento reducido. No son métricas del modelo.

`qa_bento.json` registra la comprobación final de identidad, selección de las seis categorías con teclado sin envíos, conservación de los payloads de ejemplo y diseño en 1920, 1440, 1024, 844, 768, 375 y 320 px. Las vistas `captura_real_*` muestran la captura real vacía después del CSS final. Las capturas con respuestas, aprobaciones o métricas pertenecen a simulaciones explícitas de QA.

`auditoria_integracion.json` contiene la comparación independiente de código y SHA-256. `validacion.json` reúne el resultado final.

Comprobación visual en Chrome de escritorio con tamaños de viewport; no constituye una prueba en dispositivos físicos. El motor de inferencia y PostgreSQL no se ejecutaron para esta revisión de presentación.
