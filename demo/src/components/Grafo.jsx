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
    ['aprobacion_humana', 'responder', `M${ap.cx} ${ap.y + H} V${re.y - 4}`],
  ]
}

const FINALES = { responder: 'emerald', abstener: 'amber', degradar: 'amber', rechazar: 'rose' }
const COLOR = {
  emerald: { relleno: 'rgb(16 185 129 / .18)', borde: 'rgb(52 211 153)', texto: 'rgb(167 243 208)' },
  amber: { relleno: 'rgb(245 158 11 / .18)', borde: 'rgb(251 191 36)', texto: 'rgb(253 230 138)' },
  rose: { relleno: 'rgb(244 63 94 / .18)', borde: 'rgb(251 113 133)', texto: 'rgb(254 205 211)' },
  indigo: { relleno: 'rgb(99 102 241 / .16)', borde: 'rgb(129 140 248)', texto: 'rgb(199 210 254)' },
  violeta: { relleno: 'rgb(139 92 246 / .3)', borde: 'rgb(196 181 253)', texto: 'rgb(237 233 254)' },
  apagado: { relleno: 'rgb(30 41 59 / .55)', borde: 'rgb(51 65 85)', texto: 'rgb(100 116 139)' },
}

export default function Grafo({ pasos, corriendo, enPausa }) {
  const secuencia = pasos.map((p) => p.nodo)
  const visitas = secuencia.reduce((m, n) => ({ ...m, [n]: (m[n] || 0) + 1 }), {})
  const recorridas = new Set(secuencia.slice(1).map((n, i) => `${secuencia[i]}>${n}`))
  if (enPausa && secuencia.at(-1) === 'validar_salida') recorridas.add('validar_salida>aprobacion_humana')
  const activo = enPausa ? 'aprobacion_humana' : corriendo ? siguiente(pasos) : null

  return (
    <svg viewBox="0 0 480 462" className="w-full h-auto select-none">
      <defs>
        {['gris', 'azul'].map((id) => (
          <marker key={id} id={`flecha-${id}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0 0 L10 5 L0 10 z" fill={id === 'azul' ? 'rgb(129 140 248)' : 'rgb(71 85 105)'} />
          </marker>
        ))}
      </defs>
      {aristas().map(([o, d, ruta]) => {
        const hecha = recorridas.has(`${o}>${d}`)
        return (
          <path key={`${o}-${d}`} d={ruta} fill="none" strokeWidth={hecha ? 2 : 1.3}
            stroke={hecha ? 'rgb(129 140 248)' : 'rgb(51 65 85)'} strokeDasharray={hecha ? '' : '4 4'}
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
            <rect x={x} y={y} width={w} height={H} rx="10" fill={c.relleno} stroke={c.borde} strokeWidth={fueVisitado || n === activo ? 1.6 : 1} />
            <foreignObject x={x} y={y} width={w} height={H}>
              <div className="h-full flex items-center gap-2 px-2.5" style={{ color: c.texto }}>
                <Icono size={15} strokeWidth={2} className="shrink-0" />
                <div className="leading-tight min-w-0">
                  <div className="text-[11.5px] font-semibold truncate">{NODOS[n].nombre}</div>
                  <div className="text-[9.5px] opacity-70 truncate">{n === activo && enPausa ? 'Esperando a N2…' : NODOS[n].detalle}</div>
                </div>
              </div>
            </foreignObject>
            {visitas[n] > 1 && (
              <g>
                <circle cx={x + w - 4} cy={y + 4} r="9" fill="rgb(99 102 241)" />
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
      return 'responder'
    default:
      return null
  }
}
