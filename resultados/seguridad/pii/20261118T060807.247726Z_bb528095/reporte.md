# Evaluación local de PII sembrada

Muestra sintética de IA para seguridad; no sustituye los 20 tickets manuales.

SHA-256 del banco: `bb5280953bece83a5861ea873f5424c8d94ea25594aeeed555525c74548d6d06`.

Textos: 30. Entidades: 56.
TP/FP/FN exactos: 55/3/1.
Precisión: 0.9483; recall: 0.9821; F1: 0.9649.
Recall de redacción efectiva: 0.9821.
Meta ≥ 0.95: cumplida.

| Tipo | TP | FP | FN | Precisión | Recall | F1 | Recall efectivo |
|---|---:|---:|---:|---:|---:|---:|---:|
| CARD | 5 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| DPI | 7 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| EMAIL | 10 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| PERSON | 24 | 3 | 1 | 0.8889 | 0.9600 | 0.9231 | 0.9600 |
| PHONE | 9 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

Fragmentos técnicos afectados: 1/24.
Detecciones sobre esos negativos: 1.
Textos con redacción no íntegra: 0.

Los falsos positivos/negativos se conservan por ID, tipo y offsets en casos.jsonl.
Las métricas exigen coincidencia exacta 1:1; no se ajustó el detector contra esta muestra.
El tamaño y origen sintético del banco limitan la generalización de estos resultados.
