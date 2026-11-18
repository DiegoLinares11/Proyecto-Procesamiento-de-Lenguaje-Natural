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

// Captura manual: guardar y validar no llaman modelos. La evaluación requiere un POST explícito.
async function jsonManuales(url, metodo = 'GET', cuerpo) {
  let respuesta
  try {
    respuesta = await fetch(url, {
      method: metodo,
      cache: 'no-store',
      headers: cuerpo === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
    })
  } catch {
    throw new Error('No se pudo conectar con la app. Tus cambios siguen en esta pestaña.')
  }
  const datos = await respuesta.json().catch(() => null)
  if (!respuesta.ok) {
    const detalle = datos?.detail
    const errores = datos?.errores || (typeof detalle === 'object' && detalle?.errores)
    const mensaje = typeof detalle === 'string' ? detalle
      : typeof datos?.mensaje === 'string' ? datos.mensaje
      : respuesta.status === 409 ? 'Hay una versión guardada más reciente. Tus cambios siguen aquí.'
      : `No se pudo completar la operación (${respuesta.status}).`
    const error = new Error(mensaje)
    error.status = respuesta.status
    error.codigo = datos?.codigo
    error.errores = Array.isArray(errores) ? errores.filter((e) => typeof e === 'string') : []
    throw error
  }
  if (!datos) throw new Error('La app devolvió una respuesta vacía. Vuelve a intentarlo.')
  return datos
}

export const obtenerTicketsManuales = () => jsonManuales('/api/tickets-manuales')
export const guardarTicketsManuales = (datos) => jsonManuales('/api/tickets-manuales', 'PUT', datos)
export const validarTicketsManuales = (revision) => jsonManuales('/api/tickets-manuales/validar', 'POST', { revision })
export const congelarTicketsManuales = (revision) => jsonManuales('/api/tickets-manuales/congelar', 'POST', { revision })
export const obtenerEvaluacionManuales = () => jsonManuales('/api/tickets-manuales/evaluacion')
export const evaluarTicketsManuales = () => jsonManuales('/api/tickets-manuales/evaluacion', 'POST', {})
