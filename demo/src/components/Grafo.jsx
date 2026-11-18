// El grafo de LangGraph dibujado a mano: cada nodo se ilumina cuando la API avisa que terminó.
import { NODOS } from '../nodos'

const W = 176, H = 42
const POS = {
  guardrail_entrada: [152, 14], rechazar: [352, 14, 124],
  clasificar: [152, 88],
  degradar: [4, 162, 128], agente: [152, 162], herramientas: [352, 162, 124],
  validar_salida: [152, 246],
  abstener: [4, 330, 128], aprobacion_humana: [152, 330],
  responder: [152, 412],
}

const caja = (n) => { const [x, y, w = W] = POS[n]; return { x, y, w, h: H, cx: x + w / 2, cy: y + H / 2 } }

// Aristas como trazos: [origen, destino, path]
function aristas() {
  const g = caja('guardrail_entrada'), r = caja('rechazar'), c = caja('clasificar'), a = caja('agente')
  const h = caja('herramientas'), d = caja('degradar'), v = caja('validar_salida'), ab = caja('abstener')
  const ap = caja('aprobacion_humana'), re = caja('responder')
  return [
    ['guardrail_entrada', 'rechazar', `M${g.x + g.w} ${g.cy} H${r.x - 4}`],
    ['guardrail_entrada', 'clasificar', `M${g.cx} ${g.y + H} V${c.y - 4}`],
    ['clasificar', 'agente', `M${c.cx} ${c.y + H} V${a.y - 4}`],
    ['agente', 'herramientas', `M${a.x + a.w} ${a.cy - 8} H${h.x - 4}`],
    ['herramientas', 'agente', `M${h.x} ${a.cy + 8} H${a.x + a.w + 4}`],
    ['agente', 'degradar', `M${a.x} ${a.cy} H${d.x + d.w + 4}`],
    ['agente', 'validar_salida', `M${a.cx} ${a.y + H} V${v.y - 4}`],
    ['validar_salida', 'agente', `M${v.x + 18} ${v.y} C${v.x - 18} ${v.y - 16}, ${a.x - 18} ${a.y + H + 16}, ${a.x + 14} ${a.y + H + 3}`],
    ['validar_salida', 'abstener', `M${v.x + 10} ${v.y + H} L${ab.cx + 10} ${ab.y - 4}`],
    ['validar_salida', 'aprobacion_humana', `M${v.cx} ${v.y + H} V${ap.y - 4}`],
    ['validar_salida', 'responder', `M${v.x + v.w} ${v.cy} H${v.x + v.w + 28} V${re.cy} H${re.x + re.w + 4}`],
    ['aprobacion_humana', 'aprobacion_humana', `M${ap.x + ap.w} ${ap.cy} C${ap.x + ap.w + 32} ${ap.cy}, ${ap.x + ap.w + 32} ${ap.y - 18}, ${ap.x + ap.w - 12} ${ap.y - 18} V${ap.y - 4}`],
    ['aprobacion_humana', 'responder', `M${ap.cx} ${ap.y + H} V${re.y - 4}`],
  ]
}

const FINALES = { responder: 'emerald', abstener: 'amber', degradar: 'amber', rechazar: 'rose' }
const COLOR = {
  emerald: { relleno: '#ecfdf3', borde: '#16794d', texto: '#16794d' },
  amber: { relleno: '#fffbeb', borde: '#d6a347', texto: '#92400e' },
  rose: { relleno: '#fef3f2', borde: '#b42318', texto: '#b42318' },
  indigo: { relleno: 'var(--brand-soft)', borde: 'var(--brand)', texto: 'var(--brand-strong)' },
  violeta: { relleno: 'var(--brand)', borde: 'var(--brand)', texto: '#ffffff' },
  apagado: { relleno: 'var(--surface)', borde: 'var(--border)', texto: 'var(--foreground-muted)' },
}

export default function Grafo({ pasos, corriendo, enPausa }) {
  const secuencia = pasos.map((p) => p.nodo)
  const visitas = secuencia.reduce((m, n) => ({ ...m, [n]: (m[n] || 0) + 1 }), {})
  const recorridas = new Set(secuencia.slice(1).map((n, i) => `${secuencia[i]}>${n}`))
  if (enPausa && secuencia.at(-1) === 'validar_salida') recorridas.add('validar_salida>aprobacion_humana')
  if (enPausa && secuencia.at(-1) === 'aprobacion_humana') recorridas.add('aprobacion_humana>aprobacion_humana')
  const activo = enPausa ? 'aprobacion_humana' : corriendo ? siguiente(pasos) : null

  return (
    <svg viewBox="0 0 480 462" className="h-auto w-full select-none" role="img" aria-labelledby="grafo-titulo grafo-descripcion">
      <title id="grafo-titulo">Flujo de PILAS</title>
      <desc id="grafo-descripcion">Los nodos recorridos aparecen en azul suave y el nodo activo en azul intenso. Verde indica respuesta; ámbar, pausa, abstención o degradación; rojo, rechazo.</desc>
      <defs>
        {['gris', 'azul'].map((id) => (
          <marker key={id} id={`flecha-${id}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0 0 L10 5 L0 10 z" fill={id === 'azul' ? 'var(--brand)' : '#98a2b3'} />
          </marker>
        ))}
      </defs>
      {aristas().map(([o, d, ruta]) => {
        const hecha = recorridas.has(`${o}>${d}`)
        return (
          <path key={`${o}-${d}`} d={ruta} fill="none" strokeWidth={hecha ? 2 : 1.3}
            stroke={hecha ? 'var(--brand)' : 'var(--border)'} strokeDasharray={hecha ? '' : '4 4'}
            markerEnd={`url(#flecha-${hecha ? 'azul' : 'gris'})`} className="transition-all duration-300" />
        )
      })}
      {Object.keys(POS).map((n) => {
        const { x, y, w } = caja(n)
        const fueVisitado = visitas[n] > 0
        let tono = 'apagado'
        if (fueVisitado) tono = FINALES[n] || 'indigo'
        if (n === activo) tono = enPausa ? 'amber' : 'violeta'
        const c = COLOR[tono]
        const Icono = NODOS[n].icono
        return (
          <g key={n} className={n === activo ? 'animar-brillo' : ''}>
            <title>{NODOS[n].nombre}: {NODOS[n].detalle}</title>
            <rect x={x} y={y} width={w} height={H} rx="10" fill={c.relleno} stroke={c.borde} strokeWidth={fueVisitado || n === activo ? 1.6 : 1} />
            <foreignObject x={x} y={y} width={w} height={H}>
              <div className="flex h-full items-center gap-2 px-2.5" style={{ color: c.texto }}>
                <Icono size={15} strokeWidth={2} className="shrink-0" />
                <div className="leading-tight min-w-0">
                  <div className="text-[11.5px] font-extrabold truncate">{NODOS[n].nombre}</div>
                  <div className="truncate text-[9.5px]">{n === activo && enPausa ? 'Esperando a N2…' : NODOS[n].detalle}</div>
                </div>
              </div>
            </foreignObject>
            {visitas[n] > 1 && (
              <g>
                <circle cx={x + w - 4} cy={y + 4} r="9" fill="var(--brand)" />
                <text x={x + w - 4} y={y + 7.5} textAnchor="middle" fontSize="10" fontWeight="700" fill="white">×{visitas[n]}</text>
              </g>
            )}
          </g>
        )
      })}
    </svg>
  )
}

// Mientras corre, se resalta el nodo que está trabajando: el que sigue según lo que decidió el último paso
function siguiente(pasos) {
  const ultimo = pasos.at(-1)
  if (!ultimo) return 'guardrail_entrada'
  switch (ultimo.nodo) {
    case 'guardrail_entrada': {
      const g = ultimo.traza?.find((t) => t.etapa === 'guardrail_entrada')
      return g?.decision === 'BLOCK' ? 'rechazar' : 'clasificar'
    }
    case 'clasificar':
    case 'herramientas':
      return 'agente'
    case 'agente':
      if (ultimo.error_modelo) return 'degradar'
      return ultimo.llamadas?.length ? 'herramientas' : 'validar_salida'
    case 'validar_salida':
      return ultimo.traza?.find((t) => t.etapa === 'guardrail_salida')?.siguiente ?? null
    case 'aprobacion_humana':
      return ultimo.pendiente ? 'aprobacion_humana' : 'responder'
    default:
      return null
  }
}
