import type { Word } from '../schema'

// Captions show a "page" of a few words at a time. A page ends at the
// preset's word or character limit, at the end of a sentence, or at a
// pause, so pages follow the rhythm of speech.
export const PAUSE_BREAK_S = 0.4
const ENDS_SENTENCE = /[.!?…]["')\]]?$/

export type Page = { start: number; end: number; words: Word[] }

export function paginate(words: Word[], maxWords: number, maxChars = Infinity): Page[] {
  const pages: Page[] = []
  let cur: Word[] = []
  const flush = () => {
    if (cur.length) {
      pages.push({ start: cur[0].start, end: cur[cur.length - 1].end, words: cur })
      cur = []
    }
  }
  words.forEach((word, i) => {
    const chars = cur.reduce((n, x) => n + x.text.length + 1, 0) + word.text.length
    if (cur.length && chars > maxChars) flush()
    cur.push(word)
    const next = words[i + 1]
    const pause = next ? next.start - word.end > PAUSE_BREAK_S : false
    if (cur.length >= maxWords || ENDS_SENTENCE.test(word.text) || pause) flush()
  })
  flush()
  return pages
}

export function pageAt(pages: Page[], t: number, linger = 0.3): Page | null {
  for (let i = pages.length - 1; i >= 0; i--) {
    const p = pages[i]
    if (t >= p.start) {
      const next = pages[i + 1]
      const until = next ? Math.min(next.start, p.end + linger) : p.end + linger
      return t < until ? p : null
    }
  }
  return null
}
