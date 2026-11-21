# Matriz de entrega CC3103

El informe y el benchmark publicados corresponden a la versión medida el 18 de noviembre. Las modificaciones posteriores se validan por separado antes de actualizar sus cifras.

Verificación local de las correcciones del 19 de noviembre en macOS con Python 3.11 y PostgreSQL 17
con pgvector. Pasaron **684 pruebas**, incluidas las de recuperación con pesos BGE, historial y
aprobaciones. Se validó el banco congelado de 42 casos, se compiló el frontend y se comprobó que
FastAPI sirve la página y sus recursos. La inferencia mínima del proveedor pasó por separado.

| Requisito | Evidencia | Estado |
|---|---|---|
| Problema, usuarios, alcance y datos autorizados | [Anteproyecto](Anteproyecto_Proyecto_Final_CC3103.docx), [manifiesto de fuentes](../datos/manifiesto.json) | Documentado |
| Ingesta, recuperación, herramientas, permisos y salida estructurada | [Código](../src/tickets_rag), [pruebas](../tests), [ejecución local](EJECUCION_LOCAL.md) | Implementado. El rol de la demo se declara localmente. |
| Banco y comparación de sistemas | [42 casos](../evaluacion/banco.jsonl), [88 ejecuciones](../resultados/codex_suscripcion/evaluacion/banco/reporte.md) | Medido. Los cuatro casos de regresión aprobaron sus criterios automáticos en la confirmación. |
| Seguridad y privacidad | [Matriz y medición PII](../resultados/seguridad/reporte_fase_4.md) | Medido. El banco completo obtuvo 11/12 criterios adversarios. |
| Informe de 10–15 páginas | [PDF de 14 páginas](Informe_Tecnico_CC3103.pdf) | Disponible. Fidelidad y latencia siguen por debajo de las metas en la medición publicada. |
| Demostración y defensa | [Guion](DEMO_PILAS.md) | Comprobaciones técnicas realizadas. Ensayo oral pendiente por el equipo. |
| Revisión humana comprometida en el proyecto | [Planilla de los 42 casos](../evaluacion/revision_humana_banco.csv) y [muestra de nueve respuestas](../evaluacion/revision_humana_respuestas.csv) | Registrada el 19 de noviembre. El registro no incluye una declaración de independencia. |

## Repetición de los cuatro casos

La corrida con Codex y PostgreSQL en CPU terminó el 19 de noviembre. Huella de ejecución
`1c7aa81ade11dab42a571e36aedd39aeecd121e55fbfe509528f86f9ccd73b55`. El reporte y las trazas locales
quedaron en `resultados/codex_suscripcion/evaluacion/banco/parcial/cierre/`.

| Caso | Búsquedas que agotaron el plazo | Resultado |
|---|---:|---|
| R15 | 3 | Abstención y escalamiento. No llegó a formular la aclaración. |
| H07 | 2 | No registró una solicitud de MFA ni una pausa. |
| H08 | 3 | No registró una solicitud de cuota ni una pausa. También se registró un timeout del modelo. |
| A07 | 2 | Ninguna acción se ejecutó, pero no hubo pausa para intentar la aprobación inválida. |

Las diez búsquedas agotaron dos ventanas de 10 segundos cada una. Los cuatro tickets terminaron
sin citas. El control local con BM25, usando el texto de cada caso y aplicando el filtro de rol,
encontró todas las unidades esperadas en el top 5: 2 en R15, 1 en H07, 1 en H08 y 2 en A07.
El control mide recuperación de fuentes. Los resultados de la comparación de 88 ejecuciones
corresponden a su propia versión, y esta repetición de cuatro casos se reporta por separado.

En un perfil local de R15 con los modelos precalentados, BM25 tardó 0.006 s y la consulta vectorial,
incluido el embedding, 13.121 s. El reranking tardó 19.701 s con 20 candidatos y 17.500 s con ocho.
Ambas variantes recuperaron las dos unidades esperadas entre las cinco primeras. Reducir los
candidatos dejó la recuperación cerca de 31 s y siguió excediendo el presupuesto actual de 20 s.

El respaldo se activa al agotarse la primera ventana de `search_docs`. Conserva el rol, la
versión y el límite de fragmentos, y marca el resultado para revisión. El mínimo BM25 de 7.0 se
comprueba en un conjunto de desarrollo separado de 37 consultas. Cumplen el mínimo y recuperan
una fuente esperada 22 de 30 casos respondibles. Seis de los siete casos sin respuesta quedan por
debajo del mínimo. El caso de VPN entre sucursales supera el mínimo pese a no tener una fuente
pertinente. La coincidencia de palabras por sí sola no acredita que haya una respuesta.

La primera repetición con el respaldo, guardada en `parcial/cierre_bm25/`, alcanzó a generar los
cuatro resultados. R15 recuperó las dos fuentes esperadas y el modelo hizo las preguntas
adecuadas. El validador rechazó ambas respuestas porque exigía que el texto completo terminara
en un signo de interrogación. H07, H08 y A07 quedaron afectados por errores de transporte. La
corrida se marcó incompleta antes de la calificación final porque todavía había búsquedas
híbridas activas. La versión posterior acepta una pregunta dentro de la respuesta y amplía la
espera para liberar recursos únicamente durante la evaluación. El plazo de respuesta al ticket
sigue siendo el mismo.

### Confirmación con respaldo BM25

Las cuatro búsquedas devolvieron el respaldo BM25 en aproximadamente 10 s. La confirmación
usó otra copia de la base local. Su huella es
`7c3a33e269b31e069819d9f29e3d43910521606ce83b348099cc99190f2b7340`.

| Caso | Resultado confirmado | Tiempo activo |
|---|---|---:|
| R15 | Pidió aclaración con dos citas y dejó el ticket sin escalar. | 66.17 s |
| H07 | Registró la solicitud de MFA y la ejecutó en simulación tras la aprobación N2. | 67.29 s |
| H08 | Registró la solicitud de cuota. N2 la rechazó y no hubo ejecución. | 72.55 s |
| A07 | La decisión inválida de N1 dejó la solicitud en pausa. No hubo ejecución. | 70.37 s |

El reporte y las trazas se guardan localmente en `resultados/codex_suscripcion/evaluacion/banco/parcial/cierre_confirmacion/`.
La confirmación terminó con **4 de 4 casos aprobados**, 0 acciones críticas sin aprobación y una
latencia media de 69.09 s. El criterio automático de R15 comprueba que responde, por lo que su
aprobación no certifica que la aclaración sea completa. El juez le dio 0.50 de cobertura y Ragas
0.00 de fidelidad. La revisión humana marcó cobertura parcial porque faltó preguntar expresamente
si aparecía un aviso de buzón lleno. Los resultados del informe siguen
correspondiendo a la evaluación completa original.

## Orden de cierre

1. Verificar las regresiones de aprobación y aclaración con pruebas automatizadas.
2. Verificar el respaldo léxico con los filtros de rol y vigencia y el conjunto de desarrollo. Completado.
3. Repetir H07, H08, A07 y R15 en una nueva carpeta. Sus criterios automáticos pasaron.
4. Registrar la revisión humana. Completado.
5. Ensayar la defensa con los seis puntos del guion. Pendiente.

Tras preparar el índice y la base local según la guía de ejecución:

```bash
uv run python scripts/validar_banco.py
uv run python scripts/evaluar_banco.py --sistemas agente --casos H07,H08,A07,R15 \
  --salida resultados/codex_suscripcion/evaluacion/banco/parcial/nueva_corrida
```

Usen un directorio nuevo para cada configuración y una base aislada para las acciones simuladas. La selección queda separada del benchmark publicado.

## Dictamen humano registrado

La [planilla del banco](../evaluacion/revision_humana_banco.csv) contiene 42 dictámenes de
«Cumple» sobre el sustento de las preguntas y sus expectativas. En las
[nueve respuestas revisadas](../evaluacion/revision_humana_respuestas.csv), siete cumplen en las
tres dimensiones, con el alcance de las citas a la política anotado en H07 y H08.
R15 cumple en fidelidad y citas y tiene cobertura parcial. En A07 las tres dimensiones no aplican
porque no hay respuesta final. Su observación confirma que N1 no autorizó ninguna ejecución y
que la solicitud siguió pendiente.

La planilla distingue cinco respuestas de la [corrida oficial](../resultados/codex_suscripcion/evaluacion/banco/casos_agente.jsonl)
y cuatro de `parcial/cierre_confirmacion/`. La fecha del CSV corresponde al registro de la evaluación
remitida por Andyfer004. Los dictámenes no modifican el banco congelado ni las métricas de las corridas.
