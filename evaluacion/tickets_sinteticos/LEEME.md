# Veinte tickets sintéticos de IA

Estos veinte casos fueron redactados y etiquetados por el asistente de IA Codex. Su modelo redactor
exacto no se expone en esta sesión y no se inventa en el manifiesto. No hay una persona autora
declarada ni una revisión humana independiente. **No equivalen a los veinte tickets escritos a mano
del anteproyecto: ese requisito sigue en 0/20.** La captura humana, sus declaraciones y sus archivos
permanecen separados.

Los textos imitan consultas de soporte con estilos distintos, voseo y errores plausibles. Son
ficticios y no contienen datos personales reales incorporados deliberadamente. No se ejecutó un
detector para certificar la ausencia de todas las clases de PII.

| Categoría | Casos |
| --- | ---: |
| ACCESO | 4 |
| CORREO | 4 |
| EQUIPOS | 4 |
| RED | 3 |
| APLICACIONES | 3 |
| OTRO | 2 |

Prioridades: **6 ALTA, 6 MEDIA y 8 BAJA**. Tipos auxiliares: 17 procedimiento, 1 acción y 2 fuera de
dominio. Cada caso justifica sus tres etiquetas. Categoría y prioridad siguen las secciones 1.3 y
1.4 del manual vigente; el tipo sigue el contrato del clasificador. No se corrigen las etiquetas
según lo que predigan los sistemas.

`manifiesto.json` fija el SHA-256 del JSONL, las fuentes de referencia, los chunks y el balance.
Se comprobaron duplicados exactos normalizados con NFC, espacios colapsados y casefold contra F3,
desarrollo y ambos bancos: ninguno. Esto no prueba independencia semántica ni representatividad.
El conjunto queda reservado para evaluación técnica; no se agrega a F3, entrenamiento, ejemplos,
índice, ajuste del prompt ni selección de variantes.

## Comandos

Validar archivos y procedencia, sin NER, sesión, clasificadores ni inferencias:

```sh
uv run python scripts/evaluar_sinteticos.py --solo-validar
```

Medir posteriormente, cuando se autorice la corrida real y la sesión tenga cuota:

```sh
uv run python scripts/evaluar_sinteticos.py
```

El evaluador reutiliza la línea base TF-IDF de palabras/caracteres y regresión logística, con
entrenamiento limitado a F3 `particion=indice`. El LLM recibe solo el texto del caso, nunca su
etiqueta ni justificación. Usa la variante vigente `juegos_criterios`, cinco votos secuenciales,
cinco juegos distintos, criterios extra y esfuerzo `low`. No cambia el proveedor ni el modelo
configurado; la ruta de suscripción sigue consumiendo cuota incluida.

El primer JSON de stdout anuncia el UUID antes de la inferencia. Los artefactos se guardan en
`resultados/codex_suscripcion/clasificador_sinteticos/<UUID>/`:

- `corrida.json`: plan, hashes de código/datos/dependencias, modelo, variante, semillas, cinco
  hashes de prompts, predicciones TF-IDF y estado.
- `mediciones_parciales.jsonl`: eventos de inicio, resultado o error por ticket, con UUID y hash
  de plan. Cada escritura se sincroniza a disco; no guarda textos completos.
- `resumen.json`: macro-F1 por categoría y prioridad para ambos sistemas, errores por ID, tokens,
  latencia LLM y cargo incremental de API de los tickets completados. Un resumen incompleto lo
  indica expresamente; no constituye una medición final. No se inventan tokens de votos fallidos.

Reanudar conservando el UUID y todas las huellas:

```sh
uv run python scripts/evaluar_sinteticos.py --reanudar UUID
```

Los tickets con resultado registrado no se repiten. Si un ticket quedó iniciado sin resultado, el
evaluador se detiene antes de nuevas inferencias: el intento anterior puede haber consumido cuota
o parte de sus cinco votos. Tras revisar los parciales, el reintento explícito es:

```sh
uv run python scripts/evaluar_sinteticos.py --reanudar UUID --reintentar-pendiente
```

No se mezclan UUID, modelos, variantes, prompts o datos cambiados. Un JSONL truncado se rechaza;
no se elimina ni repara automáticamente. El bloqueo del UUID evita ejecuciones concurrentes.

## Estado y límite de interpretación

En la preparación se validaron los veinte casos y la ausencia de duplicados exactos. **No se
ejecutaron inferencias reales ni existen métricas de rendimiento de este conjunto todavía.** Las
pruebas automatizadas usan clasificadores falsos y carpetas temporales; sus números perfectos son
fixtures de prueba, no evidencia de rendimiento del proyecto.

Hay una hipótesis de fallo anterior a la medición: `REGLAS_EXTRA` dice que si la persona todavía
puede trabajar, la prioridad es BAJA; el manual 1.4 define MEDIA cuando hay una alternativa temporal
que permite seguir trabajando. Se conservan los prompts vigentes y las etiquetas del manual para
medir honestamente. Si aparece esa discrepancia, corresponde documentarla en la autopsia; no usar
estos veinte reservados para retocar prompts o etiquetas y presentar luego el ajuste como prueba
independiente. La revisión humana de las anotaciones sigue pendiente.
