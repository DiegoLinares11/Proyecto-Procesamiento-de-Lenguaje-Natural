// Sólo consulta resultados y progreso guardados. Visitar o actualizar no ejecuta evaluaciones.
import { useEffect, useState } from 'react'
import { BarChart3, Bug, CheckCircle2, Clock3, FileSearch, Info, LoaderCircle, RefreshCw, ShieldCheck, TriangleAlert, XCircle } from 'lucide-react'

const SISTEMAS = [['agente', 'Agente (grafo)'], ['rag', 'RAG'], ['linea_base', 'Línea base']]
const ETIQUETAS = {
  recall_at_5: 'Recall@5', mrr: 'MRR', precision_contexto: 'Precisión de contexto', redundancia: 'Redundancia',
  fidelidad: 'Fidelidad (Ragas)', cobertura: 'Cobertura fáctica', relevancia: 'Relevancia', precision_citas: 'Precisión de citas',
  abstencion_correcta: 'Abstención correcta', falsas_abstenciones: 'Falsas abstenciones', validez_contrato: 'Validez del contrato',
  latencia_media_s: 'Latencia media (s)', latencia_p95_s: 'Latencia P95 (s)', costo_promedio_usd: 'Cargo API por ticket (US$)',
  ataques_bloqueados: 'Pruebas de seguridad superadas', control_acceso: 'Control de acceso', acciones_criticas_sin_aprobacion: 'Acciones sin aprobación',
}

const cumple = (metas, k, v) => {
  if (!(k in metas) || v == null) return null
  const [meta, sentido] = metas[k]
  return sentido === 'min' ? v >= meta : v <= meta
}
const fmt = (v) => (v == null ? '—' : typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(v < 1 ? 3 : 2)) : v)

export default function Evaluacion() {
  const [datos, setDatos] = useState(null)
  const [progreso, setProgreso] = useState(null)
  const [estados, setEstados] = useState({})
  const [cargando, setCargando] = useState(true)
  const [consulta, setConsulta] = useState(0)
  useEffect(() => {
    const controlador = new AbortController()
    setCargando(true)
    setDatos(null)
    setProgreso(null)
    setEstados({})
    async function leer(url) {
      const respuesta = await fetch(url, { method: 'GET', cache: 'no-store', signal: controlador.signal })
      if (respuesta.status === 404) return { estado: 'ausente' }
      if (!respuesta.ok) throw new Error('servicio')
      const contenido = await respuesta.json()
      if (!contenido || typeof contenido !== 'object' || Array.isArray(contenido)) throw new Error('formato')
      return { estado: 'disponible', contenido }
    }
    async function cargar() {
      const [resultado, avance] = await Promise.allSettled([leer('/api/evaluacion'), leer('/api/evaluacion/progreso')])
      if (controlador.signal.aborted) return
      const resumen = resultado.status === 'fulfilled' ? resultado.value : { estado: 'error' }
      const guardado = avance.status === 'fulfilled' ? avance.value : { estado: 'error' }
      if (resumen.contenido && (!resumen.contenido.sistemas || !resumen.contenido.metas)) resumen.estado = 'error'
      if (guardado.contenido && !['sin_datos', 'por_completar', 'interrumpida', 'completa'].includes(guardado.contenido.estado)) guardado.estado = 'error'
      setDatos(resumen.estado === 'disponible' ? resumen.contenido : null)
      setProgreso(guardado.estado === 'disponible' ? guardado.contenido : null)
      setEstados({ resultados: resumen.estado, progreso: guardado.estado })
      setCargando(false)
    }
    cargar()
    return () => controlador.abort()
  }, [consulta])
  return (
    <div className="mx-auto min-w-0 max-w-6xl space-y-6" aria-busy={cargando}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <Encabezado />
        <button type="button" onClick={() => setConsulta((v) => v + 1)} disabled={cargando} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-border bg-surface px-4 py-2.5 text-xs font-semibold text-brand transition hover:bg-brand-soft disabled:cursor-wait disabled:opacity-60">
          <RefreshCw size={15} className={cargando ? 'animate-spin' : ''} aria-hidden="true" />{cargando ? 'Consultando…' : 'Actualizar datos guardados'}
        </button>
      </div>
      <Proposito />
      {cargando ? <section className="rounded-[20px] border border-border bg-surface p-6" role="status"><p className="flex items-center gap-3 text-sm font-semibold text-ink"><LoaderCircle size={19} className="animate-spin text-brand" aria-hidden="true" />Consultando la evaluación guardada…</p><p className="mt-2 text-xs leading-relaxed text-ink-muted">Leyendo el avance y los resultados disponibles.</p></section> : <>
        {(estados.resultados === 'error' || estados.progreso === 'error' || estados.progreso === 'ausente') && <div className="flex items-start gap-3 rounded-xl border border-[#fecdca] bg-[#fef3f2] px-5 py-4 text-xs leading-relaxed text-[#b42318]" role="alert"><TriangleAlert size={19} className="shrink-0" aria-hidden="true" /><div><p className="font-bold">No se pudo consultar toda la evaluación</p><p className="mt-1">{estados.resultados === 'error' ? 'El servicio de métricas no respondió correctamente. ' : ''}{estados.progreso === 'ausente' ? 'La consulta de progreso aún no está disponible en este servicio. ' : estados.progreso === 'error' ? 'El servicio no pudo leer el progreso guardado. ' : ''}Podés volver a consultar con Actualizar datos guardados.</p></div></div>}
        {progreso && <Progreso datos={progreso} />}
        {!datos && estados.resultados === 'ausente' && <section className="flex items-start gap-3 rounded-[20px] border border-border bg-surface p-5 sm:p-6" role="status"><Info size={21} className="mt-0.5 shrink-0 text-brand" aria-hidden="true" /><div><h2 className="text-sm font-extrabold text-ink">Aún no hay métricas finales</h2><p className="mt-1 text-xs leading-relaxed text-ink-muted">La comparación de calidad, seguridad y tiempos aparecerá al completar la evaluación y su calificación. {progreso?.generaciones ? 'El avance de respuestas guardadas se muestra arriba.' : 'Todavía no hay resultados para comparar.'}</p></div></section>}
        {datos && <Resultados datos={datos} />}
      </>}
      <p className="text-[11px] leading-relaxed text-ink-muted">Esta vista consulta archivos guardados. Abrirla o actualizarla no inicia modelos ni consume cuota de evaluación.</p>
    </div>
  )
}

function Resultados({ datos }) {
  const { metas = {}, sistemas = {} } = datos
  const a = sistemas.agente || {}
  return (
    <div className="min-w-0 space-y-6">
      {datos.borrador && (
        <div className="flex items-start gap-2.5 rounded-xl border border-[#fde68a] bg-[#fffbeb] px-4 py-3 text-[12.5px] leading-relaxed text-[#92400e]">
          <TriangleAlert size={17} className="mt-0.5 shrink-0" />
          Resultados con el banco borrador ({datos.banco}). Los finales salen del banco oficial cuando el equipo lo termine.
        </div>
      )}
      <p className="rounded-xl border border-border bg-surface px-4 py-3 text-[12px] leading-relaxed text-ink-muted sm:px-5">{datos.historico ? 'Se muestran resultados históricos de Claude: todavía no hay una evaluación de Codex para este banco.' : 'Se muestran resultados de Codex con la suscripción de ChatGPT.'} Las corridas históricas conservan sus métricas y costos originales. Las consultas por suscripción consumen cuota incluida aunque su cargo incremental de API sea US$0.</p>

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Indicadores principales">
        <Kpi titulo="Casos que pasan" valor={a.casos_que_pasan} nota={`${datos.casos} casos del banco`} />
        <Kpi titulo="Pruebas de seguridad superadas" valor={a.ataques_bloqueados != null ? `${Math.round(a.ataques_bloqueados * 100)} %` : '—'} nota="meta ≥ 95 %" ok={cumple(metas, 'ataques_bloqueados', a.ataques_bloqueados)} />
        <Kpi titulo="Acciones sin aprobación" valor={a.acciones_criticas_sin_aprobacion} nota="meta: 0" ok={cumple(metas, 'acciones_criticas_sin_aprobacion', a.acciones_criticas_sin_aprobacion)} />
        <Kpi titulo="Cargo API por ticket" valor={a.costo_promedio_usd != null ? `US$${a.costo_promedio_usd.toFixed(3)}` : '—'} nota="meta ≤ US$0.03; cuota aparte" ok={cumple(metas, 'costo_promedio_usd', a.costo_promedio_usd)} />
      </section>

      <section className="rounded-[20px] border border-border bg-surface p-5 shadow-[0_4px_18px_#11224005] sm:p-6">
        <div className="mb-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-brand-strong">Comparación de sistemas</div>
        <h3 className="max-w-3xl text-[15px] font-extrabold leading-relaxed text-ink">La hipótesis: búsqueda híbrida + citas + abstención supera a BM25</h3>
        <p className="mb-6 mt-1.5 text-[12px] leading-relaxed text-ink-muted">Mismos casos de RAG y alucinación para los tres sistemas.</p>
        <div className="grid gap-6 md:grid-cols-3 md:gap-7">
          {['recall_at_5', 'abstencion_correcta', 'falsas_abstenciones'].map((k) => (
            <Barras key={k} titulo={ETIQUETAS[k]} meta={metas[k]} valores={SISTEMAS.map(([s, n]) => [n, sistemas[s]?.[k]])} />
          ))}
        </div>
      </section>

      <section className="min-w-0 overflow-hidden rounded-[20px] border border-border bg-surface shadow-[0_4px_18px_#11224005]">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4 sm:px-6">
          <div><h3 className="text-sm font-extrabold text-ink">Detalle de métricas</h3><p className="mt-1 text-[11.5px] text-ink-muted">Valores medidos y objetivos de referencia por sistema.</p></div>
          <div className="flex items-center gap-3 text-[10px] text-ink-muted"><span className="inline-flex items-center gap-1.5"><span className="size-1.5 rounded-full bg-[#16794d]" />Cumple la meta</span><span className="inline-flex items-center gap-1.5"><span className="size-1.5 rounded-full bg-[#b42318]" />Por revisar</span></div>
        </div>
        <div className="max-w-full overflow-x-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand" role="region" aria-label="Tabla comparativa de métricas; desplaza horizontalmente para ver todos los sistemas" tabIndex={0}>
        <table className="w-full min-w-[740px] text-[12px]">
          <caption className="sr-only">Métricas de evaluación, sus metas y resultados del agente, RAG y línea base.</caption>
          <thead className="bg-muted text-ink-muted">
            <tr>
              <th scope="col" className="sticky left-0 z-10 min-w-60 bg-muted px-5 py-3.5 text-left font-semibold">Métrica</th>
              <th scope="col" className="px-4 py-3.5 text-left font-semibold">Meta</th>
              {SISTEMAS.map(([s, n]) => <th scope="col" key={s} className="whitespace-nowrap px-5 py-3.5 text-right font-semibold">{n}</th>)}
            </tr>
          </thead>
          <tbody>
            {Object.keys(ETIQUETAS).filter((k) => SISTEMAS.some(([s]) => sistemas[s]?.[k] != null)).map((k) => (
              <tr key={k} className="group border-t border-border/75 transition hover:bg-muted">
                <td className="sticky left-0 bg-surface px-5 py-3 font-medium text-ink group-hover:bg-muted">{ETIQUETAS[k]}</td>
                <td className="whitespace-nowrap px-4 py-3 font-mono text-[11px] text-ink-muted">{metas[k] ? `${metas[k][1] === 'min' ? '≥' : '≤'} ${metas[k][0]}` : ''}</td>
                {SISTEMAS.map(([s]) => {
                  const v = sistemas[s]?.[k]
                  const ok = cumple(metas, k, v)
                  return (
                    <td key={s} className="px-5 py-3 text-right font-mono">
                      <span className={ok === true ? 'text-[#16794d]' : ok === false ? 'text-[#b42318]' : 'text-ink-muted'}>{fmt(v)}</span>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </section>

      <Autopsia />
    </div>
  )
}

function Encabezado() {
  return <header className="flex items-start gap-3.5">
    <span className="grid size-11 shrink-0 place-items-center rounded-xl border border-brand/10 bg-brand-soft text-brand"><BarChart3 size={21} aria-hidden="true" /></span>
    <div><h1 className="text-xl font-extrabold leading-snug tracking-[-0.02em] text-ink sm:text-2xl">Evaluación de PILAS</h1><p className="mt-1 text-[12.5px] leading-relaxed text-ink-muted">Cómo comprobamos que las respuestas son útiles, seguras y oportunas.</p></div>
  </header>
}

function Proposito() {
  const dimensiones = [
    [FileSearch, 'Calidad y fuentes', '¿Encuentra la información correcta?', 'Revisa la recuperación de documentos, las citas y si la respuesta se apoya en las fuentes. También mide cuándo corresponde abstenerse.'],
    [ShieldCheck, 'Seguridad', '¿Respeta los límites de la mesa de ayuda?', 'Comprueba el bloqueo de ataques, el acceso por rol y la aprobación humana antes de acciones críticas.'],
    [Clock3, 'Tiempos y costo', '¿Cuánto tarda en responder?', 'Compara el tiempo medio y el P95 —el límite que cubre el 95 % de los tiempos—, junto con el cargo API por ticket.'],
  ]
  return <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-6" aria-label="Para qué sirve la evaluación">
    <div className="rounded-[20px] bg-brand p-6 text-white sm:col-span-2 lg:col-span-4 sm:p-7">
      <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-[#d8f64e]">Evidencia para el proyecto académico</span>
      <h2 className="mt-3 max-w-xl text-xl font-extrabold leading-snug tracking-[-0.02em] sm:text-2xl">¿Qué tan bien resuelve PILAS los casos de soporte?</h2>
      <p className="mt-3 max-w-2xl text-[13px] leading-relaxed text-white/90">Esta sección reúne pruebas con respuestas esperadas para comprobar la calidad del sistema, detectar fallas y sustentar las conclusiones del informe.</p>
    </div>
    <div className="rounded-[20px] border border-border bg-surface p-6 sm:col-span-2 lg:col-span-2">
      <h3 className="text-sm font-extrabold text-ink">Una comparación de tres sistemas</h3>
      <p className="mt-2 text-xs leading-relaxed text-ink-muted">Los mismos casos de recuperación y alucinación permiten comparar estas tres alternativas:</p>
      <div className="mt-4 flex flex-wrap gap-2">{SISTEMAS.map(([s, nombre]) => <span key={s} className="rounded-lg bg-brand-soft px-3 py-2 text-[11px] font-semibold text-brand">{nombre}</span>)}</div>
    </div>
    {dimensiones.map(([Icono, titulo, pregunta, detalle]) => <article key={titulo} className="rounded-[20px] border border-border bg-surface p-5 sm:col-span-2 lg:col-span-2 sm:p-6">
      <div className="mb-4 flex items-center gap-2.5 text-brand"><span className="grid size-9 place-items-center rounded-xl bg-brand-soft"><Icono size={19} aria-hidden="true" /></span><h3 className="text-sm font-extrabold">{titulo}</h3></div>
      <p className="text-[12px] font-bold leading-relaxed text-ink">{pregunta}</p><p className="mt-1.5 text-xs leading-relaxed text-ink-muted">{detalle}</p>
    </article>)}
  </section>
}

function Progreso({ datos }) {
  const g = datos.generaciones
  const completa = datos.estado === 'completa'
  const sinDatos = datos.estado === 'sin_datos'
  const fecha = datos.actualizado_utc && new Date(datos.actualizado_utc)
  const registro = fecha && !Number.isNaN(fecha.getTime()) ? fecha.toLocaleString('es-GT', { timeZone: 'America/Guatemala', dateStyle: 'medium', timeStyle: 'short' }) : null
  return <section className="overflow-hidden rounded-[20px] border border-border bg-surface" aria-labelledby="evaluacion-progreso-titulo">
    <div className="flex flex-wrap items-start justify-between gap-5 p-5 sm:p-6">
      <div className="min-w-0 max-w-2xl">
        <span className="text-[10px] font-bold uppercase tracking-[0.13em] text-brand">Avance guardado · {datos.banco}</span>
        <div className="mt-2 flex flex-wrap items-center gap-3"><h2 id="evaluacion-progreso-titulo" className="text-lg font-extrabold text-ink">{completa ? 'Evaluación completa' : sinDatos ? 'Sin una evaluación guardada' : 'Evaluación por completar'}</h2>{datos.estado === 'interrumpida' && <span className="rounded-full bg-[#fff4dc] px-3 py-1 text-[10px] font-bold text-[#805512]">Interrumpida</span>}</div>
        <p className="mt-2 text-xs leading-relaxed text-ink-muted">{completa ? 'El resumen final ya está guardado; las métricas se presentan en la comparación.' : sinDatos ? 'Todavía no se ha registrado avance para este banco. Aquí aparecerá su progreso cuando haya archivos de evaluación.' : datos.estado === 'interrumpida' ? 'El último registro indica que la ejecución se interrumpió y el proceso evaluador no estaba activo. Se conservan las respuestas generadas.' : 'Hay archivos de evaluación, pero todavía no acreditan un cierre completo. Este avance guardado no confirma una ejecución activa.'}</p>
      </div>
      {g && <div className="min-w-36 rounded-xl bg-muted px-5 py-4"><div className="font-mono text-3xl font-semibold tracking-[-0.04em] text-ink">{g.completas}<span className="text-lg text-ink-muted"> / {g.planeadas}</span></div><div className="mt-1 text-[11px] text-ink-muted">respuestas generadas</div></div>}
    </div>
    {g && <div className="grid gap-5 px-5 pb-6 sm:grid-cols-3 sm:px-6">{SISTEMAS.map(([s, nombre]) => {
      const fila = g.por_sistema?.[s]
      if (!fila) return null
      return <div key={s}><div className="mb-2 flex items-center justify-between gap-2 text-xs"><span className="font-semibold text-ink">{nombre}</span><span className="font-mono text-ink-muted">{fila.completas}/{fila.planeadas}</span></div><div className="h-2 overflow-hidden rounded-full bg-brand-soft" role="progressbar" aria-label={`Respuestas generadas por ${nombre}`} aria-valuenow={fila.completas} aria-valuemin={0} aria-valuemax={fila.planeadas}><div className="h-full rounded-full bg-brand" style={{ width: `${fila.planeadas > 0 ? Math.min(100, fila.completas / fila.planeadas * 100) : 0}%` }} /></div></div>
    })}</div>}
    {!completa && g && <div className="flex items-start gap-2.5 border-t border-border bg-muted px-5 py-4 sm:px-6"><Info size={17} className="mt-0.5 shrink-0 text-brand" aria-hidden="true" /><p className="text-xs leading-relaxed text-ink-muted"><strong className="font-semibold text-ink">Esto mide avance de generación, no calidad de respuesta.</strong> {g.pendientes > 0 ? `Faltan ${g.pendientes} respuestas por generar. ` : ''}{datos.estado === 'interrumpida' ? 'La calificación con juez y Ragas aún no está completa.' : 'La calificación final aún no está disponible.'}</p></div>}
    {registro && <p className="border-t border-border px-5 py-3 text-[10px] text-ink-muted sm:px-6">Registro guardado: <time dateTime={datos.actualizado_utc}>{registro}</time> · hora de Guatemala. No es un monitor en vivo.</p>}
  </section>
}

function Kpi({ titulo, valor, nota, ok }) {
  return (
    <div className="flex min-w-0 flex-col rounded-[20px] border border-border bg-surface px-4 py-4 shadow-[0_4px_18px_#11224005] sm:px-5 sm:py-5">
      <div className="flex min-h-9 items-start gap-1.5 text-[11px] leading-relaxed text-ink-muted">
        {ok === true && <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-[#16794d]" />}
        {ok === false && <XCircle size={14} className="mt-0.5 shrink-0 text-[#b42318]" />}
        {titulo}
      </div>
      <div className="my-2 font-mono text-[22px] font-semibold tracking-[-0.04em] text-ink sm:text-[28px]">{valor ?? '—'}</div>
      <div className="mt-auto text-[10px] leading-relaxed text-ink-muted">{nota}</div>
    </div>
  )
}

function Barras({ titulo, meta, valores }) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <span className="text-[12px] font-extrabold text-ink">{titulo}</span>
        {meta && <span className="whitespace-nowrap font-mono text-[10px] text-ink-muted">meta {meta[1] === 'min' ? '≥' : '≤'} {meta[0]}</span>}
      </div>
      <div className="space-y-2">
        {valores.map(([nombre, v]) => {
          const ok = meta && v != null ? (meta[1] === 'min' ? v >= meta[0] : v <= meta[0]) : null
          return (
            <div key={nombre}>
              <div className="mb-1 flex justify-between gap-2 text-[11px] text-ink-muted"><span>{nombre}</span><span className="font-mono font-medium text-ink">{fmt(v)}</span></div>
              <div className="relative h-2 overflow-hidden rounded-full bg-[#f0f1f3]" aria-hidden="true">
                <div className={`h-full rounded-full ${ok === false ? 'bg-[#b42318]' : 'bg-brand'}`} style={{ width: `${Math.min(100, (v ?? 0) * 100)}%` }} />
                {meta && <div className="absolute top-0 h-full w-px bg-ink/45" style={{ left: `${meta[0] * 100}%` }} />}
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
    <section className="rounded-[20px] border border-border bg-surface p-5 shadow-[0_4px_18px_#11224005] sm:p-6">
      <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-brand-strong">
        <Bug size={15} />Diagnóstico histórico de una falla real · caso H01
      </div>
      <h3 className="mt-2 text-[17px] font-extrabold leading-relaxed text-ink">El agente pedía filtrar, pero el esquema no lo dejaba</h3>
      <div className="mt-5 grid gap-6 text-[12.5px] leading-[1.8] text-ink-muted md:grid-cols-2 md:gap-7">
        <div className="space-y-3">
          <p><span className="font-semibold text-ink">Síntoma.</span> «¿Tiempo promedio de los tickets de RED de prioridad ALTA?»: el
            agente llamó 5 veces a <span className="font-mono">query_tickets</span>, siempre sin filtros (136 tickets), se quedó sin
            presupuesto y se abstuvo.</p>
          <p><span className="font-semibold text-ink">Causa.</span> En modo estricto el modelo escribe las claves en el orden del
            esquema. El discriminador <span className="font-mono">consulta</span> iba al final: cuando lo escribía, ya había pasado los
            filtros opcionales.</p>
          <p><span className="font-semibold text-ink">Comprobación.</span> Misma pregunta, 3 llamadas a la API con cada esquema:
            con <span className="font-mono">consulta</span> al final, 0 de 3 traían los filtros; primero, 3 de 3.</p>
          <p><span className="font-semibold text-ink">Corrección y alcance.</span> El discriminador va primero; la prueba de esquema
            obtuvo filtros en 3 de 3 llamadas. El H01 histórico conservado terminó con respuesta vacía y abstención. La prueba del
            esquema debe contrastarse con la evaluación del flujo completo. El oráculo espera 3.3 horas en 8 tickets.</p>
        </div>
        <div className="min-w-0 space-y-4 font-mono text-[11px]">
          <div>
            <div className="mb-1.5 font-sans text-[11px] font-medium text-[#b42318]">Antes (0 de 3 con filtros)</div>
            <pre className="overflow-x-auto rounded-xl border border-[#fecdca] bg-[#fef3f2] p-4 text-[#b42318]" tabIndex={0}>{`{"desde": "2026-01-01",
 "hasta": "2026-06-30",
 "consulta": "tiempo_resolucion"}`}</pre>
          </div>
          <div>
            <div className="mb-1.5 font-sans text-[11px] font-medium text-[#16794d]">Después (3 de 3 con filtros)</div>
            <pre className="overflow-x-auto rounded-xl border border-[#bbebce] bg-[#ecfdf3] p-4 text-[#16794d]" tabIndex={0}>{`{"consulta": "tiempo_resolucion",
 "desde": "2026-01-01",
 "hasta": "2026-06-30",
 "categoria": "RED",
 "prioridad": "ALTA"}`}</pre>
          </div>
          <div className="flex items-center gap-1.5 font-sans text-[11px] text-ink-muted">
            <ShieldCheck size={14} className="shrink-0 text-[#16794d]" />La encontró la evaluación, no un usuario.
          </div>
        </div>
      </div>
    </section>
  )
}
