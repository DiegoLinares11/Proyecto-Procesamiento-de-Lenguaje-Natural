// Comunicación con la API de FastAPI. Los tickets responden con Server-Sent Events: cada paso del grafo
// llega como una línea "data: {...}" en cuanto termina, así la página muestra el avance en vivo.

async function leerEventos(respuesta, alEvento) {
  if (!respuesta.ok) {
    const detalle = await respuesta.text()
    throw new Error(`La API respondió ${respuesta.status}: ${detalle}`)
  }
  const lector = respuesta.body.getReader()
  const decodificador = new TextDecoder()
  let pendiente = ''
  for (;;) {
    const { value, done } = await lector.read()
    if (done) break
    pendiente += decodificador.decode(value, { stream: true })
    let corte
    while ((corte = pendiente.indexOf('\n\n')) >= 0) {
      const bloque = pendiente.slice(0, corte)
      pendiente = pendiente.slice(corte + 2)
      for (const linea of bloque.split('\n')) {
        if (linea.startsWith('data: ')) alEvento(JSON.parse(linea.slice(6)))
      }
    }
  }
}

function enviar(url, cuerpo) {
  return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo) })
}

export async function atenderTicket({ texto, rol, falla }, alEvento) {
  await leerEventos(await enviar('/api/tickets', { texto, rol, falla }), alEvento)
}

export async function enviarDecision(hilo, decision, alEvento) {
  await leerEventos(await enviar(`/api/tickets/${hilo}/decision`, decision), alEvento)
}

export async function obtener(url) {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}
