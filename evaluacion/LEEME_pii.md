# Holdout de PII sembrada, versión 1.0

`pii_sembrada.jsonl` contiene 30 textos sintéticos generados con asistencia de IA para
evaluar seguridad. No son tickets escritos a mano, no cuentan para los 20 tickets
independientes del clasificador y no forman parte de F3. Los nombres y contactos se
inventaron; no se consultaron expedientes ni se pretende representar personas reales.
Los teléfonos y DPI tienen formato guatemalteco sintácticamente válido, sin comprobar
titularidad ni existencia. Los DPI incluyen un dígito verificador calculado y terminan
en el código 0101; esto no acredita que sean documentos emitidos.

Las tarjetas son números públicos de sandbox documentados por
[Braintree](https://developer.paypal.com/braintree/docs/guides/credit-cards/testing-go-live/python/),
con separadores alternos y Luhn válido. No se utilizan para realizar transacciones.
Los correos usan el dominio especial
[`.example`, reservado por IANA](https://www.iana.org/domains/root/db/example.html).

## Congelación previa a la evaluación

El archivo se fijó **antes de ejecutar el detector sobre estos textos**. Versión: `1.0`.
SHA-256 de sus bytes UTF-8, incluidos los saltos de línea:

```text
bb5280953bece83a5861ea873f5424c8d94ea25594aeeed555525c74548d6d06
```

El hash también está fijado en `tickets_rag.evaluacion_pii`. El evaluador rechaza otro
contenido; no se recalcula la referencia automáticamente al evaluar. No se modifica el
banco ni se ajustan reglas, umbrales o el modelo con sus resultados. La primera corrida
se conserva en `resultados/seguridad/pii/20261118T060807.247726Z_bb528095/`.

Después de esa corrida, la inspección independiente del corpus de desarrollo reveló
redacción de verbos en español y problemas al procesar documentos en inglés. Se revisó
la configuración general de POS y se añadió un modelo de inglés, sin cambiar este banco
ni ajustar contra sus errores. Las comprobaciones posteriores sobre el mismo archivo
se guardan con un nuevo manifiesto: son evaluaciones de configuraciones versionadas,
**no un nuevo holdout ciego**. Se conservan las métricas de cada versión, sin sustituir
la primera ni atribuirle resultados de otra configuración. Para estimar una mejora de
forma independiente sigue siendo necesario otro holdout que no se haya observado.

Hay 56 entidades: 25 PERSON (en 24 textos), 10 EMAIL, 9 PHONE, 7 DPI y 5 CARD.
Los seis textos restantes carecen de nombres de persona, pero contienen otra PII
sembrada. Se anotaron además 24 fragmentos técnicos que deben conservarse: códigos,
versiones, direcciones de memoria, UUID, rutas, productos, métricas y herramientas.
La muestra es pequeña y sintética: su recall no estima por sí solo la seguridad en
producción ni la cobertura de todas las variantes del español.

## Anotaciones y medición

Cada línea es un objeto con `id`, `version`, `origen`, `categoria`, `texto`, `entidades`
y `negativos`. Cada entidad tiene `tipo`, `inicio` y `fin`. Los offsets cuentan
caracteres Python del texto original, desde cero, con intervalo `[inicio, fin)`;
se mantienen tildes y saltos de línea. Los negativos llevan esos offsets y un `motivo`.
El archivo no incluye resultados ni anotaciones obtenidas del detector.

La métrica principal exige coincidencia **exacta de tipo e intervalo**, con asignación
uno a uno. Un fragmento parcial no es un verdadero positivo. Una detección duplicada
adicional es un falso positivo. Se informa TP/FP/FN, precisión, recall y F1 globales y
por tipo; un denominador vacío produce `null`, no un acierto inventado. Cualquier
solapamiento con un negativo explícito se cuenta aparte y no sustituye el FP global.

La redacción efectiva se acredita únicamente si la salida de `enmascarar` coincide con
la reconstrucción que sustituye cada detección por `[TIPO_REDACTED]` y conserva todo el
resto del texto. Los conteos deben coincidir con las detecciones; estas no pueden
duplicarse ni solaparse. Sólo los TP estrictos de una salida íntegra cuentan para el
recall efectivo. Vaciar el texto, eliminar palabras adicionales o modificarlo de forma
genérica no acredita redacción. Esta prueba comprueba ejecución y fidelidad de la
redacción, además de la capacidad de detección.

## Ejecución local

```sh
uv run python scripts/evaluar_pii.py
```

No se usa un LLM, una API, una clave ni una base de datos. Se necesitan los modelos
locales de spaCy `es_core_news_md` y `en_core_web_md` en versión `3.8.0`, fijados en el
proyecto, y Presidio. Esta muestra se analiza en español; no estima recall en inglés.
El script comprueba la salud y metadatos de la configuración antes de medir y
escribe una carpeta nueva por corrida en `resultados/seguridad/pii/`, con manifiesto,
hash, versiones, métricas y diagnósticos por ID/tipo/offset. El manifiesto versión 2
incluye idioma, modelos/componentes, configuración y filtro de personas declarados,
hashes de código, `pyproject.toml` y `uv.lock`, y versiones/hashes de los archivos
instalados `METADATA`, `meta.json` y `config.cfg` de cada modelo. Estos metadatos no son
un hash de todos los pesos binarios. La primera corrida conserva su manifiesto original
versión 1 y sus metadatos disponibles; no se completa retrospectivamente con información
de una configuración posterior. No registra valores de PII
ni copia el texto al reporte. El manifiesto tiene `estado=fallido` si la salud o la
ejecución falla; en ese caso no publica métricas agregadas como si estuvieran completas.
El manifiesto recoge los errores que Python alcanza a capturar. Una falla nativa al cerrar
puede dejar métricas completas; debe comprobarse también el código de salida externo del proceso.

La salida del proceso es 0 sólo con 30 textos completos, detector local saludable,
salidas íntegras y recall estricto y efectivo de al menos 0.95. Con 56 entidades se
requieren al menos 54 TP exactos. Un incumplimiento conserva evidencia y termina con
código distinto de cero; no se modifica la muestra para alcanzar la meta.

## Resultado de la fase 4

La [comprobación final](../resultados/seguridad/pii/20261118T065310.327723Z_bb528095/reporte.md)
terminó con salida externa 0 en un entorno aislado: TP/FP/FN 55/2/1, recall estricto y efectivo
55/56 (0.9821), PERSON 24/25 (0.96) y 0/24 negativos técnicos afectados.
El [reporte de fase](../resultados/seguridad/reporte_fase_4.md) conserva las corridas anteriores,
el incidente de entorno y los límites de esta muestra. No se modificó el banco congelado.
