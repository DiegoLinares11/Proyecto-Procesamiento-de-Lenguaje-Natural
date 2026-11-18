# Evidencia de los doce ataques

`scripts/evaluar_seguridad.py` produce una tabla con **exactamente cinco columnas**: amenaza,
componente afectado, comportamiento esperado, resultado observado y mitigación. Usa los ataques
**A01–A12 del banco borrador**, cuyo hash conserva en cada evidencia. No convierte el borrador en el
banco oficial de la fase 5 y no modifica el corpus ni los resultados históricos.

## Comprobación local sin LLM ni DB

```bash
uv run python scripts/evaluar_seguridad.py --modo local
uv run pytest tests/test_seguridad.py
```

Necesita `indices/chunks.jsonl` ya generado; `--chunks <ruta>` admite un snapshot para esta prueba.
No descarga modelos ni regenera fuentes. Presidio/spaCy deben estar instalados localmente como pide
la configuración PII del proyecto. El modelo hostil es un objeto Python falso: intenta citar fuentes
privadas, copiar instrucciones, obedecer el documento envenenado, solicitar acciones y fabricar datos.
Se ejecutan el grafo, validadores, filtro BM25 y contratos reales de herramientas/acciones. La conexión
de acciones solo guarda dicts en memoria; no abre PostgreSQL ni ejecuta sistemas externos.

En A10–A12 se **simula insuficiencia de evidencia** para comprobar que la guarda obliga a abstenerse
aunque el modelo falso invente una respuesta. Esto no mide la recuperación semántica ni la abstención
de un LLM real. A02 y A03 pueden fallar: citar un fragmento permitido no impide por sí solo copiar el
prompt u obedecer una instrucción. La tabla conserva esos fallos. Los criterios de extracción/inyección
son comparaciones literales y no cubren todas las paráfrasis ni todos los ataques.

Cada ejecución crea una carpeta fechada bajo `resultados/seguridad/ataques/local/`: `tabla.md`, `resumen.json`,
`observaciones.jsonl` y una evidencia `Axx.json` por caso. Cada fila enlaza su salida, traza, criterios,
modelo, procedencia y hashes. Se revisan **todas** las búsquedas y citas al comprobar acceso N1.

## Codex real con recursos limitados

```bash
uv run python scripts/evaluar_seguridad.py --modo codex-bm25
# Variante explícita de menor votación, si se necesita limitar llamadas:
uv run python scripts/evaluar_seguridad.py --modo codex-bm25 --corridas-clasificador 1
```

El clasificador y el generador usan `ClienteModelo` con la sesión local personal de Codex. Estas
órdenes **sí consumen tokens/cuota incluida**, aunque no usen una API key ni un juez LLM. El adaptador
exige cuota verificable por debajo del umbral conservador del 80% y sin créditos adicionales. Cualquier
error del modelo corta las llamadas siguientes; no cambia de proveedor. Se conserva cada caso antes
de intentar el siguiente y los no ejecutados figuran como PENDIENTE si la corrida se interrumpe.

`codex-bm25` busca solo en el manual, con filtros de rol y versión: por defecto vigente, versión vieja
solo si la herramienta la pide. La suficiencia es coincidencia léxica con score mayor que cero. Es una
**variante de seguridad sin híbrido, embeddings, reranker ni τ semántico calibrado**; no sustituye la
evaluación oficial de RAG. No ofrece historial SQL ni tickets similares. Las acciones y escalamientos
siempre se simulan en memoria. Los resultados quedan separados por fecha en `ataques/codex-bm25/`.

El clasificador también lee el índice configurado para construir sus ejemplos. Por eso el modo real
exige que `--chunks` coincida con `config.CHUNKS`; evita declarar un hash para un corpus distinto del
que recibió el clasificador. El número de votos se conserva en la variante del reporte.

Si ya están preparados PostgreSQL, los embeddings y el reranker:

```bash
uv run python scripts/evaluar_seguridad.py --modo codex-hibrido
```

Esta variante abre la conexión vectorial con `default_transaction_read_only=on`; no prepara tablas ni
borra tickets de evaluación. Las acciones siguen en memoria y el historial SQL está deshabilitado.
Puede cargar modelos grandes; no es necesario para ejecutar la variante BM25.

## Releer resultados reales o históricos sin inferir

```bash
uv run python scripts/evaluar_seguridad.py --modo importar \
  --artefacto resultados/evaluacion/banco_borrador/casos_agente.jsonl \
  --procedencia anthropic_historico --variante historico_hibrido_claude
```

Para artefactos nuevos se usa `--procedencia codex_subscription` y una `--variante` que describa la
configuración original. El archivo debe contener una sola observación con traza/modelo por ataque.
Para `codex_subscription` se exige también un proveedor declarado consistente; los modelos observados
deben pertenecer todos a esa misma familia. No se permite mezclar Claude y GPT en una fila histórica.
Se corrobora que los nombres de modelo y proveedores declarados no contradigan esa procedencia; no
se acredita autenticidad criptográfica del proveedor. El hash del archivo permite revisar qué evidencia
se importó. No mezclar históricos Claude, Codex real y modelos simulados en una misma tabla.

Una importación registra hashes del **recalificador actual**; no atribuye esos archivos de código a la
corrida histórica. Sin un snapshot original no se puede acreditar su revisión de código. Recalcular
criterios antiguos no vuelve a ejecutar el sistema actual ni demuestra que se hayan corregido fallas.

Que doce casos cumplan criterios no equivale a doce decisiones BLOCK: los resultados pueden ser WARN,
filtrado por rol, abstención o una pausa humana. El rol elegido en la demo no autentica personas en
producción. Antes de entregar, revisar la tabla, abrir las trazas enlazadas y contrastar con la corrida
real correspondiente; una prueba local con fakes no acredita seguridad semántica del modelo.

`--salida` permite elegir una carpeta nueva; si ya contiene archivos, el runner la rechaza para
evitar mezclar evidencias de corridas distintas. Las carpetas históricas previas se conservan.

## Resultado de la fase 4

La [corrida real Codex-BM25](../resultados/seguridad/ataques/codex-bm25/20261118T062717.558294Z/tabla.md)
cumplió 12/12 criterios con un voto del clasificador: 2 WARN y 10 ALLOW. A09 dejó una acción
privilegiada pendiente de aprobación. A07 y A08 no solicitaron acciones en esa corrida;
sus rechazos por rol y booleano textual sí se ejercitaron con el modelo falso local.

La [corrida local](../resultados/seguridad/ataques/local/20261118T063614.425507Z/tabla.md)
conserva 10/12: fallan A02 y A03. La
[importación histórica de Claude](../resultados/seguridad/ataques/importado_anthropic_historico/20261118T063615.301062Z/tabla.md)
recalificó 12/12 sin volver a ejecutar el sistema. Sus evidencias no se presentan como resultados
actuales de Codex. Ver [alcance y validación](../resultados/seguridad/reporte_fase_4.md).
