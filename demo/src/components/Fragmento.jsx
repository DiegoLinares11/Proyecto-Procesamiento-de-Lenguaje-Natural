// Panel lateral con el fragmento citado: texto, sección, versión y enlace al PDF en la página exacta.
import { useEffect, useState } from 'react'
import { ExternalLink, Lock, X } from 'lucide-react'
import { obtener } from '../api'
import { fuenteCorta } from '../nodos'
import { Insignia } from './Respuesta'

export default function Fragmento({ chunkId, rol, alCerrar }) {
  const [datos, setDatos] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    setDatos(null); setError(null)
    obtener(`/api/fragmentos/${chunkId}?rol=${rol}`).then(setDatos)
      .catch((e) => setError(e.message === '403' ? 'Tu rol no puede ver este fragmento.' : 'No se pudo cargar el fragmento.'))
  }, [chunkId, rol])

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-950/50 backdrop-blur-[2px]" onClick={alCerrar}>
      <aside className="h-full w-full max-w-xl bg-slate-900 border-l border-slate-800 shadow-2xl flex flex-col animar-entrada"
        onClick={(e) => e.stopPropagation()}>
        <header className="flex items-start gap-3 px-5 py-4 border-b border-slate-800">
          <div className="min-w-0">
            <div className="font-mono text-[11px] text-indigo-300">{chunkId}</div>
            <h3 className="text-[15px] font-semibold text-slate-100 leading-snug">
              {datos ? `${datos.seccion} ${datos.titulo}` : 'Fragmento'}
            </h3>
            {datos && <p className="text-[12.5px] text-slate-400">{fuenteCorta(datos)}</p>}
          </div>
          <button type="button" onClick={alCerrar} className="ml-auto text-slate-400 hover:text-slate-100"><X size={18} /></button>
        </header>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          {error && <p className="flex items-center gap-2 text-rose-300 text-sm"><Lock size={15} />{error}</p>}
          {datos && (
            <>
              <div className="flex flex-wrap gap-1.5">
                <Insignia tono="slate">{datos.tipo === 'manual' ? 'Manual (F1)' : datos.tipo === 'articulo' ? 'Microsoft Learn (F2)' : 'Ticket resuelto (F3)'}</Insignia>
                <Insignia tono="slate">Versión {datos.version}</Insignia>
                <Insignia tono={datos.vigente ? 'emerald' : 'amber'}>{datos.vigente ? 'Vigente' : 'No vigente'}</Insignia>
              </div>
              <p className="whitespace-pre-line text-[13.5px] leading-relaxed text-slate-200">{datos.texto}</p>
            </>
          )}
        </div>
        {datos?.url_pdf && (
          <footer className="px-5 py-3 border-t border-slate-800">
            <a href={datos.url_pdf} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-lg bg-indigo-500 hover:bg-indigo-400 px-3.5 py-2 text-sm font-medium text-white">
              <ExternalLink size={15} />Abrir el PDF en la página {datos.page}
            </a>
          </footer>
        )}
      </aside>
    </div>
  )
}
