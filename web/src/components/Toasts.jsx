import { useStore } from '../store.js'

const TONE = {
  ok: 'border-[#2EAF6E] bg-sand-50 text-ink-900',
  info: 'border-air-500 bg-sand-50 text-ink-900',
  error: 'border-[#E5484D] bg-[#fdecec] text-[#8F1F23]',
}

export default function Toasts() {
  const toasts = useStore((s) => s.toasts)
  const dismiss = useStore((s) => s.dismissToast)
  return (
    <div className="pointer-events-none fixed inset-x-0 top-16 z-[1500] flex flex-col items-center gap-2 px-4" aria-live="polite" role="status">
      {toasts.map((t) => (
        <div key={t.id} className={`pointer-events-auto flex max-w-xl items-start gap-3 rounded-lg border-2 px-3 py-2 text-[14px] font-medium shadow-float ${TONE[t.tone] || TONE.info}`}>
          <span className="leading-snug">{t.text}</span>
          <button type="button" onClick={() => dismiss(t.id)} className="shrink-0 text-[13px] font-bold opacity-70 hover:opacity-100" aria-label="Dismiss">
            ✕
          </button>
        </div>
      ))}
    </div>
  )
}
