# Ejecutar PILAS en esta Mac

El entorno Python del proyecto está en `.venv/`. La configuración y las claves de PostgreSQL se guardan en `.env`, fuera de Git y con permisos `600`. Codex usa la sesión local de ChatGPT; no se configuraron API keys. Los modelos BGE-M3, MiniLM y el reranker están descargados en la caché local.

## Abrir la aplicación

Desde la carpeta del proyecto:

```bash
docker compose up -d
./scripts/iniciar_demo.sh
```

Después abrir `http://localhost:8000`. Si el servidor ya está ejecutándose, basta con abrir esa dirección. El motor de atención se carga al enviar el primer ticket; la captura y la consulta de casos sintéticos funcionan antes de esa carga.

La reconstrucción de la UI requiere Node 24:

```bash
PATH=/opt/homebrew/opt/node@24/bin:$PATH npm run build --prefix demo
```

## Perfil de esta evaluación

La corrida actual usa CPU, modelos FP32, lotes de 16 en embeddings y 32 en reranking, con ocho hilos de PyTorch. La base dedicada es `tickets_rag_final_normal_20261118`: conserva 240 tickets y 564 fragmentos por índice; la base original y los intentos anteriores permanecen separados. El lanzador trabaja con los pesos descargados, en modo offline de Hugging Face por defecto. Para descargar pesos en otra instalación se debe preparar primero la caché o desactivar explícitamente ese modo.

El control público de Outlook con la configuración normal completó clasificación, recuperación y generación con dos citas en 65.409 segundos; su única búsqueda terminó en 15.551. Un control previo de CPU con dos hilos/lote4 había tardado 97.177 segundos, con un timeout y una reformulación exitosa. Ese control previo también completó juez/Ragas y un replay idéntico sin nuevas inferencias. Son controles de integración, no las métricas del banco completo.

Los ensayos de MPS y FP16 se conservan como diagnósticos; no se presentan como el perfil de la corrida final. En esta Mac de 8 GB, la medición se realiza con otros cinco contenedores locales pausados por autorización del usuario. Esos servicios se restaurarán al terminar; el registro está en `resultados/puesta_en_marcha/servicios_temporales.json`.

## Qué datos son sintéticos

**Casos sintéticos** muestra los veinte textos `SYN-01` a `SYN-20`, sus etiquetas de referencia, justificaciones y resultados guardados. La vista solo hace consultas GET; actualizarla no inicia evaluaciones. Los textos y las etiquetas son de IA y no acreditan el requisito de veinte tickets de autoría humana.

**Tickets de evaluación** conserva el formulario para el conjunto humano independiente. No se rellenó con textos sintéticos ni se marcaron declaraciones de autoría humana en su nombre.

## Banco oficial y reanudación

Una salida nueva conserva por separado la primera corrida de una configuración:

```bash
./scripts/evaluar_final_local.sh --salida resultados/codex_suscripcion/evaluacion/banco
```

Para continuar la corrida canónica guardada, usar el lanzador que compara la huella en el mismo formato JSON del manifiesto:

```bash
PYTHONPATH=src TOKENIZERS_PARALLELISM=false RAGAS_DO_NOT_TRACK=true \
  PYTORCH_ENABLE_MPS_FALLBACK=0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  caffeinate -is .venv/bin/python scripts/reanudar_banco_local.py
```

El evaluador verifica las huellas del banco, corpus, código, configuración, modelos, hardware e índice vectorial. Conserva los votos terminados, las etapas del juez/Ragas y las acciones ya observadas. Un envío sin desenlace bloquea la reanudación automática. El segundo intento del caso R11 de BM25 quedó autorizado y documentado en `resultados/cierre_tecnico/continuacion_r11_20261118T193728Z.json`. El journal privado conserva el registro original. El uso y el tiempo de ese primer intento siguen desconocidos.

En macOS el lanzador mantiene la máquina despierta solo mientras se ejecuta la evaluación. No modifica permanentemente las preferencias de energía.

## Clasificación de los veinte sintéticos

```bash
PYTHONPATH=src RAGAS_DO_NOT_TRACK=true .venv/bin/python scripts/evaluar_sinteticos.py --solo-validar
PYTHONPATH=src RAGAS_DO_NOT_TRACK=true caffeinate -is .venv/bin/python scripts/evaluar_sinteticos.py
```

Cada corrida anuncia su UUID. `--reanudar UUID` recupera sus resultados; un intento iniciado sin resultado requiere revisar el fallo antes de usar `--reintentar-pendiente`. Ese segundo intento puede consumir cuota adicional y queda registrado. El conjunto se mantiene fuera del entrenamiento, del índice y de los ejemplos del prompt.

La configuración local amplía el plazo de inferencia a 240 segundos después de observar timeouts con 90; no modifica el plazo de las herramientas. Se mantienen las verificaciones de autenticación, uso incluido, ausencia de créditos y umbral del 80 %. Las inferencias consumen la cuota de la suscripción aunque el costo incremental de API sea cero.

Los reportes nuevos no sustituyen los resultados históricos de Anthropic. Las métricas parciales se identifican como tales. La revisión técnica de IA no se registra como revisión humana.

## Caché opcional de MPS

`TICKETS_VACIAR_CACHE_MPS` acepta únicamente `true` o `false` (vacío equivale a `false`). Está
desactivado por defecto. Solo actúa cuando el dispositivo seleccionado es `mps`; no cambia el
comportamiento de CPU/CUDA. La configuración queda registrada en la huella del evaluador.

Con la opción activa, después de construir cada modelo se ejecuta `gc.collect()`, se sincroniza
MPS y se vacía la caché no ocupada de preparación mientras el modelo conserva sus referencias. Tras cada
`encode` o `predict`, cuando la salida ya se convirtió a numpy en CPU, se sincroniza MPS y se
liberan las reservas **no ocupadas** del allocator mediante `torch.mps.empty_cache()`. La limpieza
también se intenta si la operación falla; si no se puede sincronizar, no se vacía anticipadamente
la caché. Los pesos siguen retenidos, con los mismos dispositivos, precisiones y límites de tokens;
no se borran las cachés de modelos ni se modifica la sigmoide.

Es una opción de memoria para un control de hardware, no una mejora de latencia demostrada:
puede reducir reservas para otras aplicaciones y también añadir sincronizaciones o reasignaciones.
No libera pesos todavía en uso ni garantiza resolver paginación o falta de RAM. Para probarla,
usar un proceso nuevo y controles públicos ajenos al banco antes de congelar su huella; cambiarla
invalida la reanudación de una corrida previa con otra configuración. Este cambio no activa el
parámetro en el `.env` real ni ejecuta una nueva prueba GPU automáticamente.
