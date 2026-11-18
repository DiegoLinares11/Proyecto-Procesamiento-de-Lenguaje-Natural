// La respuesta del sistema: texto, citas verificables, banderas del contrato y el JSON tal cual.
import { useState } from 'react'
import { BookOpen, Braces, CircleSlash, Clock, Coins, Database, Globe, ShieldAlert, Ticket, Wrench } from 'lucide-react'
import { fuenteCorta, tipoFuente } from '../nodos'

const ICONO_FUENTE = { manual: BookOpen, articulo: Globe, consulta: Database, ticket: Ticket }

export default function Respuesta({ resultado, alVerFragmento }) {
  const [verJson, setVerJson] = useState(false)
  if (!resultado) return null
  const r = resultado.respuesta
  // Algunas respuestas traen "\n" escrito como texto (pendiente en hallazgos.md); aquí solo se muestra bien
  const texto = r.answer.replaceAll('\\n', '\n')
  return (
    <div className="space-y-4 animar-entrada">
      <div className="flex flex-wrap gap-1.5">
        {r.abstained
          ? <Insignia tono="amber" icono={CircleSlash}>Se abstuvo</Insignia>
          : <Insignia tono="emerald" icono={BookOpen}>Respondió con evidencia</Insignia>}
        {r.needs_human_review && <Insignia tono="amber" icono={ShieldAlert}>Revisión humana</Insignia>}
        {resultado.triage?.categoria && <Insignia tono="slate">{resultado.triage.categoria} · {resultado.triage.prioridad}</Insignia>}
      </div>

      <p className="text-[14.5px] leading-relaxed text-slate-100 whitespace-pre-line max-h-[38vh] overflow-y-auto pr-1">{texto}</p>

      {r.sources.length > 0 && (
        <div>
          <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Fuentes citadas</h4>
          <ul className="space-y-1">
            {r.sources.map((s, i) => {
              const Icono = ICONO_FUENTE[tipoFuente(s)]
              const esConsulta = s.chunk_id.startsWith('sql-')
              return (
                <li key={s.chunk_id}>
                  <button type="button" disabled={esConsulta} onClick={() => alVerFragmento(s.chunk_id)}
                    className="w-full flex items-center gap-2.5 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2 text-left enabled:hover:border-indigo-500/60 enabled:hover:bg-slate-800/60 transition">
                    <span className="grid place-items-center size-5 rounded bg-indigo-500/20 text-[11px] font-bold text-indigo-300">{i + 1}</span>
                    <Icono size={15} className="text-slate-400 shrink-0" />
                    <span className="text-[13px] text-slate-200 truncate">{fuenteCorta(s)}</span>
                    <span className="ml-auto font-mono text-[10.5px] text-slate-500">{s.chunk_id}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {r.needs_human_review && resultado.revision?.length > 0 && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[12.5px] text-amber-200">
          <span className="font-semibold">Por qué pide revisión: </span>{resultado.revision.join(' · ')}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-slate-400 border-t border-slate-800 pt-3">
        <span className="flex items-center gap-1.5"><Wrench size={13} />{r.tool_used || 'ninguna'}</span>
        <span className="flex items-center gap-1.5"><Clock size={13} />{resultado.segundos_total.toFixed(1)} s</span>
        <span className="flex items-center gap-1.5"><Coins size={13} />US${resultado.costo_usd.toFixed(4)}</span>
        <button type="button" onClick={() => setVerJson(!verJson)} className="ml-auto flex items-center gap-1.5 text-indigo-300 hover:text-indigo-200">
          <Braces size={13} />{verJson ? 'Ocultar' : 'Ver'} contrato JSON
        </button>
      </div>
      {verJson && (
        <pre className="font-mono text-[11px] leading-relaxed bg-slate-950 border border-slate-800 rounded-lg p-3 overflow-x-auto text-slate-300">
          {JSON.stringify(r, null, 2)}
        </pre>
      )}
    </div>
  )
}

const TONOS = {
  emerald: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  amber: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  rose: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
  slate: 'bg-slate-800 text-slate-300 border-slate-700',
}

export function Insignia({ tono = 'slate', icono: Icono, children }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12px] font-medium ${TONOS[tono]}`}>
      {Icono && <Icono size={13} />}{children}
    </span>
  )
}
