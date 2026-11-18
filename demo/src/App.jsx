import { useEffect, useReducer, useRef, useState } from 'react'
import {
  ArrowRight, BarChart3, ChevronDown, CircleSlash, ClipboardList, Database, FileSearch, LoaderCircle, Menu, MessageSquare, Shield, ShieldCheck, TriangleAlert, Workflow, Wrench, X, Zap,
} from 'lucide-react'
import { atenderTicket, enviarDecision, obtener } from './api'
import { FALLAS, describirGuardrail } from './nodos'
import Grafo from './components/Grafo'
import Linea from './components/Linea'
import Respuesta from './components/Respuesta'
import Fragmento from './components/Fragmento'
import Aprobacion from './components/Aprobacion'
import Evaluacion from './components/Evaluacion'
import TicketsManuales from './components/TicketsManuales'
import TicketsSinteticos from './components/TicketsSinteticos'

const ICONO_GRUPO = {
  'Consulta nominal': Zap, 'Trazabilidad de citas': FileSearch, Abstención: CircleSlash, Herramientas: Wrench,
  Seguridad: Shield, 'Fallas y degradación': TriangleAlert,
}

const DESCRIPCION_GRUPO = {
  'Consulta nominal': 'Casos de soporte del día a día.',
  'Trazabilidad de citas': 'Seguí la respuesta hasta su fuente.',
  Abstención: 'Cuando hace falta más información.',
  Herramientas: 'Acciones y aprobación por rol.',
  Seguridad: 'Protección de datos y accesos.',
  'Fallas y degradación': 'Qué pasa cuando algo no responde.',
}

const INICIAL = { corriendo: false, inicio: null, pasos: [], pausa: null, resultado: null, error: null, segundosPrevios: 0 }

function reducir(estado, accion) {
  switch (accion.tipo) {
    case 'empezar': return { ...INICIAL, corriendo: true }
    case 'continuar': return { ...estado, corriendo: true, pausa: null }
    case 'inicio': return { ...estado, inicio: accion }
    case 'paso': return { ...estado, pasos: [...estado.pasos, accion] }
    // Con una pausa, el tiempo total suma lo que tardó antes y después de la decisión de N2
    case 'pausa': return { ...estado, corriendo: false, pausa: accion, segundosPrevios: estado.segundosPrevios + accion.segundos_total }
    case 'respuesta': return { ...estado, corriendo: false, resultado: { ...accion, segundos_total: estado.segundosPrevios + accion.segundos_total } }
    case 'error': return { ...estado, corriendo: false, error: accion.mensaje }
    default: return estado
  }
}

export default function App() {
  const [pestana, setPestana] = useState('ticket')
  const [salud, setSalud] = useState(null)
  const [ejemplos, setEjemplos] = useState([])
  const [texto, setTexto] = useState('')
  const [rol, setRol] = useState('N1')
  const [falla, setFalla] = useState(null)
  const [fragmento, setFragmento] = useState(null)
  const [estado, despachar] = useReducer(reducir, INICIAL)
  const [menuAbierto, setMenuAbierto] = useState(false)
  const [grupoEjemplo, setGrupoEjemplo] = useState('Consulta nominal')
  const menuRef = useRef(null)
  const botonMenu = useRef(null)

  // Sólo controla la navegación visual del menú compacto.
  useEffect(() => {
    if (!menuAbierto) return
    const anterior = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const botones = () => [...menuRef.current.querySelectorAll('button')].filter((b) => b.offsetParent !== null)
    botones()[0]?.focus()
    const teclado = (e) => {
      if (e.key === 'Escape') setMenuAbierto(false)
      if (e.key === 'Tab') {
        const lista = botones(), primero = lista[0], ultimo = lista.at(-1)
        if (e.shiftKey && document.activeElement === primero) { e.preventDefault(); ultimo?.focus() }
        else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primero?.focus() }
      }
    }
    const ampliar = () => { if (window.innerWidth >= 1100) setMenuAbierto(false) }
    document.addEventListener('keydown', teclado)
    window.addEventListener('resize', ampliar)
    return () => {
      document.body.style.overflow = anterior
      document.removeEventListener('keydown', teclado)
      window.removeEventListener('resize', ampliar)
      botonMenu.current?.focus()
    }
  }, [menuAbierto])

  useEffect(() => {
    obtener('/api/salud').then(setSalud).catch(() => setSalud({ caida: true }))
    obtener('/api/ejemplos').then(setEjemplos).catch(() => {})
  }, [])

  async function atender(t = texto, r = rol, f = falla) {
    if (!t.trim() || estado.corriendo) return
    despachar({ tipo: 'empezar' })
    try {
      await atenderTicket({ texto: t, rol: r, falla: f }, despachar)
    } catch (e) {
      despachar({ tipo: 'error', mensaje: e.message })
    }
  }

  async function decidir(decision) {
    const hilo = estado.pausa.hilo
    despachar({ tipo: 'continuar' })
    try {
      await enviarDecision(hilo, decision, despachar)
    } catch (e) {
      despachar({ tipo: 'error', mensaje: e.message })
    }
  }

  function usarEjemplo(e) {
    setTexto(e.texto); setRol(e.rol); setFalla(e.falla)
    atender(e.texto, e.rol, e.falla)
  }

  const grupos = ejemplos.reduce((m, e) => ({ ...m, [e.grupo]: [...(m[e.grupo] || []), e] }), {})
  const ocupado = estado.corriendo

  const secciones = [
    ['ticket', 'Atender un ticket', 'Respuestas con evidencia', Workflow],
    ['manuales', 'Tickets de evaluación', 'Casos escritos a mano', ClipboardList],
    ['sinteticos', 'Casos sintéticos', '20 solicitudes simuladas con IA', Zap],
    ['evaluacion', 'Evaluación', 'Calidad, seguridad y tiempos', BarChart3],
  ]
  const actual = secciones.find(([id]) => id === pestana)

  return (
    <div className="app-shell">
      <a href="#contenido-principal" className="skip-link">Saltar al contenido</a>
      {menuAbierto && <button type="button" aria-label="Cerrar menú de navegación" className="sidebar-backdrop" onClick={() => setMenuAbierto(false)} />}
      <aside ref={menuRef} id="navegacion-principal" className={`app-sidebar ${menuAbierto ? 'is-open' : ''}`} aria-label="Navegación principal">
        <div className="sidebar-brand">
          <img className="brand-signature" src="/pilas/firma.svg" alt="¡PILAS! Soporte técnico" width="196" height="61" />
          <button type="button" className="sidebar-close" aria-label="Cerrar menú" onClick={() => setMenuAbierto(false)}><X size={20} /></button>
        </div>
        <div className="sidebar-tagline">Tu tecnología,<br /><strong>en marcha.</strong></div>
        <div className="sidebar-label">Tu espacio de trabajo</div>
        <nav aria-label="Secciones" className="sidebar-nav">
          {secciones.map(([id, nombre, detalle, Icono]) => (
            <button key={id} type="button" aria-label={nombre} aria-current={pestana === id ? 'page' : undefined}
              onClick={() => { setPestana(id); setMenuAbierto(false) }} className={`sidebar-link ${pestana === id ? 'is-active' : ''}`}>
              <Icono size={19} strokeWidth={1.7} /><span><strong>{nombre}</strong><small>{detalle}</small></span>
              {pestana === id && <span className="nav-active-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="sidebar-footer-icon"><ShieldCheck size={19} /></span>
          <div><strong>Entorno de demostración</strong><span>CC3103 · Proyecto académico</span></div>
        </div>
      </aside>

      <div className="app-workspace">
        <header className="app-topbar">
          <div className="topbar-context">
            <button ref={botonMenu} type="button" aria-label="Abrir menú de navegación" aria-expanded={menuAbierto} aria-controls="navegacion-principal" className="menu-toggle" onClick={() => setMenuAbierto(true)}><Menu size={22} /></button>
            <img className="topbar-symbol" src="/pilas/simbolo.png" alt="¡PILAS!" width="36" height="36" />
            <div><span className="topbar-overline">¡PILAS! · Centro de soporte</span><span className="topbar-current">{actual?.[1]}</span></div>
          </div>
          <Salud salud={salud} />
        </header>

        {pestana === 'manuales' ? null : pestana === 'evaluacion' ? (
          <main id="contenido-principal" tabIndex={-1} className="workspace-content"><Evaluacion /></main>
        ) : pestana === 'sinteticos' ? (
          <main id="contenido-principal" tabIndex={-1} className="workspace-content"><TicketsSinteticos /></main>
        ) : (
          <main id={pestana === 'ticket' ? 'contenido-principal' : undefined} tabIndex={-1} className="workspace-content">
            <div className="page-heading">
              <div><span className="page-eyebrow">¡Hola! Esto es ¡PILAS!</span><h1>¿En qué te ayudamos?</h1><p>Contanos qué pasó y te orientamos con información que podés verificar.</p></div>
              <span className="context-label"><ShieldCheck size={14} />Demo académica · CC3103</span>
            </div>
            <ol className="workflow-guide" aria-label="Cómo atender un ticket">
              <li><span>1</span>Contanos el caso</li><li><span>2</span>Revisá la respuesta</li><li><span>3</span>Consultá las fuentes</li>
            </ol>
            <div className="ticket-workspace">
              <section className="ticket-entry" aria-label="Nuevo ticket">
                <Tarjeta titulo="Contanos el problema" extra={<span className="card-number">01 / Tu caso</span>}>
                  <div className="field-label-row"><span className="field-label">Rol de demostración</span><span className="field-hint">Acceso a la información</span></div>
                  <div className="role-switch" aria-label="Rol de la sesión">
                    {['N1', 'N2'].map((r) => (
                      <button key={r} type="button" onClick={() => setRol(r)} aria-pressed={rol === r} className={rol === r ? 'is-selected' : ''}>Agente {r}</button>
                    ))}
                  </div>
                  <label htmlFor="texto-atencion" className="field-label mt-5">¿Qué necesita el usuario?</label>
                  <textarea id="texto-atencion" value={texto} onChange={(e) => setTexto(e.target.value)} rows={7}
                    onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) atender() }}
                    placeholder="Describí qué pasó con el equipo o el acceso…" className="ticket-textarea" />
                  <p className="input-help">Incluí qué falla, a quién afecta y qué se ha intentado.</p>
                  <details className="demo-options">
                    <summary><span><Wrench size={14} />Opciones de demostración</span><span className={falla ? 'demo-selected' : ''}>{falla ? 'Falla activa' : 'Opcional'}<ChevronDown size={13} /></span></summary>
                    <div className="demo-options-body"><p>Probá cómo responde el sistema ante una falla.</p><div className="failure-grid">
                      {FALLAS.map((f) => <button key={f.nombre} type="button" onClick={() => setFalla(f.valor)} aria-pressed={falla === f.valor} className={falla === f.valor ? 'is-selected' : ''}>{f.nombre}</button>)}
                    </div></div>
                  </details>
                  <button type="button" onClick={() => atender()} disabled={ocupado || !texto.trim()} className="primary-action w-full mt-4">
                    {ocupado ? <LoaderCircle size={16} className="animate-spin" /> : <ArrowRight size={17} />}{ocupado ? 'Atendiendo…' : 'Atender ticket'}
                  </button>
                  <p className="shortcut-note">⌘ / Ctrl + Enter para enviar · Consume cuota incluida</p>
                </Tarjeta>

              </section>

              <section className="ticket-results min-w-0" aria-label="Respuesta y evidencia">
                <Tarjeta titulo="Respuesta del asistente" extra={<span className={`response-state ${ocupado ? 'is-working' : ''}`}>{estado.pausa ? 'En espera' : ocupado ? 'En proceso' : estado.resultado ? 'Finalizado' : 'Listo para comenzar'}</span>}>
                  {estado.error && <div className="inline-error" role="alert"><TriangleAlert size={18} /><p>{estado.error}</p></div>}
                  {!estado.resultado && !estado.error && (
                    <div className={`response-empty ${ocupado || estado.pausa ? 'is-active' : ''}`} role={ocupado || estado.pausa ? 'status' : undefined}>
                      <span className="response-empty-icon">{ocupado ? <LoaderCircle size={27} className="animate-spin" /> : estado.pausa ? <ShieldCheck size={27} /> : <MessageSquare size={27} strokeWidth={1.6} />}</span>
                      <h3>{estado.pausa ? 'Esperando la decisión de N2' : ocupado ? 'El asistente está trabajando' : 'Vamos a resolverlo, paso a paso.'}</h3>
                      <p>{estado.pausa ? 'La acción queda pendiente hasta recibir una autorización válida.' : ocupado ? 'Podés seguir el recorrido y los pasos del proceso abajo.' : 'Enviá tu ticket para ver la clasificación del caso, la orientación y las fuentes consultadas.'}</p>
                      {!ocupado && !estado.pausa && <div className="response-capabilities"><span><FileSearch size={14} />Fuentes verificables</span><span><Shield size={14} />Control por rol</span></div>}
                    </div>
                  )}
                  <Respuesta resultado={estado.resultado} alVerFragmento={setFragmento} />
                </Tarjeta>
              </section>

              <details id="recorrido-trazabilidad" className="process-panel">
                <summary><span><Workflow size={17} /><strong>Recorrido y trazabilidad</strong></span><span className="process-panel-meta">{estado.pasos.length > 0 ? `${estado.pasos.length} pasos · ${estado.pasos.reduce((t, p) => t + p.segundos, 0).toFixed(1)} s` : 'El proceso, paso a paso'}<ChevronDown size={16} /></span></summary>
                <div className="process-panel-content">
                  <div className="graph-area"><div className="process-subheading"><span>Flujo del agente</span>{estado.inicio && <span>{estado.inicio.ticket_id} · {estado.inicio.rol}</span>}</div>
                    <Grafo pasos={estado.pasos} corriendo={estado.corriendo} enPausa={!!estado.pausa} />
                    {estado.inicio && <div className="mt-4"><LoQueVioElModelo inicio={estado.inicio} /></div>}
                  </div>
                  <div className="trace-area"><div className="process-subheading"><span>Actividad del ticket</span></div><div className="trace-scroll"><Linea pasos={estado.pasos} corriendo={estado.corriendo} alVerFragmento={setFragmento} /></div></div>
                </div>
              </details>
            </div>

            <section className="example-library" aria-labelledby="titulo-ejemplos">
              <div className="example-library-heading">
                <div><span className="page-eyebrow">Explorá el asistente</span><h2 id="titulo-ejemplos">Un punto de partida para cada caso.</h2><p>Elegí una categoría y probá cómo responde ¡PILAS!.</p></div>
                <span className="example-library-label"><Zap size={14} />Casos de demostración</span>
              </div>
              <div className="example-groups" aria-label="Categorías de ejemplos">
                {Object.entries(grupos).map(([grupo, lista]) => {
                  const Icono = ICONO_GRUPO[grupo] || Zap
                  return <button key={grupo} type="button" className={`example-category ${grupoEjemplo === grupo ? 'is-selected' : ''}`} aria-pressed={grupoEjemplo === grupo} aria-controls="casos-ejemplo" onClick={() => setGrupoEjemplo(grupo)}>
                    <span className="example-category-icon"><Icono size={21} strokeWidth={1.7} /></span>
                    <span className="example-category-copy"><strong>{grupo}</strong><small>{DESCRIPCION_GRUPO[grupo]}</small></span>
                    <span className="example-category-count">{lista.length}<ChevronDown size={13} /></span>
                  </button>
                })}
              </div>
              <div id="casos-ejemplo" className="example-selection" role="region" aria-labelledby="titulo-casos-ejemplo">
                <div className="example-selection-heading"><h3 id="titulo-casos-ejemplo">{grupoEjemplo}</h3><p>Al elegir un caso, se envía al asistente y consume cuota incluida.</p></div>
                <div className="example-options">{(grupos[grupoEjemplo] || []).map((e) => <button key={e.titulo} type="button" disabled={ocupado} onClick={() => usarEjemplo(e)}><span>{e.titulo}{e.falla && <span className="example-failure">Falla simulada</span>}</span><ArrowRight size={16} /></button>)}</div>
              </div>
            </section>
          </main>
        )}

        <main id={pestana === 'manuales' ? 'contenido-principal' : undefined} tabIndex={-1} className={pestana === 'manuales' ? 'workspace-content' : 'hidden'}>
          <TicketsManuales activo={pestana === 'manuales'} />
        </main>
      </div>
      {estado.pausa && <Aprobacion solicitudes={estado.pausa.solicitudes} notas={estado.pausa.notas} alDecidir={decidir} />}
      {fragmento && <Fragmento chunkId={fragmento} rol={estado.inicio?.rol || rol} alCerrar={() => setFragmento(null)} />}
    </div>
  )
}

function Tarjeta({ titulo, extra, children }) {
  return <div className="workspace-card"><div className="workspace-card-heading"><h2>{titulo}</h2><div>{extra}</div></div><div className="workspace-card-body">{children}</div></div>
}

function LoQueVioElModelo({ inicio }) {
  const g = inicio.guardrail
  const tono = { BLOCK: 'is-blocked', WARN: 'is-warning', REDACT: 'is-redacted' }[g.decision] || ''
  return <div className={`safe-input ${tono}`}>
    <div><ShieldCheck size={14} /><strong>Texto revisado</strong><span>{g.decision}</span></div>
    <p>{inicio.texto_seguro}</p><small>{describirGuardrail(g)}</small>
  </div>
}

function Salud({ salud }) {
  if (!salud) return <span className="system-loading">Comprobando conexión…</span>
  if (salud.caida) return <span className="system-offline"><span />Sin conexión con la API</span>
  return <details className="system-status">
    <summary aria-label="Estado del sistema"><span className={salud.base ? 'status-dot is-online' : 'status-dot'} /><span>{salud.base ? 'Base conectada' : salud.captura_disponible ? 'Captura disponible' : 'Sin base de datos'}</span><ChevronDown size={14} /></summary>
    <div className="system-popover"><h2>Estado del sistema</h2><dl><div><dt>Generador</dt><dd>{salud.generador}</dd></div><div><dt>Clasificador</dt><dd>{salud.clasificador}</dd></div><div><dt>Fragmentos cargados</dt><dd>{salud.fragmentos}</dd></div><div><dt>Base de datos</dt><dd>{salud.base ? 'Conectada' : 'Sin inicializar'}</dd></div></dl><p>La captura de evaluación está disponible sin preparar el motor de atención.</p></div>
  </details>
}
