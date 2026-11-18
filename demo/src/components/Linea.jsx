// La traza paso a paso: lo que hizo cada nodo, cuánto tardó y, al abrirlo, el detalle.
import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { NODOS, fuenteCorta, resumirPaso } from '../nodos'

export default function Linea({ pasos, corriendo, alVerFragmento }) {
  if (!pasos.length && !corriendo) {
    return <p className="text-sm text-slate-500 px-1">Aquí aparece cada paso del grafo mientras corre.</p>
  }
  return (
    <ol className="relative space-y-1.5">
      {pasos.map((p, i) => <Paso key={i} paso={p} alVerFragmento={alVerFragmento} />)}
      {corriendo && (
        <li className="flex items-center gap-2 text-sm text-violet-300 px-2 py-1.5">
          <span className="size-2 rounded-full bg-violet-400 animar-brillo" /> Trabajando…
        </li>
      )}
    </ol>
  )
}

function Paso({ paso, alVerFragmento }) {
  const [abierto, setAbierto] = useState(false)
  const nodo = NODOS[paso.nodo] || { nombre: paso.nodo, icono: ChevronRight }
  const Icono = nodo.icono
  const conDetalle = tieneDetalle(paso)
  return (
    <li className="animar-entrada rounded-lg border border-slate-800 bg-slate-900/60">
      <button type="button" onClick={() => conDetalle && setAbierto(!abierto)}
        className={`w-full flex items-start gap-2.5 px-3 py-2 text-left ${conDetalle ? 'cursor-pointer hover:bg-slate-800/40' : 'cursor-default'}`}>
        <Icono size={16} className="mt-0.5 shrink-0 text-indigo-300" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-semibold text-slate-100">{nodo.nombre}</span>
            <span className="ml-auto font-mono text-[11px] text-slate-500">{paso.segundos.toFixed(2)} s</span>
          </div>
          <p className="text-[12.5px] text-slate-400 leading-snug">{resumirPaso(paso)}</p>
        </div>
        {conDetalle && <ChevronRight size={15} className={`mt-1 shrink-0 text-slate-500 transition-transform ${abierto ? 'rotate-90' : ''}`} />}
      </button>
      {abierto && <Detalle paso={paso} alVerFragmento={alVerFragmento} />}
    </li>
  )
}

// Booleano explícito: un `length` de 0 se dibujaría como "0" en la página
function tieneDetalle(p) {
  return Boolean(p.llamadas?.length || p.traza?.some((t) => t.candidatos?.length || t.errores?.length || t.error || t.triage)
    || p.revision?.length)
}

function Detalle({ paso, alVerFragmento }) {
  return (
    <div className="border-t border-slate-800 px-3 py-2.5 space-y-2.5 text-[12px]">
      {paso.llamadas?.map((l, i) => (
        <div key={i}>
          <div className="text-slate-500 mb-1">El modelo pide <span className="text-slate-300 font-mono">{l.nombre}</span></div>
          <pre className="font-mono text-[11px] bg-slate-950 rounded-md p-2 overflow-x-auto text-slate-300">{JSON.stringify(l.argumentos, null, 2)}</pre>
        </div>
      ))}
      {paso.traza?.map((t, i) => <DetalleTraza key={i} t={t} alVerFragmento={alVerFragmento} />)}
      {paso.revision?.length > 0 && (
        <div className="text-amber-300/90">Revisión humana: {paso.revision.join(' · ')}</div>
      )}
    </div>
  )
}

function DetalleTraza({ t, alVerFragmento }) {
  if (t.etapa === 'router' && t.triage) {
    return (
      <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-slate-400">
        <span>Categoría</span><span className="text-slate-200">{t.triage.categoria}</span>
        <span>Prioridad</span><span className="text-slate-200">{t.triage.prioridad}</span>
        <span>Ruta</span><span className="text-slate-200">{t.ruta}</span>
        <span>Permitidas</span><span className="font-mono text-slate-300">{(t.permitidas || []).join(', ')}</span>
        <span>Acuerdo</span>
        <span className="text-slate-200">{Object.entries(t.triage.confianza || {}).map(([k, v]) => `${k} ${(v * 100).toFixed(0)} %`).join(' · ')}</span>
      </div>
    )
  }
  if (t.etapa === 'herramienta') {
    return (
      <div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-slate-200">{t.nombre}</span>
          <span className={t.ok ? 'text-emerald-400' : 'text-rose-400'}>{t.ok ? 'correcta' : 'error'}</span>
          <span className="ml-auto font-mono text-slate-500">{t.segundos} s{t.intentos > 1 ? ` · ${t.intentos} intentos` : ''}</span>
        </div>
        {t.error && <div className="text-rose-300/90 mt-0.5">{t.error}</div>}
        {t.candidatos?.length > 0 && (
          <table className="w-full mt-1.5">
            <thead><tr className="text-slate-500 text-left"><th className="font-normal">Fragmento</th><th className="font-normal text-right">Score</th></tr></thead>
            <tbody>
              {t.candidatos.map((c) => (
                <tr key={c.chunk_id} className="hover:bg-slate-800/50 cursor-pointer" onClick={() => alVerFragmento(c.chunk_id)}>
                  <td className="py-0.5 pr-2 text-slate-300 truncate max-w-0 w-full">
                    <span className="font-mono text-[10.5px] text-indigo-300">{c.chunk_id}</span> · {fuenteCorta(c)} · {c.titulo}
                  </td>
                  <td className="py-0.5 text-right font-mono text-slate-400">{c.score.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    )
  }
  if (t.etapa === 'guardrail_salida' && t.errores?.length) {
    return <ul className="list-disc pl-4 text-amber-300/90">{t.errores.map((e) => <li key={e}>{e}</li>)}</ul>
  }
  if (t.etapa === 'aprobacion' && t.error) return <div className="text-amber-300/90">Aprobación inválida: {t.error}</div>
  return null
}
