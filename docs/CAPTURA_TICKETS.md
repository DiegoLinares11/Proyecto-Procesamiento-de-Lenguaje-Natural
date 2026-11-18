# Tickets de evaluación desde la aplicación

La pestaña **Tickets de evaluación** permite escribir, etiquetar y guardar los veinte tickets
escritos por una persona sin llenar una hoja. **Casos sintéticos** muestra los 20 tickets simulados
con IA y sus resultados. **Atender un ticket** usa el modelo para resolver una solicitud y
**Evaluación** muestra las métricas del banco general.

## Abrir la pantalla

Con las dependencias del proyecto instaladas:

```bash
uv sync --locked
cd demo && npm install && npm run build && cd ..
uv run uvicorn tickets_rag.api:app --host 127.0.0.1 --port 8000
```

Abrir `http://127.0.0.1:8000` y elegir **Tickets de evaluación**. La captura no necesita PostgreSQL,
embeddings ni una sesión de Codex: abrir, escribir, guardar, validar y congelar no hacen inferencias.
El motor de atención se prepara al atender el primer ticket; su base y modelos siguen siendo
necesarios para esa función. Una falla de ese motor no impide continuar la captura.

## Escribir y guardar

1. Seleccionar `MAN-01` a `MAN-20` y escribir el texto humano original.
2. Elegir su categoría y prioridad correctas según la ayuda de etiquetado. No se predicen ni
   completan automáticamente.
3. En **Datos del conjunto**, ingresar el nombre de quien escribió los tickets y la fecha de
   redacción. Los casos se reservan para evaluar el clasificador.
4. Pulsar **Guardar borrador**. Se admiten borradores incompletos, que se recuperan al recargar.
   Cambiar de sección conserva los cambios aún sin guardar dentro de esa pestaña del navegador.

El contador distingue los tickets con texto y ambas etiquetas. Para este conjunto, la persona
que escribe los casos debe ser distinta de quien elaboró F3. Usar situaciones ficticias, sin
información personal real ni contraseñas.

Si otra pestaña guarda antes, la aplicación conserva los cambios locales y muestra un conflicto;
no sobrescribe el borrador más reciente. El botón para descartar y recargar es una decisión
explícita del usuario. El archivo local usa revisión, bloqueo y reemplazo atómico.

## Validar y reservar

Guardar, pulsar **Validar 20 tickets**, corregir las causas indicadas y volver a guardar/validar.
La comprobación reutiliza el importador del proyecto. Verifica los veinte textos, las etiquetas,
el nombre de quien redactó los casos, la fecha, las referencias y los duplicados exactos tras
normalizar los textos. El nombre y la fecha registran los datos proporcionados en el formulario.

Tras una validación correcta, **Reservar conjunto** crea el mismo JSONL y manifiesto que la CLI,
con copias del texto y autoría recibidos. Cierra la edición de ese conjunto y evita sobrescribir
una carpeta congelada existente. Los veinte casos se reservan fuera del entrenamiento, ejemplos
del prompt e índice.

Los borradores privados quedan en `evaluacion/tickets_manuales/borrador_local/`, ignorado por Git.
El conjunto final queda en `evaluacion/tickets_manuales/congelado/`. Los originales de F3 y la
plantilla CSV se conservan. La recepción por CSV sigue disponible como alternativa.

## Evaluar el conjunto

Una vez congelado aparece **Evaluar conjunto**. Este botón inicia el clasificador con la variante
fijada `juegos_criterios`, compara Codex y TF-IDF y **consume cuota incluida de ChatGPT/Codex**.
Necesita la sesión local y los modelos PII instalados; la clasificación manual no necesita SQL.
No compra créditos ni usa API keys ni cambia de proveedor: conserva las guardas del adaptador.

La evaluación no se inicia al abrir, guardar, congelar ni consultar el avance. La página muestra
cuántos casos terminaron y, cuando hay un resultado completo verificado, el macro-F1 de categoría
y prioridad de ambos clasificadores. No muestra métricas parciales como si fueran definitivas.

El primer intento y cada resultado parcial se conservan. Recargar o abrir otra pestaña no permite
repetirlo, aunque se reordenen las mismas veinte filas. Si el proceso se creó y falló, sus parciales
quedan conservados; no se vuelve a medir desde cero. Sólo un fallo de arranque confirmado antes
de crear proceso permite pulsar de nuevo el inicio. Consultar el estado nunca reintenta.

Los resultados siguen bajo `resultados/codex_suscripcion/herramientas/manuales/<identidad>/`.
El control local de la ejecución está en `herramientas/.web/`, ignorado por Git. Los resultados
históricos y los del banco general permanecen separados.
