// Nombres, íconos y resúmenes de los nodos del grafo (src/tickets_rag/grafo.py).
import {
  Bot, CircleSlash, GitBranch, ListChecks, MessageSquareText, ShieldCheck, ShieldX, TriangleAlert, UserCheck, Wrench,
} from 'lucide-react'

export const NODOS = {
  guardrail_entrada: { nombre: 'Guardrail de entrada', detalle: 'Secretos, datos personales e inyección', icono: ShieldCheck },
  rechazar: { nombre: 'Rechazo', detalle: 'El ticket trae un secreto', icono: ShieldX },
  clasificar: { nombre: 'Router', detalle: 'Codex · clasificación estructurada', icono: GitBranch },
  agente: { nombre: 'Agente', detalle: 'Codex · sesión de ChatGPT', icono: Bot },
  herramientas: { nombre: 'Herramientas', detalle: 'Solo las de la ruta', icono: Wrench },
  validar_salida: { nombre: 'Guardrail de salida', detalle: 'Citas, rol y datos personales', icono: ListChecks },
  aprobacion_humana: { nombre: 'Aprobación N2', detalle: 'Pausa con interrupt', icono: UserCheck },
  responder: { nombre: 'Respuesta', detalle: 'Contrato validado', icono: MessageSquareText },
  abstener: { nombre: 'Abstención', detalle: 'Sin evidencia: escala', icono: CircleSlash },
  degradar: { nombre: 'Modo degradado', detalle: 'El modelo no está disponible', icono: TriangleAlert },
}

export const FALLAS = [
  { valor: null, nombre: 'Normal' },
  { valor: 'modelo', nombre: 'Modelo no disponible' },
  { valor: 'vectores', nombre: 'Base vectorial caída' },
  { valor: 'documento_envenenado', nombre: 'Documento envenenado' },
]

const PII = { PERSON: 'nombre de persona', EMAIL: 'correo', PHONE: 'teléfono', DPI: 'DPI', CARD: 'tarjeta' }

export function describirGuardrail(g) {
  if (!g) return ''
  const pii = Object.entries(g.pii || {}).map(([tipo, n]) => `${n} ${PII[tipo] || tipo}`).join(', ')
  if (g.decision === 'BLOCK') return `Bloqueado: ${(g.motivos || []).join(', ').replaceAll('secreto:', 'secreto ')}`
  if (g.decision === 'WARN') return 'Posible inyección de instrucciones: pasa marcado para revisión'
  if (g.decision === 'REDACT') return `Datos personales enmascarados: ${pii}`
  return 'Sin secretos ni datos personales'
}

export function fuenteCorta(f) {
  const s = f.source || ''
  if (f.chunk_id?.startsWith('sql-')) return s.replace('Historial de tickets', 'Historial')
  if (s.startsWith('manual_mesa_ayuda_v')) return `Manual ${s.slice(19, 25)}, p. ${f.page}`
  if (s.startsWith('f2_microsoft')) return `Microsoft Learn, p. ${f.page}`
  if (s.endsWith('.jsonl')) return `Ticket resuelto #${f.page}`
  return `${s}, p. ${f.page}`
}

export function tipoFuente(f) {
  if (f.chunk_id?.startsWith('sql-')) return 'consulta'
  if (f.chunk_id?.startsWith('F1')) return 'manual'
  if (f.chunk_id?.startsWith('F2')) return 'articulo'
  return 'ticket'
}

// Una línea que resume el paso, para la línea de tiempo
export function resumirPaso(paso) {
  const t = paso.traza || []
  const de = (etapa) => t.find((x) => x.etapa === etapa)
  switch (paso.nodo) {
    case 'guardrail_entrada':
      return describirGuardrail(de('guardrail_entrada'))
    case 'clasificar': {
      const r = de('router')
      if (!r || r.error) return 'El clasificador falló: ruta de procedimiento por defecto'
      const conf = Math.min(...Object.values(r.triage.confianza || { x: 1 }))
      return `${r.triage.categoria} · ${r.triage.prioridad} · ruta ${r.ruta} · acuerdo ${(conf * 100).toFixed(0)} %`
    }
    case 'agente': {
      if (paso.error_modelo) return `El modelo no está disponible (${paso.error_modelo})`
      if (paso.llamadas?.length) return `Pide ${paso.llamadas.map((l) => l.nombre).join(', ')}`
      return 'Redacta la respuesta final'
    }
    case 'herramientas':
      return t.filter((x) => x.etapa === 'herramienta')
        .map((x) => `${x.nombre} ${x.ok ? '✓' : '✗'}${x.ok && x.candidatos?.length ? ` (${x.candidatos.length})` : ''}`).join(' · ')
    case 'validar_salida': {
      const v = de('guardrail_salida')
      if (!v) return ''
      if (v.errores?.length) return `${v.errores.length} problema(s): ${v.siguiente === 'agente' ? 'reintenta' : v.siguiente}`
      return v.abstiene ? 'Sin evidencia suficiente: se abstiene' : `Citas válidas → ${v.siguiente.replace('_', ' ')}`
    }
    case 'aprobacion_humana':
      return (paso.notas || []).join(' · ') || 'Decisión registrada'
    case 'abstener': {
      const a = de('abstencion')
      return a?.escalado ? 'Se abstiene y escala a N2' : 'Se abstiene'
    }
    case 'degradar':
      return 'Responde con la búsqueda por palabras, para revisión humana'
    case 'rechazar':
      return 'No se procesa: nunca llega al modelo'
    case 'responder':
      return 'Respuesta lista'
    default:
      return ''
  }
}
