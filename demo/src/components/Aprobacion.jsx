// Pausa del grafo (interrupt): N2 aprueba o rechaza la acción. Los dos botones de abajo prueban los
// controles de seguridad: un N1 no puede aprobar y "true" escrito como texto no es un booleano.
import { useState } from 'react'
import { ShieldQuestion, UserCheck, UserX } from 'lucide-react'

export default function Aprobacion({ solicitudes, alDecidir }) {
  const [aprobador, setAprobador] = useState('Técnico N2')
  const s = solicitudes[0]
  const decidir = (decision) => alDecidir(decision)
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/70 backdrop-blur-sm p-4">
      <div className="w-full max-w-md rounded-2xl border border-amber-500/40 bg-slate-900 shadow-2xl animar-entrada">
        <div className="px-6 pt-5 pb-4">
          <div className="flex items-center gap-2 text-amber-300 text-[12px] font-semibold uppercase tracking-wider">
            <ShieldQuestion size={16} />El grafo está en pausa
          </div>
          <h3 className="mt-2 text-lg font-semibold text-slate-100">{s.pregunta}</h3>
          <p className="mt-1 text-[13px] text-slate-400">
            Acción <span className="font-mono text-slate-200">{s.accion}</span> · solicitud #{s.solicitud_id}.
            No se ejecuta nada hasta que un técnico N2 decida. Es una simulación: no toca sistemas reales.
          </p>
          <label className="block mt-4 text-[12px] text-slate-400">Aprobador
            <input value={aprobador} onChange={(e) => setAprobador(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-indigo-500" />
          </label>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <button type="button" onClick={() => decidir({ aprobada: true, aprobador, rol: 'N2' })}
              className="flex items-center justify-center gap-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 py-2.5 text-sm font-semibold text-slate-950">
              <UserCheck size={16} />Aprobar como N2
            </button>
            <button type="button" onClick={() => decidir({ aprobada: false, aprobador, rol: 'N2' })}
              className="flex items-center justify-center gap-2 rounded-lg bg-rose-500/90 hover:bg-rose-400 py-2.5 text-sm font-semibold text-white">
              <UserX size={16} />Rechazar
            </button>
          </div>
        </div>
        <div className="border-t border-slate-800 px-6 py-3 bg-slate-950/40 rounded-b-2xl">
          <div className="text-[11px] uppercase tracking-wider text-slate-500 mb-1.5">Probar los controles</div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => decidir({ aprobada: true, aprobador: 'Agente N1', rol: 'N1' })}
              className="rounded-md border border-slate-700 px-2.5 py-1 text-[12px] text-slate-300 hover:border-slate-500">
              Aprobar como N1
            </button>
            <button type="button" onClick={() => decidir({ aprobada: 'true', aprobador, rol: 'N2' })}
              className="rounded-md border border-slate-700 px-2.5 py-1 text-[12px] text-slate-300 hover:border-slate-500">
              Mandar <span className="font-mono">"true"</span> como texto
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
