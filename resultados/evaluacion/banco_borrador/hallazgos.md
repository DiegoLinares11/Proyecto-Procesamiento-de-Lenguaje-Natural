# Hallazgos de la corrida con el banco borrador

Fecha: 17 de noviembre de 2026. Banco: `evaluacion/banco_borrador.jsonl`, con los 42 casos redactados por
Claude. Andy todavía no lo revisa. Métricas completas en [reporte.md](reporte.md).

El juez y Ragas solo calificaron al agente, para no gastar en un banco que todavía va a cambiar. El juez y
Ragas costaron US$3.57; el sistema, unos US$1.4.

Las fallas 1, 2 y 3 ya están corregidas, cada una con sus pruebas en `tests/test_hallazgos_evaluacion.py`.
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
3. **Escalamientos innecesarios (corregido).** El agente llamó a `escalate` por su cuenta en 10 casos.
   Algunos lo justifican (R12, phishing con contraseña, y R13, pantalla azul repetida), pero otros no:
   R03, R06, R08, R09 y H09 son consultas que el procedimiento resuelve. Al capturar el motivo de cada
   llamada se vio que la mayoría no eran escalamientos de verdad: el modelo llamaba a `escalate` con
   «placeholder» o con «No procede escalar: el 4.3 se resuelve en N1», y la herramienta lo registraba.

   La corrección tiene tres partes:
   - `escalate` exige una `causa` del procedimiento 8.1 del manual: procedimiento exclusivo de N2, pasos
     agotados, incidente de seguridad, varias personas o acción sensible.
   - Rechaza los motivos que dicen que no hay que escalar, o que están vacíos, antes de escribir en la base.
   - La descripción y el prompt aclaran que un paso condicional («si el problema sigue, escale a N2») va
     en la respuesta y no se ejecuta ahora.

   Resultados con el sistema real:
   - En los 5 casos que no debían escalar, los escalamientos registrados bajaron de 5 de 10 corridas a
     0 de 16.
   - R12 y R13 siguen escalando: 4 de 4.
   - En los 42 casos, los escalamientos del agente bajaron de 10 a 4 (R09, R12, R13 y A01), todos con una
     causa del manual. El más discutible es R09: el agente decidió que restablecer el MFA lo hace N2.

   Queda un detalle: en 4 de 42 casos el modelo todavía intenta una llamada basura. Se rechaza sin efecto,
   pero gasta un turno.
4. **Saltos de línea escritos como texto.** En algunas respuestas, como R10 y A03, aparece `\n` literal en
   lugar del salto de línea. El modelo escapa dos veces dentro del JSON. Se ve mal en la interfaz.
5. **Latencia media del agente: 10.9 s**, contra la meta de 10 s. El P95, 16.8 s, sí cumple. Con la
   corrección del punto 3 bajó a 10.3 s, con P95 de 16.2 s y US$0.024 por ticket. Sigue arriba de la meta.
   Lo que más pesa ahora es `buscar_casos_similares`: el agente lo llama en 13 de 27 casos de
   procedimiento, aunque el manual ya basta. Esos casos tardan 11.4 s en promedio, contra 9.9 s los demás.

En esa misma corrida, Recall@5 del agente salió 0.93 en lugar de 0.97. No tiene que ver con la corrección.
En R13 y R15 el agente formuló distinto su primera búsqueda, y Recall@5 solo mide la primera. Es variación
entre corridas: conviene correr el banco oficial más de una vez y reportar el promedio.

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
