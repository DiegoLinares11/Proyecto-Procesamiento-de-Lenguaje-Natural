# Veinte tickets humanos independientes

Se evaluaron 20 tickets de autoría humana declarada. La plantilla contiene veinte filas vacías
para nuevas capturas. Los textos y los datos del conjunto evaluado se conservan en la instalación
local. [Resumen de clasificación](../../resultados/cierre_tecnico/clasificador_20_manuales.json).

La sección 12 del anteproyecto reserva 60 tickets de F3 y 20 escritos a mano para evaluar la
clasificación. Estos últimos los escribe una persona ajena a la redacción de F3. La evaluación
de los 20 casos simulados con IA se puede consultar en **Casos sintéticos**.

## Captura desde el frontend

La opción principal es la pestaña **Tickets de evaluación** de la demo. Permite escribir y etiquetar
cada caso, guardar un borrador y registrar el nombre y la fecha en **Datos del conjunto**. La app
permite validar y congelar los veinte sin una hoja de cálculo. Capturar no requiere PostgreSQL ni
hace inferencias. El conjunto congelado es compatible
con el mismo evaluador de esta guía. Después, el botón explícito **Evaluar conjunto** sí consume
cuota y muestra el progreso y los resultados verificados.

Ver [instrucciones de pantalla](../../docs/CAPTURA_TICKETS.md). La recepción CSV descrita a continuación
se conserva como alternativa. No se añaden textos humanos al pulsar un ejemplo de la demo normal.

## Quién y cómo los escribe

Una persona que no haya redactado F3 escribe veinte textos originales en una copia de `plantilla.csv`.
Para que suenen a mensajes de usuarios, los textos deben describir el problema, a quién afecta y si
existe una alternativa temporal. Puede haber errores de escritura. Evitar copiar o adaptar preguntas
de F3, desarrollo, los bancos de evaluación o los casos simulados con IA.

Usar situaciones ficticias, sin nombres, contactos, contraseñas ni otros datos personales reales de
usuarios. El nombre de quien asume la autoría se registra solo en los metadatos de autoría. El validador
no imprime textos ni ese nombre, y no cambia ni corrige los textos recibidos.

Conservar los identificadores `MAN-01` a `MAN-20`. Completar `texto`, `categoria` y `prioridad`:

| Categoría | Criterio del manual 1.3 |
|---|---|
| ACCESO | Cuentas, contraseñas, bloqueos, MFA y permisos |
| CORREO | Outlook, buzón, Teams y correos sospechosos |
| EQUIPOS | Computadoras, impresoras, periféricos y actualizaciones del sistema operativo |
| RED | Internet, Wi-Fi, VPN y cableado |
| APLICACIONES | Instalación de software, SIRA, Office y navegadores |
| OTRO | Otras solicitudes o fuera del alcance de la mesa de ayuda |

Si hay dos problemas, la categoría principal corresponde al que impide trabajar. La prioridad depende
del impacto descrito, no de la insistencia ni de escribir «urgente»:

| Prioridad | Criterio del manual 1.4 |
|---|---|
| ALTA | Sin alternativa para trabajar, varias personas/proceso crítico afectados o posible incidente de seguridad |
| MEDIA | Afecta el trabajo, pero existe una alternativa temporal |
| BAJA | Consulta, solicitud programable o molestia menor |

La sección 12 **no exige una distribución fija** por categoría o prioridad. Se recomienda cubrir las seis
categorías y las tres prioridades. Como orientación para veinte: categorías 4/4/3/3/3/3 y prioridades
7/7/6. No es una cuota obligatoria; el validador registra el balance y avisa si falta alguna clase.

## Datos del conjunto y validación por CSV

Crear `autoria_completa.json` con los campos `autor` (nombre de quien escribió los casos),
`fecha_redaccion` (fecha en formato `YYYY-MM-DD`) y `estado` con valor `declarado`. Los archivos
preparados con el formato anterior conservan sus declaraciones y se validan con ese formato.

```bash
uv run python scripts/preparar_tickets_manuales.py \
  --csv ruta/tickets_completados.csv --autoria ruta/autoria_completa.json --solo-validar
```

Debe existir `evaluacion/banco.jsonl` antes de congelar. El validador exige veinte textos no vacíos y
únicos, las etiquetas válidas y los datos del conjunto. Rechaza coincidencias exactas con F3
(incluidos los 60 de prueba), `validacion_dev.jsonl`, los bancos y los casos simulados con IA si
existen. La comparación se limita a coincidencias exactas después de normalizar Unicode NFC,
espacios y mayúsculas/minúsculas. Los textos quedan reservados como datos de evaluación.

La plantilla vacía y los metadatos pendientes se rechazan y **no crean un JSONL final**.

## Congelar y reservar

Una vez revisados los textos y etiquetas, ejecutar el mismo comando sin `--solo-validar`:

```bash
uv run python scripts/preparar_tickets_manuales.py \
  --csv ruta/tickets_completados.csv --autoria ruta/autoria_completa.json
```

Se crea `evaluacion/tickets_manuales/congelado/` con `tickets.jsonl`, copias exactas del CSV y de los
metadatos, y `manifiesto.json`. Este registra hashes de los tres artefactos, F3, desarrollo, los bancos,
el manifiesto del corpus y el código del validador. Rechaza sobrescribir una carpeta existente.

`tickets.jsonl` expone `ticket_id`, `texto`, `categoria` y `prioridad`, más `particion: manuales`,
`uso: evaluacion_reservada` y `procedencia: humano_declarado`. No requiere `tipo`: se mide macro-F1
por categoría y por prioridad. La función `cargar_manuales()` verifica hashes antes de evaluar.

Estos veinte textos quedan fuera de **entrenamiento, ejemplos few-shot, ajustes del prompt, selección
de variantes e índice**. No copiarlos a `datos/f3_tickets/tickets.jsonl`. El importador solo escribe en la
carpeta nueva de evaluación; la integración del evaluador debe leerlos aparte. Si cambia el corpus o
los archivos congelados, la carga falla para revisar la nueva procedencia. La congelación asegura
integridad verificable por hashes; no es una certificación de quién escribió los textos.

## Validar y medir el clasificador

Cuando exista el conjunto congelado, comprobar su carga sin modelos:

```bash
uv run python scripts/evaluar_clasificador_llm.py --conjunto manuales --solo-validar
```

En la fase 6, con la variante elegida antes de ver estas respuestas:

```bash
uv run python scripts/evaluar_clasificador_llm.py --conjunto manuales --variante juegos_criterios
```

Esta segunda orden sí consume cuota incluida de ChatGPT/Codex. Entrena TF-IDF sólo con F3 del índice;
los textos humanos se usan sólo para prueba y sus etiquetas no se envían al clasificador LLM.
Registra identidad canónica del conjunto, hashes de JSONL/manifiesto y el intento antes de inferir;
reordenar las mismas filas no habilita otra variante. Guarda cada ticket medido en un registro parcial.
Una interrupción conserva ese registro y bloquea repetir desde cero: su continuación debe recuperarse
explícitamente en la fase de evaluación, sin descartar ni volver a medir las respuestas ya obtenidas.
