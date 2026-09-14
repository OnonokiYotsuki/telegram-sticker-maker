export function formatOutputName(index: number, emoji: string, ext: string, zeroPad = true): string {
  const idx = zeroPad ? String(index).padStart(3, '0') : String(index)
  const clean = (emoji || '').trim()
  return clean ? `${idx}_${clean}${ext}` : `${idx}${ext}`
}

export function defaultClipEnd(duration: number): number {
  if (!Number.isFinite(duration) || duration <= 0) return 3
  return duration
}
