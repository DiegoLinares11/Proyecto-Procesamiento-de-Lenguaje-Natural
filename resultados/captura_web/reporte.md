# Captura y evaluación de tickets humanos desde el frontend

18 de noviembre de 2026. Se agregó la pestaña **Tickets de evaluación** a la demo existente.
Permite capturar los veinte textos, categoría, prioridad y autoría, guardar borradores y validar
o congelar el conjunto. La hoja CSV se conserva como alternativa; no es necesaria para este flujo.

## Comportamiento

- Cada caso `MAN-01`–`MAN-20` tiene texto humano y etiquetas manuales. La interfaz no genera textos,
  sugiere etiquetas ni envía casos al modelo al guardar. Muestra progreso y criterios de etiquetado.
- El borrador se guarda en el backend local, se recupera al recargar y se mantiene en memoria al
  cambiar de sección. Las revisiones evitan sobrescribir cambios guardados desde otra pestaña.
- Autoría, fecha y seis declaraciones permanecen a cargo de la persona. Se reutilizan los mismos
  validadores del importador; el contador 20/20 no acredita por sí solo independencia o autoría.
- La congelación verifica banco y referencias, usa archivos privados y una carpeta exclusiva,
  conserva el conjunto y bloquea su edición. No modifica F3, índices ni resultados históricos.
- Tras congelar aparece el inicio explícito de evaluación. Usa la variante `juegos_criterios`,
  muestra progreso y macro-F1 de categoría/prioridad de Codex y TF-IDF al terminar con evidencia
  coherente. **Iniciar sí consume cuota incluida**; guardar/validar/congelar/consultar no infieren.
- El proceso reutiliza la CLI y sus guardas de sesión/cuota. Hay una reserva persistente antes
  del arranque; consultar o reiniciar la API no permite repetir un intento ni descartar parciales.
  Se rechazan artefactos incompletos, hashes cambiados y resultados inconsistentes.
- La captura inicia sin PostgreSQL. El motor del agente se prepara al atender el primer ticket;
  sus fallos devuelven un error seguro y dejan disponible la captura. Las rutas de captura usan
  JSON y restricciones de host/origen local para impedir disparos desde sitios ajenos.

## Verificación

[Suite completa](suite.json): **452 pruebas aprobadas y 20 omitidas por PostgreSQL**, salida externa
0. Incluye persistencia, bloqueo concurrente, errores sin textos privados,
congelación, integridad, procesos falsos, primer intento, progreso y restricciones de origen.

El build de producción pasó con Node 24.21.0 y Vite 8.3.8, y `git diff --check` pasó.
La revisión de navegador usó Chrome con Playwright y un servidor de QA separado en puerto 8008,
archivos bajo `/tmp` y evaluación falsa. No se llamó a Codex ni se generaron tickets humanos del
proyecto. [Registro del flujo](qa_navegador.json):

1. Carga sin PostgreSQL ni modelos.
2. Edición y navegación sin pérdida de cambios.
3. Guardado mediante teclado y recuperación tras recargar.
4. Conflicto entre dos pestañas sin sobrescritura.
5. Rechazo de conjunto incompleto.
6. Captura, validación y congelación de veinte fixtures aislados.
7. Escritorio 1440 px, tableta 768 px y móvil 375 px, sin desbordamiento horizontal.
8. Edición cerrada y recuperación del congelado.
9. Inicio de evaluación falsa exclusivamente por clic, progreso y presentación de resultados.

Se inspeccionaron capturas por viewport y se comprobó navegación por teclado. Las imágenes de
fixtures están identificadas como QA y no constituyen métricas académicas. La
[pantalla lista](pantalla_lista.png) corresponde a la aplicación real: **0/20**, textos y autoría
vacíos, sin errores JavaScript. El conjunto humano congelado del proyecto sigue sin existir.

## Uso

Abrir `http://127.0.0.1:8000` y elegir **Tickets de evaluación**. La
[guía](../../docs/CAPTURA_TICKETS.md) detalla guardar, validar, congelar y evaluar.
Faltan los aportes humanos y la evaluación real con esos datos; este QA no los sustituye.
Los cambios están locales; no se hizo commit ni push.
