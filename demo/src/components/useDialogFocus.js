// Comportamiento de presentación: foco y teclado dentro del diálogo visible.
import { useEffect, useRef } from 'react'

export default function useDialogFocus(ref, alEscapar) {
  const escapar = useRef(alEscapar)
  escapar.current = alEscapar
  useEffect(() => {
    const dialogo = ref.current
    const anterior = document.activeElement
    const activo = () => [...document.querySelectorAll('[role="dialog"]')]
      .filter((d) => d.getClientRects().length)
      .sort((a, b) => Number(a.closest('[data-dialog-layer]')?.dataset.dialogLayer || 0)
        - Number(b.closest('[data-dialog-layer]')?.dataset.dialogLayer || 0)).at(-1) === dialogo
    const opciones = () => [...dialogo.querySelectorAll('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]')]
      .filter((e) => e.getClientRects().length)
    if (activo() && !dialogo.contains(document.activeElement)) opciones()[0]?.focus()
    const teclado = (e) => {
      if (!activo()) return
      if (e.key === 'Escape' && escapar.current) { e.preventDefault(); escapar.current(); return }
      if (e.key !== 'Tab') return
      const lista = opciones(), primero = lista[0], ultimo = lista.at(-1)
      if (!primero) { e.preventDefault(); return }
      if (e.shiftKey && (document.activeElement === primero || !dialogo.contains(document.activeElement))) {
        e.preventDefault(); ultimo.focus()
      } else if (!e.shiftKey && (document.activeElement === ultimo || !dialogo.contains(document.activeElement))) {
        e.preventDefault(); primero.focus()
      }
    }
    document.addEventListener('keydown', teclado)
    return () => {
      document.removeEventListener('keydown', teclado)
      if (dialogo.contains(document.activeElement) && anterior?.isConnected) anterior.focus()
    }
  }, [ref])
}
