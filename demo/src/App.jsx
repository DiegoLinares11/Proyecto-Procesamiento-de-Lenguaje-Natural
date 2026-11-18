import { useEffect, useReducer, useState } from 'react'
import {
  BarChart3, CircleSlash, Database, FileSearch, LifeBuoy, Play, Shield, ShieldCheck, TriangleAlert, Workflow, Wrench, Zap,
} from 'lucide-react'
import { atenderTicket, enviarDecision, obtener } from './api'
import { FALLAS, describirGuardrail } from './nodos'
import Grafo from './components/Grafo'
import Linea from './components/Linea'
import Respuesta from './components/Respuesta'
import Fragmento from './components/Fragmento'
import Aprobacion from './components/Aprobacion'
import Evaluacion from './components/Evaluacion'

const ICONO_GRUPO = {
  'Consulta nominal': Zap, 'Trazabilidad de citas': FileSearch, Abstención: CircleSlash, Herramientas: Wrench,
  Seguridad: Shield, 'Fallas y degradación': TriangleAlert,
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

  return (
    <div className="min-h-full flex flex-col">
      <header className="border-b border-slate-800/80 bg-slate-950/80 backdrop-blur sticky top-0 z-30">
        <div className="mx-auto max-w-[1600px] px-5 h-14 flex items-center gap-4">
          <div className="flex items-center gap-2.5">
            <div className="grid place-items-center size-8 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 shadow-lg shadow-indigo-500/20">
              <LifeBuoy size={17} className="text-white" />
            </div>
            <div className="leading-tight">
              <div className="text-[14px] font-semibold text-slate-50">Asistente de la Mesa de Ayuda</div>
              <div className="text-[11px] text-slate-500">Corporación Valcora · RAG agéntico con LangGraph</div>
            </div>
          </div>
          <nav className="ml-6 flex gap-1 rounded-lg bg-slate-900 p-1 border border-slate-800">
            {[['ticket', 'Atender un ticket', Workflow], ['evaluacion', 'Evaluación', BarChart3]].map(([id, nombre, Icono]) => (
              <button key={id} type="button" onClick={() => setPestana(id)}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition ${pestana === id ? 'bg-slate-800 text-slate-50' : 'text-slate-400 hover:text-slate-200'}`}>
                <Icono size={14} />{nombre}
              </button>
            ))}
          </nav>
          <Salud salud={salud} />
        </div>
      </header>

      {pestana === 'evaluacion' ? (
        <main className="flex-1 px-5 py-6"><Evaluacion /></main>
      ) : (
        <main className="flex-1 mx-auto w-full max-w-[1600px] px-5 py-5 grid gap-5 grid-cols-1 xl:grid-cols-[300px_440px_minmax(0,1fr)]">
          {/* Columna 1: el ticket */}
          <section className="space-y-4">
            <Tarjeta titulo="Ticket">
              <div className="flex gap-1 rounded-lg bg-slate-950 p-1 border border-slate-800 mb-3">
                {['N1', 'N2'].map((r) => (
                  <button key={r} type="button" onClick={() => setRol(r)}
                    className={`flex-1 rounded-md py-1.5 text-[12.5px] font-medium ${rol === r ? 'bg-indigo-500 text-white' : 'text-slate-400 hover:text-slate-200'}`}>
                    Agente {r}
                  </button>
                ))}
              </div>
              <textarea value={texto} onChange={(e) => setTexto(e.target.value)} rows={5}
                onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) atender() }}
                placeholder="Escribe el ticket del usuario…"
                className="w-full resize-none rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5 text-[14px] text-slate-100 placeholder:text-slate-600 outline-none focus:border-indigo-500" />
              <div className="mt-3">
                <div className="text-[11px] uppercase tracking-wider text-slate-500 mb-1.5">Simular una falla</div>
                <div className="grid grid-cols-2 gap-1.5">
                  {FALLAS.map((f) => (
                    <button key={f.nombre} type="button" onClick={() => setFalla(f.valor)}
                      className={`rounded-md border px-2 py-1.5 text-[12px] ${falla === f.valor ? 'border-amber-400/70 bg-amber-500/10 text-amber-200' : 'border-slate-800 text-slate-400 hover:border-slate-600'}`}>
                      {f.nombre}
                    </button>
                  ))}
                </div>
              </div>
              <button type="button" onClick={() => atender()} disabled={ocupado || !texto.trim()}
                className="mt-4 w-full flex items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-indigo-500 to-violet-500 hover:from-indigo-400 hover:to-violet-400 disabled:opacity-40 disabled:cursor-not-allowed py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-500/20">
                <Play size={15} />{ocupado ? 'Atendiendo…' : 'Atender ticket'}
              </button>
            </Tarjeta>

            <Tarjeta titulo="Ejemplos para la demo">
              <div className="space-y-3">
                {Object.entries(grupos).map(([grupo, lista]) => {
                  const Icono = ICONO_GRUPO[grupo] || Zap
                  return (
                    <div key={grupo}>
                      <div className="flex items-center gap-1.5 text-[11.5px] font-semibold text-slate-400 mb-1"><Icono size={13} />{grupo}</div>
                      <div className="space-y-1">
                        {lista.map((e) => (
                          <button key={e.titulo} type="button" disabled={ocupado} onClick={() => usarEjemplo(e)}
                            className="w-full text-left rounded-md px-2.5 py-1.5 text-[12.5px] text-slate-300 hover:bg-slate-800/70 disabled:opacity-40">
                            {e.titulo}{e.falla && <span className="ml-1.5 text-[10.5px] text-amber-300/80">· falla</span>}
                          </button>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            </Tarjeta>
          </section>

          {/* Columna 2: el grafo en vivo */}
          <section className="space-y-4 min-w-0 xl:sticky xl:top-[72px] self-start">
            <Tarjeta titulo="El grafo en vivo" extra={estado.inicio && (
              <span className="font-mono text-[11px] text-slate-500">{estado.inicio.ticket_id} · {estado.inicio.rol}</span>
            )}>
              <Grafo pasos={estado.pasos} corriendo={estado.corriendo} enPausa={!!estado.pausa} />
              {estado.inicio && <div className="mt-3"><LoQueVioElModelo inicio={estado.inicio} /></div>}
            </Tarjeta>
          </section>

          {/* Columna 3: la respuesta y la traza */}
          <section className="space-y-4 min-w-0 xl:sticky xl:top-[72px] self-start">
            <Tarjeta titulo="Respuesta del sistema">
              {estado.error && <p className="text-sm text-rose-300">{estado.error}</p>}
              {!estado.resultado && !estado.error && (
                <p className="text-sm text-slate-500">
                  {estado.pausa ? 'Esperando la decisión de N2…' : ocupado ? 'El agente está trabajando…' : 'Elige un ejemplo o escribe un ticket.'}
                </p>
              )}
              <Respuesta resultado={estado.resultado} alVerFragmento={setFragmento} />
            </Tarjeta>
            <Tarjeta titulo="Traza paso a paso" extra={estado.pasos.length > 0 && (
              <span className="font-mono text-[11px] text-slate-500">
                {estado.pasos.length} pasos · {estado.pasos.reduce((t, p) => t + p.segundos, 0).toFixed(1)} s
              </span>
            )}>
              <div className="max-h-[30vh] overflow-y-auto pr-1">
                <Linea pasos={estado.pasos} corriendo={estado.corriendo} alVerFragmento={setFragmento} />
              </div>
            </Tarjeta>
          </section>
        </main>
      )}

      {estado.pausa && <Aprobacion solicitudes={estado.pausa.solicitudes} alDecidir={decidir} />}
      {fragmento && <Fragmento chunkId={fragmento} rol={estado.inicio?.rol || rol} alCerrar={() => setFragmento(null)} />}
    </div>
  )
}

function Tarjeta({ titulo, extra, children }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 shadow-xl shadow-black/20">
      <div className="flex items-center px-4 pt-3.5 pb-2">
        <h2 className="text-[12px] font-semibold uppercase tracking-wider text-slate-400">{titulo}</h2>
        <div className="ml-auto">{extra}</div>
      </div>
      <div className="px-4 pb-4">{children}</div>
    </div>
  )
}

// El texto que de verdad llega al modelo: ya pasó por el guardrail de entrada
function LoQueVioElModelo({ inicio }) {
  const g = inicio.guardrail
  const tono = { BLOCK: 'border-rose-500/40 bg-rose-500/10', WARN: 'border-amber-500/40 bg-amber-500/10', REDACT: 'border-sky-500/40 bg-sky-500/10' }[g.decision]
    || 'border-slate-800 bg-slate-950/60'
  return (
    <div className={`rounded-lg border px-3 py-2 ${tono}`}>
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-slate-400">
        <ShieldCheck size={13} />Lo que ve el modelo · <span className="font-mono normal-case">{g.decision}</span>
      </div>
      <p className="mt-1 text-[13px] text-slate-200 break-words">{inicio.texto_seguro}</p>
      <p className="text-[11.5px] text-slate-400 mt-0.5">{describirGuardrail(g)}</p>
    </div>
  )
}

function Salud({ salud }) {
  if (!salud) return null
  if (salud.caida) return <div className="ml-auto text-[12px] text-rose-300">La API no responde</div>
  return (
    <div className="ml-auto hidden md:flex items-center gap-3 text-[11.5px] text-slate-400">
      <span>{salud.generador}</span>
      <span className="text-slate-700">·</span>
      <span>{salud.clasificador}</span>
      <span className="text-slate-700">·</span>
      <span>{salud.fragmentos} fragmentos</span>
      <span className={`flex items-center gap-1 ${salud.base ? 'text-emerald-400' : 'text-rose-400'}`}>
        <Database size={12} />{salud.base ? 'PostgreSQL' : 'sin base'}
      </span>
    </div>
  )
}
