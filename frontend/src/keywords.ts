export const MAX_KEYWORDS = 20
export const MAX_KEYWORDS_CHARS = 64

const KEYWORD_SPLIT_RE = /[,，、;；\s]+/

export function parseKeywords(value: string | string[] | null | undefined): string[] {
  if (value == null) return []
  const parts = Array.isArray(value) ? value.map(String) : String(value).split(KEYWORD_SPLIT_RE)
  const out: string[] = []
  const seen = new Set<string>()
  for (const raw of parts) {
    const word = raw.trim()
    if (!word || seen.has(word)) continue
    seen.add(word)
    out.push(word)
  }
  return out
}

export function clampKeywordList(words: string[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  let total = 0
  for (const word of words) {
    if (!word || out.length >= MAX_KEYWORDS) break
    const room = MAX_KEYWORDS_CHARS - total
    if (room <= 0) break
    const clipped = word.length > room ? word.slice(0, room) : word
    if (!clipped || seen.has(clipped)) continue
    seen.add(clipped)
    out.push(clipped)
    total += clipped.length
  }
  return out
}

export function formatKeywords(words: string[]): string {
  return words.join(', ')
}

export function constrainKeywordsInput(raw: string): string {
  const parsed = parseKeywords(raw)
  const clamped = clampKeywordList(parsed)
  const parsedChars = parsed.reduce((n, w) => n + w.length, 0)
  const clampedChars = clamped.reduce((n, w) => n + w.length, 0)
  if (parsed.length <= MAX_KEYWORDS && parsedChars <= MAX_KEYWORDS_CHARS && parsedChars === clampedChars) {
    return raw
  }
  return formatKeywords(clamped)
}

export function keywordMeter(raw: string): { count: number; chars: number } {
  const words = clampKeywordList(parseKeywords(raw))
  return {
    count: words.length,
    chars: words.reduce((n, w) => n + w.length, 0),
  }
}
