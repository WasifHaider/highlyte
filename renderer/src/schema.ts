// Mirrors backend/spec.py. The Python-generated fixture in __fixtures__ is
// parsed by schema.test.ts, so a change on one side that the other side
// doesn't know about fails a test instead of a render.
import { z } from 'zod'

export const layoutSchema = z.enum(['follow', 'speaker', 'split', 'fit'])

export const wordSchema = z.object({
  text: z.string(),
  start: z.number(),
  end: z.number(),
  emphasis: z.boolean().optional(),
})

export const trackPointSchema = z.object({
  t: z.number(),
  cx: z.number(),
  cy: z.number(),
  w: z.number(),
  h: z.number(),
})

export const clipSpecSchema = z.object({
  version: z.literal(1),
  clipId: z.string(),
  source: z.object({
    url: z.string(),
    width: z.number().int().positive(),
    height: z.number().int().positive(),
    fps: z.number().positive(),
  }),
  start: z.number().min(0),
  end: z.number(),
  words: z.array(wordSchema),
  wordsApprox: z.boolean(),
  hookTitle: z.string().nullable(),
  viralityScore: z.number().min(0).max(10),
  reframe: z.object({
    auto: layoutSchema,
    faces: z.array(z.object({ id: z.number().int(), track: z.array(trackPointSchema) })),
    speakerTimeline: z.array(z.object({ t: z.number(), faceId: z.number().int() })),
  }),
})

export const clipStyleSchema = z.object({
  layout: layoutSchema,
  captionPreset: z.enum(['karaoke', 'pop', 'clean']),
  showHook: z.boolean(),
  hookTitle: z.string().max(80).nullable(),
  accent: z.string().regex(/^#[0-9A-Fa-f]{6}$/),
  captionPosition: z.enum(['lower', 'middle']),
})

export const clipPropsSchema = z.object({ spec: clipSpecSchema, style: clipStyleSchema })

export type Layout = z.infer<typeof layoutSchema>
export type Word = z.infer<typeof wordSchema>
export type TrackPoint = z.infer<typeof trackPointSchema>
export type ClipSpec = z.infer<typeof clipSpecSchema>
export type ClipStyle = z.infer<typeof clipStyleSchema>
export type ClipProps = z.infer<typeof clipPropsSchema>
