// Métricas del banco de evaluación (resultados/evaluacion/<banco>/resumen.json) y la autopsia de una falla real.
import { useEffect, useState } from 'react'
import { Bug, CheckCircle2, ShieldCheck, TriangleAlert, XCircle } from 'lucide-react'
import { obtener } from '../api'

const SISTEMAS = [['agente', 'Agente (grafo)'], ['rag', 'RAG'], ['linea_base', 'Línea base']]
const ETIQUETAS = {
  recall_at_5: 'Recall@5', mrr: 'MRR', precision_contexto: 'Precisión de contexto', redundancia: 'Redundancia',
  fidelidad: 'Fidelidad (Ragas)', cobertura: 'Cobertura fáctica', relevancia: 'Relevancia', precision_citas: 'Precisión de citas',
  abstencion_correcta: 'Abstención correcta', falsas_abstenciones: 'Falsas abstenciones', validez_contrato: 'Validez del contrato',
  latencia_media_s: 'Latencia media (s)', latencia_p95_s: 'Latencia P95 (s)', costo_promedio_usd: 'Costo por ticket (US$)',
  ataques_bloqueados: 'Ataques bloqueados', control_acceso: 'Control de acceso', acciones_criticas_sin_aprobacion: 'Acciones sin aprobación',
}

const cumple = (metas, k, v) => {
  if (!(k in metas) || v == null) return null
  const [meta, sentido] = metas[k]
  return sentido === 'min' ? v >= meta : v <= meta
}
const fmt = (v) => (v == null ? '—' : typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(v < 1 ? 3 : 2)) : v)

export default function Evaluacion() {
  const [datos, setDatos] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => { obtener('/api/evaluacion').then(setDatos).catch(() => setError('Todavía no hay resultados: corran scripts/evaluar_banco.py.')) }, [])
  if (error) return <p className="text-slate-400">{error}</p>
  if (!datos) return <p className="text-slate-500">Cargando…</p>
  const { metas, sistemas } = datos
  const a = sistemas.agente || {}
  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {datos.borrador && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-[13px] text-amber-200">
          <TriangleAlert size={17} className="mt-0.5 shrink-0" />
          Resultados con el banco borrador ({datos.banco}). Los finales salen del banco oficial cuando el equipo lo termine.
        </div>
      )}

      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi titulo="Casos que pasan" valor={a.casos_que_pasan} nota={`${datos.casos} casos del banco`} />
        <Kpi titulo="Ataques bloqueados" valor={a.ataques_bloqueados != null ? `${Math.round(a.ataques_bloqueados * 100)} %` : '—'} nota="meta ≥ 95 %" ok={cumple(metas, 'ataques_bloqueados', a.ataques_bloqueados)} />
        <Kpi titulo="Acciones sin aprobación" valor={a.acciones_criticas_sin_aprobacion} nota="meta: 0" ok={cumple(metas, 'acciones_criticas_sin_aprobacion', a.acciones_criticas_sin_aprobacion)} />
        <Kpi titulo="Costo por ticket" valor={a.costo_promedio_usd != null ? `US$${a.costo_promedio_usd.toFixed(3)}` : '—'} nota="meta ≤ US$0.03" ok={cumple(metas, 'costo_promedio_usd', a.costo_promedio_usd)} />
      </section>

      <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
        <h3 className="font-semibold text-slate-100">La hipótesis: búsqueda híbrida + citas + abstención supera a BM25</h3>
        <p className="text-[13px] text-slate-400 mb-4">Mismos casos de RAG y alucinación para los tres sistemas.</p>
        <div className="grid md:grid-cols-3 gap-6">
          {['recall_at_5', 'abstencion_correcta', 'falsas_abstenciones'].map((k) => (
            <Barras key={k} titulo={ETIQUETAS[k]} meta={metas[k]} valores={SISTEMAS.map(([s, n]) => [n, sistemas[s]?.[k]])} />
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-800 bg-slate-900/50 overflow-hidden">
        <table className="w-full text-[13px]">
          <thead className="bg-slate-900 text-slate-400">
            <tr>
              <th className="text-left font-medium px-4 py-2.5">Métrica</th>
              <th className="text-left font-medium px-4 py-2.5">Meta</th>
              {SISTEMAS.map(([s, n]) => <th key={s} className="text-right font-medium px-4 py-2.5">{n}</th>)}
            </tr>
          </thead>
          <tbody>
            {Object.keys(ETIQUETAS).filter((k) => SISTEMAS.some(([s]) => sistemas[s]?.[k] != null)).map((k) => (
              <tr key={k} className="border-t border-slate-800/80">
                <td className="px-4 py-2 text-slate-200">{ETIQUETAS[k]}</td>
                <td className="px-4 py-2 font-mono text-[12px] text-slate-500">{metas[k] ? `${metas[k][1] === 'min' ? '≥' : '≤'} ${metas[k][0]}` : ''}</td>
                {SISTEMAS.map(([s]) => {
                  const v = sistemas[s]?.[k]
                  const ok = cumple(metas, k, v)
                  return (
                    <td key={s} className="px-4 py-2 text-right font-mono">
                      <span className={ok === true ? 'text-emerald-300' : ok === false ? 'text-rose-300' : 'text-slate-400'}>{fmt(v)}</span>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <Autopsia />
    </div>
  )
}

function Kpi({ titulo, valor, nota, ok }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/50 px-4 py-3.5">
      <div className="flex items-center gap-1.5 text-[12px] text-slate-400">
        {ok === true && <CheckCircle2 size={14} className="text-emerald-400" />}
        {ok === false && <XCircle size={14} className="text-rose-400" />}
        {titulo}
      </div>
      <div className="mt-1 text-2xl font-semibold text-slate-50">{valor ?? '—'}</div>
      <div className="text-[11.5px] text-slate-500">{nota}</div>
    </div>
  )
}

function Barras({ titulo, meta, valores }) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <span className="text-[13px] font-medium text-slate-200">{titulo}</span>
        {meta && <span className="font-mono text-[11px] text-slate-500">meta {meta[1] === 'min' ? '≥' : '≤'} {meta[0]}</span>}
      </div>
      <div className="space-y-2">
        {valores.map(([nombre, v]) => {
          const ok = meta && v != null ? (meta[1] === 'min' ? v >= meta[0] : v <= meta[0]) : null
          return (
            <div key={nombre}>
              <div className="flex justify-between text-[11.5px] text-slate-400"><span>{nombre}</span><span className="font-mono">{fmt(v)}</span></div>
              <div className="relative h-2 rounded-full bg-slate-800 overflow-hidden">
                <div className={`h-full rounded-full ${ok === false ? 'bg-rose-400/80' : 'bg-indigo-400'}`} style={{ width: `${Math.min(100, (v ?? 0) * 100)}%` }} />
                {meta && <div className="absolute top-0 h-full w-px bg-slate-300/70" style={{ left: `${meta[0] * 100}%` }} />}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function Autopsia() {
  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
      <div className="flex items-center gap-2 text-rose-300 text-[12px] font-semibold uppercase tracking-wider">
        <Bug size={15} />Diagnóstico de una falla real · caso H01
      </div>
      <h3 className="mt-1 text-lg font-semibold text-slate-100">El agente pedía filtrar, pero el esquema no lo dejaba</h3>
      <div className="mt-4 grid md:grid-cols-2 gap-5 text-[13.5px] leading-relaxed text-slate-300">
        <div className="space-y-3">
          <p><span className="text-slate-100 font-medium">Síntoma.</span> «¿Tiempo promedio de los tickets de RED de prioridad ALTA?»: el
            agente llamó 5 veces a <span className="font-mono">query_tickets</span>, siempre sin filtros (136 tickets), se quedó sin
            presupuesto y se abstuvo.</p>
          <p><span className="text-slate-100 font-medium">Causa.</span> En modo estricto el modelo escribe las claves en el orden del
            esquema. El discriminador <span className="font-mono">consulta</span> iba al final: cuando lo escribía, ya había pasado los
            filtros opcionales.</p>
          <p><span className="text-slate-100 font-medium">Comprobación.</span> Misma pregunta, 3 llamadas a la API con cada esquema:
            con <span className="font-mono">consulta</span> al final, 0 de 3 traían los filtros; primero, 3 de 3.</p>
          <p><span className="text-slate-100 font-medium">Arreglo y prueba.</span> El discriminador va primero en todos los esquemas y
            una llamada repetida ya no se ejecuta. La prueba falla con el código anterior. H01 ahora responde con una sola consulta:
            3.3 horas en 8 tickets.</p>
        </div>
        <div className="space-y-3 font-mono text-[11.5px]">
          <div>
            <div className="text-rose-300 mb-1 font-sans text-[12px]">Antes (0 de 3 con filtros)</div>
            <pre className="rounded-lg bg-slate-950 border border-rose-500/30 p-3 overflow-x-auto">{`{"desde": "2026-01-01",
 "hasta": "2026-06-30",
 "consulta": "tiempo_resolucion"}`}</pre>
          </div>
          <div>
            <div className="text-emerald-300 mb-1 font-sans text-[12px]">Después (3 de 3 con filtros)</div>
            <pre className="rounded-lg bg-slate-950 border border-emerald-500/30 p-3 overflow-x-auto">{`{"consulta": "tiempo_resolucion",
 "desde": "2026-01-01",
 "hasta": "2026-06-30",
 "categoria": "RED",
 "prioridad": "ALTA"}`}</pre>
          </div>
          <div className="flex items-center gap-1.5 font-sans text-[12px] text-slate-400">
            <ShieldCheck size={14} className="text-emerald-400" />La encontró la evaluación, no un usuario.
          </div>
        </div>
      </div>
    </section>
  )
}
