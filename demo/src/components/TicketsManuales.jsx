import { useEffect, useRef, useState } from 'react'
import { Check, CheckCircle2, ChevronLeft, ChevronRight, ClipboardList, LoaderCircle, LockKeyhole, Play, Save, ShieldCheck } from 'lucide-react'
import {
  congelarTicketsManuales, evaluarTicketsManuales, guardarTicketsManuales,
  obtenerEvaluacionManuales, obtenerTicketsManuales, validarTicketsManuales,
} from '../api'
import './TicketsManuales.css'

const CAMPO = 'tm-field'
const BOTON = 'tm-button'
const SECUNDARIO = `${BOTON} tm-button--secondary`

function editarSnapshot(s) {
  if (s?.revision == null || !Array.isArray(s.tickets) || s.tickets.length !== 20 || !s.autoria) {
    throw new Error('No se pudo cargar el formato de 20 tickets. Vuelve a intentarlo.')
  }
  return {
    tickets: s.tickets.map(({ ticket_id, texto, categoria, prioridad }) => ({ ticket_id, texto: texto || '', categoria: categoria || '', prioridad: prioridad || '' })),
    autoria: {
      estado: s.autoria.estado || 'pendiente', autor: s.autoria.autor || '', fecha_redaccion: s.autoria.fecha_redaccion || '',
    },
  }
}

function datosCompletos(a) {
  return Boolean(a?.autor.trim() && a.fecha_redaccion)
}

function fechaLocal() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export default function TicketsManuales({ activo }) {
  const [snapshot, setSnapshot] = useState(null)
  const [borrador, setBorrador] = useState(null)
  const [baseGuardada, setBaseGuardada] = useState('')
  const [seleccionado, setSeleccionado] = useState(0)
  const [cargando, setCargando] = useState(false)
  const [ocupado, setOcupado] = useState(null)
  const [errores, setErrores] = useState([])
  const [conflicto, setConflicto] = useState(false)
  const [aviso, setAviso] = useState('')
  const [validacion, setValidacion] = useState(null)
  const [evaluacion, setEvaluacion] = useState(null)
  const [consultaEvaluacion, setConsultaEvaluacion] = useState(0)
  const titulo = useRef(null)
  const alerta = useRef(null)
  const congelado = snapshot?.estado === 'congelado'
  const sucio = borrador !== null && JSON.stringify(borrador) !== baseGuardada
  const formatoAnterior = !congelado && Boolean(snapshot?.autoria?.declaraciones)
  const pendienteGuardar = sucio || formatoAnterior
  const categorias = snapshot?.categorias || []
  const prioridades = snapshot?.prioridades || []
  const listo = (t) => Boolean(t.texto.trim() && t.texto.length <= 8000 && categorias.includes(t.categoria) && prioridades.includes(t.prioridad))
  const listos = borrador?.tickets.filter(listo).length || 0

  function aplicar(s) {
    const datos = editarSnapshot(s)
    setSnapshot(s)
    setBorrador(datos)
    setBaseGuardada(JSON.stringify(datos))
    setConflicto(false)
    setValidacion(null)
  }

  function mostrarError(e, captura = false) {
    setErrores(e.errores?.length ? e.errores : [e.message || 'No se pudo completar la operación.'])
    if (captura && e.status === 409) setConflicto(true)
    setValidacion(null)
    setAviso('')
  }

  async function cargar() {
    setCargando(true)
    setErrores([])
    try { aplicar(await obtenerTicketsManuales()) } catch (e) { mostrarError(e) }
    finally { setCargando(false) }
  }

  useEffect(() => {
    if (activo) {
      titulo.current?.focus({ preventScroll: true })
      if (!snapshot && !cargando) cargar()
    }
  }, [activo]) // Se mantiene montado al cambiar de sección: conserva los cambios sin guardar.

  useEffect(() => {
    if (!sucio) return
    const proteger = (e) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', proteger)
    return () => window.removeEventListener('beforeunload', proteger)
  }, [sucio])

  useEffect(() => { if (activo && errores.length) alerta.current?.focus() }, [errores, activo])

  useEffect(() => {
    if (!activo || !congelado) return
    let cancelado = false
    let temporizador
    async function consultar() {
      try {
        const datos = await obtenerEvaluacionManuales()
        if (cancelado) return
        setEvaluacion(datos)
        if (datos.estado === 'ejecutando') temporizador = setTimeout(consultar, 2500)
      } catch (e) {
        if (!cancelado) setEvaluacion({ estado: 'no_disponible', mensaje: e.message, puede_iniciar: false })
      }
    }
    consultar()
    return () => { cancelado = true; clearTimeout(temporizador) }
  }, [activo, congelado, consultaEvaluacion])

  function cambiarTicket(campo, valor) {
    setBorrador((b) => ({ ...b, tickets: b.tickets.map((t, i) => i === seleccionado ? { ...t, [campo]: valor } : t) }))
    setValidacion(null)
    setAviso('')
  }

  function cambiarAutoria(campo, valor) {
    setBorrador((b) => ({ ...b, autoria: { ...b.autoria, [campo]: valor } }))
    setValidacion(null)
    setAviso('')
  }

  async function guardar() {
    if (ocupado || congelado || !pendienteGuardar) return
    setOcupado('guardar'); setErrores([])
    try {
      aplicar(await guardarTicketsManuales({ revision: snapshot.revision, tickets: borrador.tickets,
        autoria: { ...borrador.autoria, estado: datosCompletos(borrador.autoria) ? 'declarado' : 'pendiente',
          fecha_redaccion: borrador.autoria.fecha_redaccion || null } }))
      setAviso('Borrador guardado en este equipo.')
    } catch (e) { mostrarError(e, true) }
    finally { setOcupado(null) }
  }

  async function validar() {
    if (ocupado || pendienteGuardar || congelado) return
    setOcupado('validar'); setErrores([]); setAviso(''); setValidacion(null)
    try {
      const datos = await validarTicketsManuales(snapshot.revision)
      setValidacion({ ...datos, revision: snapshot.revision })
      if (!datos.valido) setErrores(Array.isArray(datos.errores) ? datos.errores : ['El conjunto todavía no está completo.'])
      else setAviso('Los 20 tickets están listos. Ya puedes reservar el conjunto para la evaluación.')
    } catch (e) { mostrarError(e, true) }
    finally { setOcupado(null) }
  }

  async function congelar() {
    if (!puedeCongelar) return
    setOcupado('congelar'); setErrores([])
    try {
      aplicar(await congelarTicketsManuales(snapshot.revision))
      setAviso('El conjunto quedó reservado para evaluación.')
    } catch (e) { mostrarError(e, true) }
    finally { setOcupado(null) }
  }

  async function evaluar() {
    if (ocupado || !congelado || evaluacion?.puede_iniciar !== true || ['ejecutando', 'completo'].includes(evaluacion.estado)) return
    setOcupado('evaluar'); setErrores([])
    try {
      setEvaluacion(await evaluarTicketsManuales())
      setConsultaEvaluacion((n) => n + 1)
      setAviso('Evaluación solicitada. Puedes consultar aquí su avance.')
    } catch (e) { mostrarError(e); setConsultaEvaluacion((n) => n + 1) }
    finally { setOcupado(null) }
  }

  const puedeCongelar = !ocupado && !pendienteGuardar && !congelado && listos === 20 && datosCompletos(borrador?.autoria)
    && validacion?.valido === true && validacion.revision === snapshot?.revision
  const t = borrador?.tickets[seleccionado]

  return (
    <div className="tm-page">
      <header className="tm-heading">
        <div>
          <p className="tm-eyebrow">Evaluación del clasificador</p>
          <h1 ref={titulo} tabIndex={-1}>Tickets de evaluación</h1>
          <p className="tm-description">Registra 20 casos escritos a mano con su categoría y prioridad. Se usarán para medir el clasificador.</p>
        </div>
        {snapshot && <span className={`tm-badge ${congelado ? 'tm-badge--success' : 'tm-badge--neutral'}`}>
          {congelado ? <LockKeyhole size={13} /> : <ClipboardList size={13} />}{congelado ? 'Conjunto reservado' : 'Borrador'}
        </span>}
      </header>

      {errores.length > 0 && <div ref={alerta} role="alert" tabIndex={-1} className="tm-alert tm-alert--danger">
        <p className="tm-alert-title">Revisa lo siguiente</p>
        <ul>{errores.map((e, i) => <li key={i}>{typeof e === 'string' ? e : 'Hay un campo que necesita revisión.'}</li>)}</ul>
        {conflicto && <button type="button" onClick={cargar} disabled={cargando || !!ocupado} className={`${SECUNDARIO} tm-button--danger`}>Descartar estos cambios y cargar la versión guardada</button>}
      </div>}
      <div aria-live="polite" role="status" className="tm-status">{aviso && <p className="tm-alert tm-alert--success"><CheckCircle2 size={17} aria-hidden="true" /><span>{aviso}</span></p>}</div>

      {cargando && <p className="tm-loading" role="status"><LoaderCircle size={17} className="animate-spin" />Cargando el conjunto guardado…</p>}
      {!snapshot && !cargando && <button type="button" onClick={cargar} className={SECUNDARIO}>Volver a cargar</button>}

      {borrador && !cargando && <>
        <div className="tm-toolbar">
          <div className="tm-progress-group">
            <div className="tm-progress-caption"><p><strong>{listos}<span>/20</span></strong> tickets listos</p><span className="tm-small">Texto, categoría y prioridad</span></div>
            <div role="progressbar" aria-label="Tickets completos" aria-valuemin={0} aria-valuemax={20} aria-valuenow={listos} className="tm-progress"><div style={{ width: `${listos * 5}%` }} /></div>
          </div>
          <div className="tm-save-group">
            {!congelado && <p className={`tm-save-state ${pendienteGuardar ? 'tm-save-state--pending' : ''}`}><span aria-hidden="true" />{sucio ? 'Tienes cambios sin guardar. Se conservan al cambiar de pestaña.' : formatoAnterior ? 'Guarda el borrador para actualizar el formato.' : 'El borrador guardado se conserva en este equipo.'}</p>}
            {!congelado && <button type="button" onClick={guardar} disabled={!pendienteGuardar || !!ocupado} className={`${BOTON} tm-button--primary`}><IconoAccion ocupado={ocupado === 'guardar'} icono={Save} />{ocupado === 'guardar' ? 'Guardando…' : 'Guardar borrador'}</button>}
          </div>
        </div>

        <div className="tm-workspace">
          <section aria-label="Seleccionar ticket" className="tm-ticket-nav">
            <div className="tm-nav-heading"><h2>Los 20 tickets</h2><span className="tm-small">Selecciona para editar</span></div>
            <div className="tm-ticket-grid">
              {borrador.tickets.map((ticket, i) => <button key={ticket.ticket_id} type="button" onClick={() => setSeleccionado(i)} aria-pressed={i === seleccionado} aria-label={`${ticket.ticket_id}, ${listo(ticket) ? 'completo' : 'pendiente'}`} className={`tm-ticket-button ${i === seleccionado ? 'tm-ticket-button--selected' : ''} ${listo(ticket) ? 'tm-ticket-button--complete' : ''}`}>
                {listo(ticket) && <Check size={11} className="tm-ticket-check" />}{ticket.ticket_id}
              </button>)}
            </div>
            <p className="tm-mobile-nav-help">Desliza para elegir otro ticket.</p>
            <p className="tm-nav-legend"><CheckCircle2 size={13} aria-hidden="true" />Completo: texto y dos etiquetas</p>
          </section>

          <section aria-labelledby="ticket-manual-titulo" className="tm-editor">
            <div className="tm-section-heading"><div><p className="tm-eyebrow">Texto y clasificación</p><h2 id="ticket-manual-titulo" className="tm-ticket-title">{t.ticket_id}</h2></div><span className="tm-position">{seleccionado + 1} de 20</span></div>
            <fieldset disabled={congelado || !!ocupado} className="tm-editor-fields">
              <div>
                <label htmlFor="manual-texto" className="tm-label">Texto del ticket</label>
                <textarea id="manual-texto" value={t.texto} onChange={(e) => cambiarTicket('texto', e.target.value)} rows={7} maxLength={8000} placeholder="Escribe aquí el texto creado por ti." aria-describedby="manual-ayuda manual-contador" className={`${CAMPO} tm-textarea`} />
                <div className="tm-textarea-footer"><p id="manual-ayuda" className="tm-help">Describe el problema, su impacto y si hay una alternativa temporal. Usa situaciones ficticias, sin datos personales reales.</p><p id="manual-contador" className="tm-counter">{t.texto.length}/8000 caracteres</p></div>
              </div>
              <div className="tm-fields-row">
                <div><label htmlFor="manual-categoria" className="tm-label">Categoría</label><select id="manual-categoria" value={t.categoria} onChange={(e) => cambiarTicket('categoria', e.target.value)} className={CAMPO}><option value="">Seleccionar categoría</option>{categorias.map((c) => <option key={c} value={c}>{c}</option>)}</select></div>
                <div><label htmlFor="manual-prioridad" className="tm-label">Prioridad</label><select id="manual-prioridad" value={t.prioridad} onChange={(e) => cambiarTicket('prioridad', e.target.value)} className={CAMPO}><option value="">Seleccionar prioridad</option>{prioridades.map((p) => <option key={p} value={p}>{p}</option>)}</select></div>
              </div>
            </fieldset>
            <details className="tm-criteria"><summary>Ver criterios de etiquetado</summary><div><p>ACCESO: cuentas y permisos. CORREO: Outlook, buzón y Teams. EQUIPOS: computadoras y periféricos. RED: internet, Wi-Fi y VPN. APLICACIONES: software y sistemas. OTRO: las demás solicitudes.</p><p>ALTA: no puede trabajar sin alternativa, afecta a varias personas o a un proceso crítico, como facturación o nómina, o hay un posible incidente de seguridad. MEDIA: afecta el trabajo, con alternativa temporal. BAJA: consultas o molestias menores. La urgencia escrita no determina la prioridad.</p></div></details>
            <div className="tm-editor-navigation"><button type="button" onClick={() => setSeleccionado((n) => n - 1)} disabled={seleccionado === 0} className={SECUNDARIO}><ChevronLeft size={15} />Anterior</button><button type="button" onClick={() => setSeleccionado((n) => n + 1)} disabled={seleccionado === 19} className={SECUNDARIO}>Siguiente<ChevronRight size={15} /></button></div>
          </section>
        </div>

        <section aria-labelledby="datos-conjunto-titulo" className="tm-section tm-set-data">
          <h2 id="datos-conjunto-titulo">Datos del conjunto</h2>
          <p className="tm-description">Los casos se reservan para evaluar el clasificador. Debe escribirlos una persona distinta de quienes redactaron F3, el conjunto de tickets históricos del proyecto.</p>
          <fieldset disabled={congelado || !!ocupado} className="tm-fields-row tm-set-fields">
            <div>
              <label htmlFor="manual-autor" className="tm-label">Persona que escribió los casos</label>
              <input id="manual-autor" value={borrador.autoria.autor} maxLength={120} onChange={(e) => cambiarAutoria('autor', e.target.value)} autoComplete="name" className={CAMPO} />
            </div>
            <div>
              <label htmlFor="manual-fecha" className="tm-label">Fecha de redacción</label>
              <input id="manual-fecha" type="date" max={fechaLocal()} value={borrador.autoria.fecha_redaccion} onChange={(e) => cambiarAutoria('fecha_redaccion', e.target.value)} className={CAMPO} />
            </div>
          </fieldset>
        </section>

        {!congelado ? <section className="tm-section tm-finalize">
          <div className="tm-finalize-content"><h2>Preparar para evaluación</h2><p className="tm-description">Valida que estén completos los textos, las etiquetas y los datos del conjunto. Al reservarlo se cierra su edición.</p><p className={`tm-finalize-hint ${pendienteGuardar ? 'tm-finalize-hint--pending' : ''}`}>{pendienteGuardar ? 'Guarda el borrador antes de validar.' : validacion?.valido ? 'Ya puedes reservar el conjunto.' : 'Primero valida la versión guardada.'}</p></div>
          <div className="tm-finalize-actions"><button type="button" onClick={validar} disabled={pendienteGuardar || !!ocupado} className={SECUNDARIO}><IconoAccion ocupado={ocupado === 'validar'} icono={ShieldCheck} />{ocupado === 'validar' ? 'Validando…' : 'Validar 20 tickets'}</button><button type="button" onClick={congelar} disabled={!puedeCongelar} className={`${BOTON} tm-button--primary`}><IconoAccion ocupado={ocupado === 'congelar'} icono={LockKeyhole} />{ocupado === 'congelar' ? 'Reservando…' : 'Reservar conjunto'}</button></div>
        </section>
          : <EvaluacionManual datos={evaluacion} ocupado={ocupado === 'evaluar'} alEvaluar={evaluar} alConsultar={() => setConsultaEvaluacion((n) => n + 1)} />}
      </>}
    </div>
  )
}

function IconoAccion({ ocupado, icono: Icono }) {
  return ocupado ? <LoaderCircle size={16} className="animate-spin" aria-hidden="true" /> : <Icono size={16} aria-hidden="true" />
}

function EvaluacionManual({ datos, ocupado, alEvaluar, alConsultar }) {
  const estado = datos?.estado
  const titulos = { sin_iniciar: 'Conjunto listo para evaluar', ejecutando: 'Evaluación en curso', completo: 'Evaluación completada', incompleto: 'Evaluación incompleta', no_disponible: 'Evaluación no disponible' }
  const completados = Math.max(0, Math.min(20, datos?.progreso?.completados || 0))
  const f = (v) => typeof v === 'number' ? v.toFixed(3) : '—'
  return <section aria-labelledby="evaluar-manuales-titulo" className="tm-section tm-evaluation">
    <div className="tm-section-heading"><div><p className="tm-eyebrow">Evaluación final</p><h2 id="evaluar-manuales-titulo">{titulos[estado] || 'Consultando evaluación…'}</h2></div></div>
    <p className="tm-description">La evaluación compara el clasificador de Codex y TF-IDF con estos 20 tickets y consume cuota de tu suscripción.</p>
    {datos?.mensaje && <p className="tm-evaluation-message" role="status">{datos.mensaje}</p>}
    {estado === 'ejecutando' && <p className="tm-evaluation-progress" role="status"><LoaderCircle size={16} className="animate-spin" />{completados}/20 tickets evaluados. El avance se actualiza automáticamente.</p>}
    <div className="tm-evaluation-actions"><button type="button" onClick={alEvaluar} disabled={ocupado || datos?.puede_iniciar !== true || ['ejecutando', 'completo'].includes(estado)} className={`${BOTON} tm-button--primary`}><IconoAccion ocupado={ocupado} icono={Play} />{ocupado ? 'Iniciando…' : estado === 'incompleto' && datos?.puede_iniciar ? 'Reintentar inicio' : 'Evaluar conjunto'}</button><button type="button" onClick={alConsultar} disabled={ocupado} className={SECUNDARIO}>Actualizar estado</button></div>
    {datos?.resumen && <div className="tm-metrics">{[['categoria', 'Categoría'], ['prioridad', 'Prioridad']].map(([k, nombre]) => <div key={k} className="tm-metric"><h3>Macro-F1 · {nombre}</h3><dl><div><dt>Codex</dt><dd>{f(datos.resumen.macro_f1_llm?.[k])}</dd></div><div><dt>TF-IDF</dt><dd>{f(datos.resumen.macro_f1_tfidf?.[k])}</dd></div></dl></div>)}</div>}
  </section>
}
