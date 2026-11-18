// Panel lateral con el fragmento citado: texto, sección, versión y enlace al PDF en la página exacta.
import { useEffect, useRef, useState } from 'react'
import { ExternalLink, Lock, X } from 'lucide-react'
import { obtener } from '../api'
import { fuenteCorta } from '../nodos'
import { Insignia } from './Respuesta'
import useDialogFocus from './useDialogFocus'

export default function Fragmento({ chunkId, rol, alCerrar }) {
  const [datos, setDatos] = useState(null)
  const [error, setError] = useState(null)
  const dialogo = useRef(null)
  useDialogFocus(dialogo, alCerrar)

  useEffect(() => {
    setDatos(null); setError(null)
    obtener(`/api/fragmentos/${chunkId}?rol=${rol}`).then(setDatos)
      .catch((e) => setError(e.message === '403' ? 'Tu rol no puede ver este fragmento.' : 'No se pudo cargar el fragmento.'))
  }, [chunkId, rol])

  return (
    <div data-dialog-layer="40" className="fixed inset-0 z-40 flex justify-end bg-ink/35 backdrop-blur-[2px]" onClick={alCerrar}>
      <aside ref={dialogo} className="flex h-full w-full max-w-2xl flex-col border-l border-border bg-surface shadow-2xl animar-entrada"
        role="dialog" aria-modal="true" aria-labelledby="fragmento-titulo"
        onClick={(e) => e.stopPropagation()}>
        <header className="flex items-start gap-4 border-b border-border px-5 py-5 sm:px-7 sm:py-6">
          <div className="min-w-0">
            <div className="mb-2 inline-flex rounded-md bg-brand-soft px-2 py-1 font-mono text-[10px] text-brand-strong [overflow-wrap:anywhere]">{chunkId}</div>
            <h3 id="fragmento-titulo" className="text-lg font-extrabold leading-snug text-ink sm:text-xl">
              {datos ? `${datos.seccion} ${datos.titulo}` : 'Fragmento citado'}
            </h3>
            {datos && <p className="mt-1.5 text-[12px] leading-relaxed text-ink-muted [overflow-wrap:anywhere]">{fuenteCorta(datos)}</p>}
          </div>
          <button type="button" onClick={alCerrar} aria-label="Cerrar fragmento"
            className="ml-auto grid size-10 shrink-0 place-items-center rounded-xl border border-border bg-surface text-ink-muted transition hover:border-brand/30 hover:bg-brand-soft hover:text-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"><X size={18} /></button>
        </header>
        <div className="flex-1 space-y-5 overflow-y-auto bg-canvas px-5 py-5 sm:px-7 sm:py-6">
          {error && <p role="alert" className="flex items-start gap-2.5 rounded-xl border border-[#fecdca] bg-[#fef3f2] p-4 text-sm leading-relaxed text-[#b42318]"><Lock size={16} className="mt-0.5 shrink-0" />{error}</p>}
          {datos && (
            <>
              <div className="flex flex-wrap gap-2" aria-label="Información del documento">
                <Insignia tono="slate">{datos.tipo === 'manual' ? 'Manual (F1)' : datos.tipo === 'articulo' ? 'Microsoft Learn (F2)' : 'Ticket resuelto (F3)'}</Insignia>
                <Insignia tono="slate">Versión {datos.version}</Insignia>
                <Insignia tono={datos.vigente ? 'emerald' : 'amber'}>{datos.vigente ? 'Vigente' : 'No vigente'}</Insignia>
              </div>
              <div className="rounded-[20px] border border-border bg-surface p-4 shadow-[0_2px_8px_#11224005] sm:p-6">
                <p className="whitespace-pre-line text-[13px] leading-[1.9] text-ink [overflow-wrap:anywhere] sm:text-[13.5px]">{datos.texto}</p>
              </div>
            </>
          )}
        </div>
        {(datos?.url_pdf || datos?.pdf_restringido) && (
          <footer className="border-t border-border bg-surface px-5 py-4 sm:px-7">
            {datos.url_pdf ? <a href={datos.url_pdf} target="_blank" rel="noreferrer"
              className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#D8F64E] px-4 py-3 text-center text-[12.5px] font-semibold text-ink transition hover:bg-[#cbe83e] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 sm:w-auto">
              <ExternalLink size={15} className="shrink-0" />Abrir el PDF en la página {datos.page}
            </a> : <p className="flex items-start gap-2.5 rounded-xl bg-muted p-3 text-[12px] leading-relaxed text-ink-muted">
              <Lock size={15} className="mt-0.5 shrink-0" />
              El PDF completo de este manual está reservado a N2. El fragmento y su cita siguen disponibles.
            </p>}
          </footer>
        )}
      </aside>
    </div>
  )
}
