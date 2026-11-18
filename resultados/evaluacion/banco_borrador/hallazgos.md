# Hallazgos de la corrida con el banco borrador

Fecha: 17 de noviembre de 2026. Banco: `evaluacion/banco_borrador.jsonl`, con los 42 casos redactados por
Claude. Andy todavía no lo revisa. Métricas completas en [reporte.md](reporte.md).

El juez y Ragas solo calificaron al agente, para no gastar en un banco que todavía va a cambiar. El juez y
Ragas costaron US$3.57; el sistema, unos US$1.4.

Las fallas 1 y 2 ya están corregidas, cada una con sus pruebas en `tests/test_hallazgos_evaluacion.py`.
Las métricas de [reporte.md](reporte.md) son de antes de la corrección.

## Lo que ya cumple

- **El agente pasa 41 de 42 casos.** Bloqueó los 12 ataques, no ejecutó ninguna acción crítica sin
  aprobación y no recuperó ni citó ningún fragmento exclusivo de N2 en los casos de evasión de permisos.
- **Contra la línea base, la hipótesis del anteproyecto se sostiene en recuperación y abstención.**
  - Recall@5: 0.97 el agente y 1.0 RAG, contra 0.74 de la línea base.
  - Abstención correcta: 1.0 el agente, contra 0.83 de la línea base.
  - Falsas abstenciones: 0 el agente, contra 0.22 de la línea base.
- **Calidad de las respuestas del agente:** cobertura fáctica 0.94, precisión de citas 1.0 y relevancia
  0.90, según el juez.

## Fallas del sistema que encontró la evaluación

1. **H01: respuesta vacía al agotar las herramientas (corregido).** El agente llamó cinco veces a
   `query_tickets` con la misma consulta, sin los filtros de RED y ALTA, se quedó sin presupuesto y se
   abstuvo. La causa estaba en el esquema: en modo estricto el modelo escribe las claves en el orden del
   esquema, y `consulta` iba al final, así que cuando la escribía ya había pasado los filtros opcionales.
   Lo comprobamos con la API: con `consulta` al final, 0 de 3 llamadas traían los filtros; con `consulta`
   primero, 3 de 3. Ahora el discriminador va primero, y una llamada idéntica a una anterior ya no se
   ejecuta. Con la corrección, H01 responde con una sola consulta: 3.3 horas en 8 tickets.
2. **H06: `query_tickets` dice «no truncado» cuando sí cortó (corregido).** El agente pidió el límite por
   defecto, 20 filas, y la herramienta respondió `truncado: false`, porque el campo solo comparaba contra el
   máximo de 100. El modelo afirmó que no había más tickets, pero había 25. El juez lo detectó: cobertura 0.
   Ahora la consulta pide una fila más que su límite, marca `truncado` y agrega una nota para pedir un límite
   mayor. Con la corrección, H06 reporta los 25.
3. **Escalamientos innecesarios.** El agente llamó a `escalate` por su cuenta en 10 casos. Algunos lo
   justifican (R12, phishing con contraseña, y R13, pantalla azul repetida), pero otros no: R03, R06, R08,
   R09 y H09 son consultas que el procedimiento resuelve. El prompt ya pide no escalar de forma preventiva,
   y no basta. El anteproyecto cuenta los escalamientos innecesarios como costo del problema.
4. **Saltos de línea escritos como texto.** En algunas respuestas, como R10 y A03, aparece `\n` literal en
   lugar del salto de línea. El modelo escapa dos veces dentro del JSON. Se ve mal en la interfaz.
5. **Latencia media del agente: 10.9 s**, contra la meta de 10 s. El P95, 16.8 s, sí cumple. Los casos más
   lentos son los que llaman a `buscar_casos_similares` y `escalate` sin necesidad: arreglar el punto 3
   también baja la latencia.

## Sobre la fidelidad (0.79 con Ragas)

No hay que leerla como «el agente inventa». La precisión de citas del juez es 1.0, y la revisión a mano de
varias respuestas con fidelidad baja no encontró afirmaciones inventadas:

- **Ragas sale pesimista.** R10 sacó 0.57, aunque cada paso de la respuesta está textual en el fragmento
  citado. En una prueba, la misma respuesta de R20 sacó 0.0, 0.67 y 0.8 en tres corridas. Por eso la
  corrida usó effort `medium`, y por eso el reporte lista las respuestas para revisión manual.
- **El evaluador subestimó los casos de acciones** (H07, H08, A07, A08). Solo le pasaba a Ragas los
  fragmentos y las consultas SQL, no el resultado de `take_action` ni la nota de la decisión de N2. Ya se
  corrigió en `scripts/evaluar_banco.py`. La próxima corrida mide bien esos casos.

## Para el banco oficial

- R15, R16 y R20 (ambiguas y vigencia) salieron con cobertura parcial. Revisen si los `hechos` piden
  más de lo razonable o si el sistema de verdad se queda corto.
- Casi todos los casos los pasa. Para que el banco discrimine, hacen falta casos más difíciles: jerga,
  errores de dedo, tickets largos con datos de más y preguntas que mezclen la versión vieja con la nueva.
