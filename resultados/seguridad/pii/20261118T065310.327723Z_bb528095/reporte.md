# Evaluación local de PII sembrada

Muestra sintética de IA para seguridad; no sustituye los 20 tickets manuales.

SHA-256 del banco: `bb5280953bece83a5861ea873f5424c8d94ea25594aeeed555525c74548d6d06`.

Textos: 30. Entidades: 56.
TP/FP/FN exactos: 55/2/1.
Precisión: 0.9649; recall: 0.9821; F1: 0.9735.
Recall de redacción efectiva: 0.9821.
Meta ≥ 0.95: cumplida.

| Tipo | TP | FP | FN | Precisión | Recall | F1 | Recall efectivo |
|---|---:|---:|---:|---:|---:|---:|---:|
| CARD | 5 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| DPI | 7 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| EMAIL | 10 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| PERSON | 24 | 2 | 1 | 0.9231 | 0.9600 | 0.9412 | 0.9600 |
| PHONE | 9 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

Fragmentos técnicos afectados: 0/24.
Detecciones sobre esos negativos: 0.
Textos con redacción no íntegra: 0.

Los falsos positivos/negativos se conservan por ID, tipo y offsets en casos.jsonl.
Las métricas exigen coincidencia exacta 1:1 y corresponden a la configuración y hashes del manifiesto.
Se conservan las corridas anteriores; repetir este banco con una configuración distinta no constituye un nuevo holdout ciego.
El tamaño y origen sintético del banco limitan la generalización de estos resultados.
