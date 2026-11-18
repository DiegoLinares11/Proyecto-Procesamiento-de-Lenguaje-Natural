# Rediseño visual del asistente

18 de noviembre de 2026. Se renovó la presentación de las tres secciones de la aplicación
con la paleta de [PRO Procesos](https://pro-procesos.vercel.app/). La referencia inspeccionada
fue su acceso público y los tokens compartidos de sus estilos. La implementación corresponde
al asistente local de Valcora, con sus nombres y funciones existentes.

## Dirección visual

| Uso | Color |
|---|---|
| Acento de marca | `#ed1c2e` |
| Acción principal y texto rojo con contraste | `#c81324` |
| Navegación lateral | `#111216` |
| Fondo de trabajo | `#f3f4f6` |
| Superficies | `#ffffff` |
| Texto principal / secundario | `#17191d` / `#667085` |
| Bordes | `#e4e7ec` |

Se conservan verde para estados satisfactorios, ámbar para espera/revisión y rojo oscuro
para errores. La tipografía principal pasa a Poppins; los identificadores y contratos
conservan una fuente monoespaciada.

- Navegación lateral con las tres secciones y menú compacto en móvil.
- Composición centrada en escribir el ticket y leer su respuesta. Las fallas simuladas y
  el recorrido del grafo se despliegan cuando se necesitan.
- Captura de veinte casos con editor protagonista, avance, guardado y autoría organizados.
  En móvil, el índice permite deslizar entre tickets sin ocupar cinco filas antes del editor.
- Respuestas, citas, contrato JSON, tabla de métricas, trazas y documentos con superficies claras.
- Estados vacíos y errores legibles, foco visible, teclado en menús/diálogos y respeto por
  movimiento reducido. La aprobación sigue requiriendo las decisiones ya existentes.

## Preservación del proyecto

La auditoría compara el código con el respaldo previo al rediseño. El reductor y los handlers
`atender`, `decidir` y `usarEjemplo` conservan sus bytes. Las llamadas HTTP, sus argumentos,
el estado operativo y la propagación de roles, citas y decisiones permanecen iguales.
Los nuevos controles de menú y foco pertenecen a presentación.

Se verificaron los hashes de `demo/src/api.js`, API Python, almacenamiento de captura,
gestor de evaluación y CLI contra la validación anterior. También coinciden las fuentes y
los hashes del banco congelado. Los cambios del rediseño se limitan a componentes, estilos,
fuente y documentación visual. La copia de trabajo ya tenía cambios de fases anteriores;
se preservaron.

## Verificación

- Build de producción con Node 24.21.0 / Vite 8.3.8: correcto.
- `git diff --check`: correcto.
- [Auditoría estática](auditoria_integracion.json) y [comprobación final](validacion.json).
- [Nueve escenarios de captura](qa_navegador.json): edición, navegación, teclado, guardado,
  recarga, conflictos, validación, congelación y evaluación falsa.
- [Ocho grupos de interacción](qa_flujos.json), repetidos también con
  [viewport móvil](movil_modales/qa_flujos.json): envío, JSON, trazas, citas N1/N2, enlaces PDF,
  denegación, abstención, cuatro payloads de aprobación, pausa, fallas, ejemplos, métricas,
  navegación, foco y movimiento reducido.
- Anchos 320, 375, 768 y 1440 px sin desbordamiento horizontal. Se inspeccionaron las imágenes
  de escritorio, captura móvil, documentos y aprobación.

Los ensayos usaron respuestas simuladas y archivos de captura bajo `/tmp`. Los resultados
históricos se utilizaron únicamente para comprobar su representación con procedencia explícita;
no son métricas nuevas. No se ejecutaron inferencias reales.

La aplicación real se comprobó en `http://127.0.0.1:8000`: captura **0/20**, autoría pendiente,
sin fixtures en el conjunto del proyecto. [Vista de atención](app_real_atencion.png),
[captura](app_real_captura.png) y [móvil](app_real_movil.png).

El cambio está aplicado localmente. PRO Procesos permanece como referencia de lectura;
no se hizo commit, push ni despliegue.
