// La respuesta del sistema: texto, citas verificables, banderas del contrato y el JSON tal cual.
import { useState } from 'react'
import { ArrowUpRight, BookOpen, Braces, CircleSlash, Clock, Coins, Database, Globe, ShieldAlert, Ticket, Wrench } from 'lucide-react'
import { fuenteCorta, tipoFuente } from '../nodos'

const ICONO_FUENTE = { manual: BookOpen, articulo: Globe, consulta: Database, ticket: Ticket }

export default function Respuesta({ resultado, alVerFragmento }) {
  const [verJson, setVerJson] = useState(false)
  if (!resultado) return null
  const r = resultado.respuesta
  // Algunas respuestas traen "\n" escrito como texto (pendiente en hallazgos.md); aquí solo se muestra bien
  const texto = r.answer.replaceAll('\\n', '\n')
  return (
    <div className="min-w-0 space-y-5 animar-entrada">
      <div className="flex flex-wrap gap-2" aria-label="Estado de la respuesta">
        {r.abstained
          ? <Insignia tono="amber" icono={CircleSlash}>Se abstuvo</Insignia>
          : <Insignia tono="emerald" icono={BookOpen}>Respondió con evidencia</Insignia>}
        {r.needs_human_review && <Insignia tono="amber" icono={ShieldAlert}>Revisión humana</Insignia>}
        {resultado.triage?.categoria && <Insignia tono="slate">{resultado.triage.categoria} · {resultado.triage.prioridad}</Insignia>}
      </div>

      <div className="rounded-[20px] border border-border bg-muted p-4 sm:p-5">
        <p className="max-h-[38vh] overflow-y-auto pr-1 text-[14px] leading-[1.8] text-ink whitespace-pre-line [overflow-wrap:anywhere]">{texto}</p>
      </div>

      {r.sources.length > 0 && (
        <div>
          <h4 className="mb-2.5 text-[11px] font-extrabold uppercase tracking-[0.12em] text-ink-muted">Fuentes citadas</h4>
          <ul className="space-y-2">
            {r.sources.map((s, i) => {
              const Icono = ICONO_FUENTE[tipoFuente(s)]
              const esConsulta = s.chunk_id.startsWith('sql-')
              return (
                <li key={s.chunk_id}>
                  <button type="button" disabled={esConsulta} onClick={() => alVerFragmento(s.chunk_id)}
                    className="group flex w-full min-w-0 items-start gap-3 rounded-[20px] border border-border bg-surface p-3 text-left font-semibold transition enabled:hover:border-brand/35 enabled:hover:bg-brand-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 disabled:cursor-default disabled:bg-muted sm:items-center"
                    aria-label={`Fuente citada: ${fuenteCorta(s)}`}>
                    <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg bg-brand-soft font-mono text-[11px] font-semibold text-brand-strong sm:mt-0">{i + 1}</span>
                    <Icono size={16} className="mt-1.5 shrink-0 text-ink-muted sm:mt-0" aria-hidden="true" />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[12.5px] font-semibold leading-relaxed text-ink [overflow-wrap:anywhere]">{fuenteCorta(s)}</span>
                      <span className="mt-0.5 block font-mono text-[10px] leading-relaxed text-ink-muted [overflow-wrap:anywhere]">{s.chunk_id}</span>
                    </span>
                    <span className="mt-1.5 inline-flex shrink-0 items-center gap-1 text-brand group-disabled:invisible sm:mt-0" aria-hidden="true"><ArrowUpRight size={15} /></span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {r.needs_human_review && resultado.revision?.length > 0 && (
        <div className="rounded-[20px] border border-[#fde68a] bg-[#fffbeb] px-4 py-3 text-[12.5px] leading-relaxed text-[#92400e]">
          <span className="font-semibold">Por qué pide revisión: </span>{resultado.revision.join(' · ')}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-3 border-t border-border pt-4 text-[11.5px] text-ink-muted">
        <span className="flex items-center gap-1.5"><Wrench size={13} />Herramienta: {r.tool_used || 'ninguna'}</span>
        <span className="flex items-center gap-1.5"><Clock size={13} />{resultado.segundos_total.toFixed(1)} s</span>
        <span className="flex items-center gap-1.5" title="Cargo incremental de API; la consulta también consume cuota de ChatGPT/Codex."><Coins size={13} />API: US${resultado.costo_usd.toFixed(4)}</span>
        <button type="button" onClick={() => setVerJson(!verJson)} aria-expanded={verJson}
          className="flex min-h-9 items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 font-semibold text-ink-muted transition hover:border-brand/30 hover:bg-brand-soft hover:text-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 sm:ml-auto">
          <Braces size={13} />{verJson ? 'Ocultar' : 'Ver'} contrato JSON
        </button>
      </div>
      {verJson && (
        <pre className="max-w-full overflow-x-auto rounded-[20px] border border-border bg-muted p-4 font-mono text-[11px] leading-relaxed text-ink" tabIndex={0} aria-label="Contrato JSON de la respuesta">
          {JSON.stringify(r, null, 2)}
        </pre>
      )}
    </div>
  )
}

const TONOS = {
  emerald: 'bg-[#ecfdf3] text-[#16794d] border-[#bbebce]',
  amber: 'bg-[#fffbeb] text-[#92400e] border-[#fde68a]',
  rose: 'bg-[#fef3f2] text-[#b42318] border-[#fecdca]',
  slate: 'bg-muted text-ink-muted border-border',
}

export function Insignia({ tono = 'slate', icono: Icono, children }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium ${TONOS[tono]}`}>
      {Icono && <Icono size={13} />}{children}
    </span>
  )
}
