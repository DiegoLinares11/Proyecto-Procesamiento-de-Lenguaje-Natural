// Pausa del grafo (interrupt): N2 aprueba o rechaza la acción. Los dos botones de abajo prueban los
// controles de seguridad: un N1 no puede aprobar y "true" escrito como texto no es un booleano.
import { useRef, useState } from 'react'
import { ShieldQuestion, UserCheck, UserX } from 'lucide-react'
import useDialogFocus from './useDialogFocus'

export default function Aprobacion({ solicitudes, notas = [], alDecidir }) {
  const [aprobador, setAprobador] = useState('Técnico N2')
  const dialogo = useRef(null)
  useDialogFocus(dialogo)
  const s = solicitudes[0]
  const ultimaNota = notas[notas.length - 1]
  const decidir = (decision) => alDecidir(decision)
  return (
    <div data-dialog-layer="50" className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-ink/45 backdrop-blur-sm p-4">
      <div ref={dialogo} role="dialog" aria-modal="true" aria-labelledby="aprobacion-titulo" aria-describedby="aprobacion-descripcion"
        className="max-h-[calc(100dvh-2rem)] w-full max-w-lg overflow-y-auto rounded-[20px] border border-border bg-surface text-ink shadow-2xl animar-entrada">
        <div className="px-5 pt-5 pb-5 sm:px-6">
          <div className="mb-4 flex items-center gap-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-xl border border-[#f4e0b6] bg-[#fffbeb] text-[#92400e]">
              <ShieldQuestion size={20} aria-hidden="true" />
            </span>
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[.14em] text-ink-muted">Revisión humana</div>
              <div className="mt-0.5 text-[13px] font-semibold text-[#92400e]">El grafo está en pausa</div>
            </div>
          </div>
          <h3 id="aprobacion-titulo" className="text-lg font-extrabold leading-snug tracking-tight">{s.pregunta}</h3>
          <p id="aprobacion-descripcion" className="mt-2 text-[13px] leading-relaxed text-ink-muted">
            Acción <span className="rounded bg-muted px-1 py-0.5 font-mono text-[12px] text-ink">{s.accion}</span> · solicitud #{s.solicitud_id}.
            No se ejecuta nada hasta que un técnico N2 decida. Es una simulación: no toca sistemas reales.
          </p>
          {ultimaNota && <p role="status" className="mt-4 rounded-lg border border-[#f4e0b6] bg-[#fffbeb] p-3 text-[13px] leading-relaxed text-[#92400e]">{ultimaNota}</p>}
          <label className="mt-5 block text-[12px] font-medium text-ink">Aprobador
            <input value={aprobador} onChange={(e) => setAprobador(e.target.value)}
              className="mt-1.5 w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm text-ink outline-none transition-shadow focus:border-brand focus:ring-3 focus:ring-brand/10" />
          </label>
          <div className="mt-5 grid grid-cols-1 gap-2 sm:grid-cols-2 sm:gap-3">
            <button type="button" onClick={() => decidir({ aprobada: true, aprobador, rol: 'N2' })}
              className="flex min-h-11 items-center justify-center gap-2 rounded-lg border border-[#16794d] bg-[#16794d] px-3 py-2.5 text-[13px] font-semibold text-white transition-colors hover:bg-[#12633f] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#16794d]">
              <UserCheck size={16} />Aprobar como N2
            </button>
            <button type="button" onClick={() => decidir({ aprobada: false, aprobador, rol: 'N2' })}
              className="flex min-h-11 items-center justify-center gap-2 rounded-lg border border-[#fecdca] bg-[#fef3f2] px-3 py-2.5 text-[13px] font-semibold text-[#b42318] transition-colors hover:bg-[#fee4e2] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#b42318]">
              <UserX size={16} />Rechazar
            </button>
          </div>
        </div>
        <div className="border-t border-border bg-muted px-5 py-4 sm:px-6">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[.12em] text-ink-muted">Probar los controles</div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => decidir({ aprobada: true, aprobador: 'Agente N1', rol: 'N1' })}
              className="min-h-9 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-[11px] font-semibold text-ink-muted transition-colors hover:border-brand/30 hover:text-brand-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand">
              Aprobar como N1
            </button>
            <button type="button" onClick={() => decidir({ aprobada: 'true', aprobador, rol: 'N2' })}
              className="min-h-9 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-[11px] font-semibold text-ink-muted transition-colors hover:border-brand/30 hover:text-brand-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand">
              Mandar <span className="font-mono">"true"</span> como texto
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
