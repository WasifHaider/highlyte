import { describe, expect, it } from 'vitest'
import { pageAt, paginate } from './paginate'

const w = (text: string, start: number, end: number) => ({ text, start, end })

describe('paginate', () => {
  it('breaks at the word limit', () => {
    const words = [w('a', 0, 0.2), w('b', 0.2, 0.4), w('c', 0.4, 0.6), w('d', 0.6, 0.8), w('e', 0.8, 1)]
    expect(paginate(words, 2).map(p => p.words.map(x => x.text).join(' '))).toEqual(['a b', 'c d', 'e'])
  })
  it('breaks at sentence ends and pauses', () => {
    const words = [w('Hi.', 0, 0.3), w('So', 0.3, 0.5), w('then', 0.5, 0.7), w('later', 1.5, 1.8)]
    expect(paginate(words, 10).map(p => p.words.length)).toEqual([1, 2, 1])
  })
  it('breaks before exceeding the character limit', () => {
    const words = [w('abcdef', 0, 0.2), w('ghijkl', 0.2, 0.4), w('m', 0.4, 0.6)]
    expect(paginate(words, 10, 10).map(p => p.words.length)).toEqual([1, 2])
  })
  it('page times come from its words', () => {
    const [p] = paginate([w('a', 1, 1.2), w('b', 1.2, 1.5)], 5)
    expect([p.start, p.end]).toEqual([1, 1.5])
  })
})

describe('pageAt', () => {
  const pages = paginate([w('a', 0, 0.5), w('b.', 0.5, 1), w('c', 3, 3.5)], 5)
  it('shows a page from its start until the next page or a short linger', () => {
    expect(pageAt(pages, 0.2)?.words[0].text).toBe('a')
    expect(pageAt(pages, 1.2)?.words[0].text).toBe('a')
    expect(pageAt(pages, 2)).toBeNull()
    expect(pageAt(pages, 3.1)?.words[0].text).toBe('c')
  })
  it('shows nothing before the first word', () => {
    expect(paginate([w('a', 1, 2)], 5).length).toBe(1)
    expect(pageAt(paginate([w('a', 1, 2)], 5), 0.5)).toBeNull()
  })
})
