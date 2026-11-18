// La traza paso a paso: lo que hizo cada nodo, cuánto tardó y, al abrirlo, el detalle.
import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { NODOS, fuenteCorta, resumirPaso } from '../nodos'

export default function Linea({ pasos, corriendo, alVerFragmento }) {
  if (!pasos.length && !corriendo) {
    return <p className="rounded-xl border border-dashed border-border bg-muted px-4 py-5 text-[13px] leading-relaxed text-ink-muted">Aquí aparece cada paso del grafo mientras corre.</p>
  }
  return (
    <ol className="relative space-y-2" aria-label="Pasos del grafo">
      {pasos.map((p, i) => <Paso key={i} paso={p} alVerFragmento={alVerFragmento} />)}
      {corriendo && (
        <li role="status" className="flex items-center gap-2.5 rounded-lg bg-brand-soft px-3 py-2.5 text-[12px] font-medium text-brand-strong">
          <span className="size-2 rounded-full bg-brand animar-brillo" aria-hidden="true" /> Trabajando…
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
    <li className="animar-entrada overflow-hidden rounded-[20px] border border-border bg-surface">
      <button type="button" onClick={() => conDetalle && setAbierto(!abierto)}
        aria-expanded={conDetalle ? abierto : undefined}
        className={`w-full flex items-start gap-3 px-3 py-3 text-left transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand ${conDetalle ? 'cursor-pointer hover:bg-muted' : 'cursor-default'}`}>
        <span className="grid size-8 shrink-0 place-items-center rounded-lg border border-brand/15 bg-brand-soft text-brand-strong">
          <Icono size={16} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <span className="text-[12px] font-extrabold leading-5 text-ink">{nodo.nombre}</span>
            <span className="ml-auto shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] leading-4 text-ink-muted">{paso.segundos.toFixed(2)} s</span>
          </div>
          <p className="mt-0.5 break-words text-[12px] leading-relaxed text-ink-muted">{resumirPaso(paso)}</p>
        </div>
        {conDetalle && <ChevronRight size={15} aria-hidden="true" className={`mt-2 shrink-0 text-ink-muted transition-transform ${abierto ? 'rotate-90' : ''}`} />}
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
    <div className="space-y-3 border-t border-border bg-muted px-3 py-3 text-[12px] leading-relaxed">
      {paso.llamadas?.map((l, i) => (
        <div key={i}>
          <div className="mb-1.5 text-ink-muted">El modelo pide <span className="font-mono text-[11px] text-ink">{l.nombre}</span></div>
          <pre className="overflow-x-auto rounded-lg border border-border bg-surface p-2.5 font-mono text-[11px] leading-relaxed text-[#475467]">{JSON.stringify(l.argumentos, null, 2)}</pre>
        </div>
      ))}
      {paso.traza?.map((t, i) => <DetalleTraza key={i} t={t} alVerFragmento={alVerFragmento} />)}
      {paso.revision?.length > 0 && (
        <div className="rounded-lg border border-[#f4e0b6] bg-[#fffbeb] px-2.5 py-2 text-[#92400e]">Revisión humana: {paso.revision.join(' · ')}</div>
      )}
    </div>
  )
}

function DetalleTraza({ t, alVerFragmento }) {
  if (t.etapa === 'router' && t.triage) {
    return (
      <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-ink-muted">
        <span>Categoría</span><span className="font-medium text-ink">{t.triage.categoria}</span>
        <span>Prioridad</span><span className="font-medium text-ink">{t.triage.prioridad}</span>
        <span>Ruta</span><span className="break-words text-ink">{t.ruta}</span>
        <span>Permitidas</span><span className="break-words font-mono text-[11px] text-[#475467]">{(t.permitidas || []).join(', ')}</span>
        <span>Acuerdo</span>
        <span className="text-ink">{Object.entries(t.triage.confianza || {}).map(([k, v]) => `${k} ${(v * 100).toFixed(0)} %`).join(' · ')}</span>
      </div>
    )
  }
  if (t.etapa === 'herramienta') {
    return (
      <div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="break-all font-mono text-[11px] font-medium text-ink">{t.nombre}</span>
          <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${t.ok ? 'bg-[#ecfdf3] text-[#16794d]' : 'bg-[#fef3f2] text-[#b42318]'}`}>{t.ok ? 'correcta' : 'error'}</span>
          <span className="ml-auto font-mono text-[10px] text-ink-muted">{t.segundos} s{t.intentos > 1 ? ` · ${t.intentos} intentos` : ''}</span>
        </div>
        {t.error && <div className="mt-2 rounded-md border border-[#fecdca] bg-[#fef3f2] px-2 py-1.5 text-[#b42318]">{t.error}</div>}
        {t.candidatos?.length > 0 && (
          <table className="mt-2 w-full border-separate border-spacing-0">
            <thead><tr className="text-left text-[10px] uppercase tracking-wide text-ink-muted"><th className="border-b border-border pb-1.5 font-medium">Fragmento</th><th className="border-b border-border pb-1.5 text-right font-medium">Score</th></tr></thead>
            <tbody>
              {t.candidatos.map((c) => (
                <tr key={c.chunk_id} className="cursor-pointer transition-colors hover:bg-brand-soft" onClick={() => alVerFragmento(c.chunk_id)}>
                  <td className="w-full max-w-0 truncate border-b border-border py-2 pr-2 text-[#475467]">
                    <button type="button" aria-label={`Ver fragmento ${c.chunk_id}`} className="block w-full truncate text-left font-semibold focus-visible:outline-2 focus-visible:outline-brand">
                      <span className="font-mono text-[10.5px] font-medium text-brand-strong">{c.chunk_id}</span> · {fuenteCorta(c)} · {c.titulo}
                    </button>
                  </td>
                  <td className="border-b border-border py-2 text-right font-mono text-[11px] text-ink-muted">{c.score.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    )
  }
  if (t.etapa === 'guardrail_salida' && t.errores?.length) {
    return <ul className="list-disc space-y-1 rounded-lg border border-[#f4e0b6] bg-[#fffbeb] py-2 pr-2 pl-6 text-[#92400e]">{t.errores.map((e) => <li key={e}>{e}</li>)}</ul>
  }
  if (t.etapa === 'aprobacion' && t.error) return <div className="rounded-lg border border-[#f4e0b6] bg-[#fffbeb] px-2.5 py-2 text-[#92400e]">Aprobación inválida: {t.error}</div>
  return null
}
