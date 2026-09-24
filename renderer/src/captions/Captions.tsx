import { useMemo } from 'react'
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { OUT_H } from '../constants'
import { fontFamily } from '../fonts'
import type { ClipStyle, Word } from '../schema'
import { pageAt, paginate, type Page } from './paginate'

const PRESETS = {
  karaoke: { maxWords: 4, maxChars: 28 },
  pop: { maxWords: 2, maxChars: 18 },
  clean: { maxWords: 14, maxChars: 84 },
} as const

type Props = {
  words: Word[]
  preset: ClipStyle['captionPreset']
  accent: string
  position: ClipStyle['captionPosition']
}

const OUTLINE = { WebkitTextStroke: '12px black', paintOrder: 'stroke fill' } as const

export const Captions: React.FC<Props> = ({ words, preset, accent, position }) => {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const t = frame / fps
  const { maxWords, maxChars } = PRESETS[preset]
  const pages = useMemo(() => paginate(words, maxWords, maxChars), [words, maxWords, maxChars])
  const page = pageAt(pages, t)
  if (!page) return null

  const top = position === 'middle' ? OUT_H / 2 : OUT_H * 0.7
  return (
    <AbsoluteFill>
      <div style={{
        position: 'absolute', top, left: 60, right: 60, transform: 'translateY(-50%)',
        display: 'flex', justifyContent: 'center', textAlign: 'center', fontFamily,
      }}>
        {preset === 'karaoke' && <Karaoke page={page} t={t} accent={accent} />}
        {preset === 'pop' && <Pop page={page} frame={frame} fps={fps} accent={accent} />}
        {preset === 'clean' && <Clean page={page} t={t} />}
      </div>
    </AbsoluteFill>
  )
}

const Karaoke: React.FC<{ page: Page; t: number; accent: string }> = ({ page, t, accent }) => (
  <div style={{ fontSize: 84, fontWeight: 900, lineHeight: 1.1, textTransform: 'uppercase', color: 'white', ...OUTLINE }}>
    {page.words.map((w, i) => (
      <span key={i} style={{ color: t >= w.start && t < w.end ? accent : 'white' }}>
        {w.text}{i < page.words.length - 1 ? ' ' : ''}
      </span>
    ))}
  </div>
)

const Pop: React.FC<{ page: Page; frame: number; fps: number; accent: string }> = ({ page, frame, fps, accent }) => {
  const s = spring({ frame: frame - Math.round(page.start * fps), fps, config: { damping: 12, stiffness: 200 } })
  return (
    <div style={{
      fontSize: 120, fontWeight: 900, lineHeight: 1.05, textTransform: 'uppercase',
      transform: `scale(${0.8 + 0.2 * s})`, ...OUTLINE, WebkitTextStroke: '14px black',
    }}>
      {page.words.map((w, i) => (
        <span key={i} style={{ color: w.emphasis ? accent : 'white' }}>
          {w.text}{i < page.words.length - 1 ? ' ' : ''}
        </span>
      ))}
    </div>
  )
}

const Clean: React.FC<{ page: Page; t: number }> = ({ page, t }) => {
  const opacity = interpolate(t, [page.start, page.start + 0.15, page.end + 0.15, page.end + 0.3], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  })
  return (
    <div style={{
      maxWidth: 900, fontSize: 56, fontWeight: 700, lineHeight: 1.25, color: 'white', opacity,
      textShadow: '0 4px 16px rgba(0,0,0,0.85)',
    }}>
      {page.words.map(w => w.text).join(' ')}
    </div>
  )
}
