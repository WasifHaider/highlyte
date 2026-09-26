import type { Word } from '../schema'
import { paginate } from './paginate'

// Caption lines for editing use the clean preset's limits, so a line is the
// same whichever caption style the clip uses.
export const LINE_MAX_WORDS = 14
export const LINE_MAX_CHARS = 84

export type Line = { index: number; from: number; start: number; end: number; words: Word[] }

export function captionLines(words: Word[]): Line[] {
  let from = 0
  return paginate(words, LINE_MAX_WORDS, LINE_MAX_CHARS).map((page, index) => {
    const line = { index, from, start: page.start, end: page.end, words: page.words }
    from += page.words.length
    return line
  })
}

export const lineText = (line: Line) => line.words.map(x => x.text).join(' ')

const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}']+/gu, '')
const round3 = (n: number) => Math.round(n * 1000) / 1000

// Replaces one line's words with the edited text. Same word count keeps
// every timing; otherwise the line's own time span is shared out by word
// length, so the rest of the clip never moves.
export function editLine(words: Word[], line: Line, text: string): Word[] {
  const tokens = text.split(/\s+/).filter(Boolean)
  const before = words.slice(0, line.from)
  const after = words.slice(line.from + line.words.length)
  let replaced: Word[]
  if (tokens.length === line.words.length) {
    replaced = line.words.map((x, i) => ({ ...x, text: tokens[i] }))
  } else if (tokens.length === 0) {
    replaced = []
  } else {
    const emphasised = new Set(line.words.filter(x => x.emphasis).map(x => norm(x.text)))
    const weights = tokens.map(t => t.length + 1)
    const total = weights.reduce((a, b) => a + b, 0)
    const span = line.end - line.start
    let acc = 0
    replaced = tokens.map((t, i) => {
      const start = line.start + (span * acc) / total
      acc += weights[i]
      const end = i === tokens.length - 1 ? line.end : line.start + (span * acc) / total
      return { text: t, start: round3(start), end: round3(end), emphasis: emphasised.has(norm(t)) }
    })
  }
  return [...before, ...replaced, ...after]
}
