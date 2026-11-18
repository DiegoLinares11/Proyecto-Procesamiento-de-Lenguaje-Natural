import { useEffect, useRef, useState } from 'react'
import { BarChart3, ChevronDown, ClipboardList, FileText, LoaderCircle, RefreshCw, Sparkles } from 'lucide-react'
import './TicketsSinteticos.css'

const ETIQUETAS = [['categoria', 'Categoría'], ['prioridad', 'Prioridad'], ['tipo', 'Tipo de consulta']]
const TIPOS = { accion: 'Acción', procedimiento: 'Procedimiento', fuera_de_dominio: 'Fuera de dominio' }
const ESTADOS = { sin_iniciar: 'Sin evaluar', ejecutando: 'Evaluación en curso', completo: 'Resultados guardados', incompleto: 'Resultados incompletos', parcial: 'Resultados parciales', no_disponible: 'Sin resultados disponibles' }
const valor = (v) => typeof v === 'string' && v.trim() ? v : 'No registrado'
const f1 = (v) => typeof v === 'number' && Number.isFinite(v) ? v.toFixed(3) : '—'

export default function TicketsSinteticos({ activo = true }) {
  const [datos, setDatos] = useState(null)
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState('')
  const [consulta, setConsulta] = useState(0)
  const [seleccionado, setSeleccionado] = useState(0)
  const titulo = useRef(null)

  useEffect(() => {
    if (!activo) return
    titulo.current?.focus({ preventScroll: true })
    const controlador = new AbortController()
    setCargando(true)
    setError('')
    async function cargar() {
      try {
        // Esta vista solo lee artefactos guardados. No inicia evaluaciones ni inferencias.
        const respuesta = await fetch('/api/tickets-sinteticos', { method: 'GET', cache: 'no-store', signal: controlador.signal })
        if (!respuesta.ok) throw new Error(respuesta.status === 404 ? 'El conjunto sintético todavía no está disponible.' : 'No se pudo consultar el conjunto sintético.')
        const snapshot = await respuesta.json()
        if (!snapshot?.metadatos || !Array.isArray(snapshot.tickets)) throw new Error('No se pudo leer el conjunto sintético guardado.')
        if (controlador.signal.aborted) return
        setDatos(snapshot)
        setSeleccionado((i) => Math.min(i, Math.max(0, snapshot.tickets.length - 1)))
      } catch (e) {
        if (!controlador.signal.aborted) setError(e instanceof TypeError ? 'No se pudo conectar con la app.' : e.message || 'No se pudo leer el conjunto guardado.')
      } finally {
        if (!controlador.signal.aborted) setCargando(false)
      }
    }
    cargar()
    return () => controlador.abort()
  }, [activo, consulta])

  const tickets = datos?.tickets || []
  const ticket = tickets[seleccionado]
  const metadatos = datos?.metadatos || {}

  return (
    <div className="ts-page" aria-busy={cargando}>
      <header className="ts-heading">
        <div>
          <span className="ts-eyebrow">¡PILAS! · Evaluación técnica</span>
          <h1 ref={titulo} tabIndex={-1}>Casos sintéticos</h1>
          <p>Estos tickets simulan solicitudes de usuarios de soporte. Podés revisar cada texto, sus etiquetas y los resultados del clasificador.</p>
        </div>
        <span className="ts-badge"><Sparkles size={14} aria-hidden="true" />Generados por IA</span>
      </header>

      {error && <div className="ts-error" role="alert"><p>{error}</p><button className="ts-button" type="button" onClick={() => setConsulta((v) => v + 1)} disabled={cargando}><RefreshCw size={15} aria-hidden="true" />Reintentar consulta</button></div>}
      {cargando && !datos && <div className="ts-loading" role="status"><LoaderCircle size={20} className="animate-spin" aria-hidden="true" />Consultando casos guardados…</div>}

      {datos && <>
        <div className="ts-toolbar">
          <div><strong>{tickets.length} solicitudes simuladas</strong><span>Etiquetas de referencia de IA</span></div>
          <button className="ts-button" type="button" onClick={() => setConsulta((v) => v + 1)} disabled={cargando}><RefreshCw size={14} className={cargando ? 'animate-spin' : ''} aria-hidden="true" />Actualizar datos guardados</button>
        </div>

        {ticket ? <section className="ts-workspace" aria-label="Explorar los casos sintéticos">
          <nav className="ts-nav" aria-label="Seleccionar caso sintético">
            <div className="ts-nav-heading"><ClipboardList size={17} aria-hidden="true" /><h2>Los casos</h2></div>
            <p>Elegí un caso para revisarlo.</p>
            <ol className="ts-ticket-grid">
              {tickets.map((t, i) => <li key={t.ticket_id}>
                <button type="button" className={`ts-ticket-button${i === seleccionado ? ' is-selected' : ''}`} aria-current={i === seleccionado ? 'true' : undefined} aria-controls="ticket-sintetico-detalle" aria-label={`Ver caso ${t.ticket_id}`} onClick={() => setSeleccionado(i)}>{t.ticket_id}</button>
              </li>)}
            </ol>
          </nav>

          <article className="ts-detail" id="ticket-sintetico-detalle" aria-labelledby="ticket-sintetico-titulo" aria-live="polite" aria-atomic="true">
            <div className="ts-detail-heading"><div><span className="ts-eyebrow">Texto del ticket</span><h2 id="ticket-sintetico-titulo">{ticket.ticket_id}</h2></div><span>{seleccionado + 1} de {tickets.length}</span></div>
            <p className="ts-ticket-text">{ticket.texto}</p>
            <section className="ts-labels" aria-label="Etiquetas de referencia y justificación">
              <h3>¿Cómo se etiquetó?</h3>
              <p className="ts-labels-intro">Estas etiquetas se usaron como referencia para calificar al clasificador.</p>
              <dl>{ETIQUETAS.map(([campo, nombre]) => <div key={campo}>
                <dt>{nombre}</dt><dd><strong className={`ts-label-value${campo === 'prioridad' ? ` ts-priority-${String(ticket[campo]).toLowerCase()}` : ''}`}>{campo === 'tipo' ? TIPOS[ticket[campo]] || valor(ticket[campo]) : valor(ticket[campo])}</strong><p>{valor(ticket.justificacion?.[campo])}</p></dd>
              </div>)}</dl>
            </section>
            <p className="ts-ticket-origin"><Sparkles size={14} aria-hidden="true" />Solicitud simulada con IA</p>
          </article>
        </section> : <section className="ts-empty" role="status"><FileText size={28} aria-hidden="true" /><h2>No hay casos para mostrar</h2><p>El conjunto guardado todavía no contiene tickets.</p></section>}

        <Resultados evaluacion={datos.evaluacion} />
        <details className="ts-provenance">
          <summary><span><FileText size={17} aria-hidden="true" />Datos del conjunto</span><ChevronDown size={16} aria-hidden="true" /></summary>
          <div>
            <dl className="ts-origin-grid">
              <div><dt>Origen</dt><dd>Generado por IA · {valor(metadatos.autoria?.herramienta)}</dd></div>
              <div><dt>Fecha de redacción</dt><dd>{valor(metadatos.fecha_redaccion)}</dd></div>
              <div><dt>Uso</dt><dd>Prueba de categoría y prioridad</dd></div>
            </dl>
          </div>
        </details>
      </>}
    </div>
  )
}

function Resultados({ evaluacion }) {
  const estado = evaluacion?.estado || 'sin_iniciar'
  const medidos = evaluacion?.tickets_medidos
  const objetivo = evaluacion?.tickets_objetivo
  const cantidades = Number.isInteger(medidos) && Number.isInteger(objetivo) && objetivo > 0
  const parcial = evaluacion?.metricas_parciales === true || estado !== 'completo' || !cantidades || medidos < objetivo
  const metricas = evaluacion?.macro_f1
  const errores = Array.isArray(evaluacion?.errores) ? evaluacion.errores.length : 0
  return (
    <section className="ts-results" aria-labelledby="resultados-sinteticos-titulo">
      <div className="ts-section-heading"><div><span className="ts-eyebrow">Resultados guardados</span><h2 id="resultados-sinteticos-titulo"><BarChart3 size={20} aria-hidden="true" />Clasificación del conjunto sintético</h2></div><span className="ts-badge">{ESTADOS[estado] || 'Estado sin confirmar'}</span></div>
      {estado === 'sin_iniciar' || !metricas ? <p className="ts-results-empty">{estado === 'ejecutando' ? 'La evaluación está en curso. Actualizá los datos guardados para consultar su avance.' : 'Todavía no hay métricas guardadas para este conjunto.'}</p> : <>
        <p className={parcial ? 'ts-partial' : 'ts-results-description'}>{parcial ? 'Métricas parciales' : 'Medición completa del conjunto'}{cantidades ? ` · ${medidos} de ${objetivo} tickets simulados medidos.` : ' · Cobertura sin confirmar.'} La evaluación con casos escritos a mano sigue aparte en Tickets de evaluación.</p>
        <div className="ts-metrics-scroll" role="region" aria-label="Métricas de clasificación sintética" tabIndex={0}>
          <table className="ts-metrics"><caption>Macro-F1 por etiqueta · escala de 0 a 1</caption><thead><tr><th scope="col">Clasificador</th><th scope="col">Categoría</th><th scope="col">Prioridad</th></tr></thead><tbody>{[['tfidf', 'TF-IDF'], ['llm', 'Modelo de lenguaje']].map(([clave, nombre]) => <tr key={clave}><th scope="row">{nombre}</th><td>{f1(metricas[clave]?.categoria)}</td><td>{f1(metricas[clave]?.prioridad)}</td></tr>)}</tbody></table>
        </div>
        <dl className="ts-result-meta">{[['Modelo', evaluacion.modelo], ['Variante', evaluacion.variante], ['Proveedor', evaluacion.proveedor]].filter(([, v]) => typeof v === 'string' && v).map(([nombre, v]) => <div key={nombre}><dt>{nombre}</dt><dd>{v}</dd></div>)}</dl>
      </>}
      {errores > 0 && <p className="ts-partial">La evaluación registra {errores} {errores === 1 ? 'error' : 'errores'}. Revisá la evidencia antes de interpretar estas métricas.</p>}
      <p className="ts-readonly-note">Esta vista solo consulta datos guardados. No inicia evaluaciones ni consume cuota de modelos.</p>
    </section>
  )
}
