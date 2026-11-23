// Mirrors backend/spec.py. The Python-generated fixture in __fixtures__ is
// parsed by schema.test.ts, so a change on one side that the other side
// doesn't know about fails a test instead of a render.
// Spec v2 stores times from file start; v1 from clip start (see lib/timeline.ts).
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

export const shotSchema = z.object({
  start: z.number(),
  end: z.number(),
  kind: z.enum(['two', 'one', 'none']),
  faceIds: z.array(z.number().int()),
})

export const clipSpecSchema = z.object({
  version: z.union([z.literal(1), z.literal(2)]),
  clipId: z.string(),
  source: z.object({
    url: z.string(),
    width: z.number().int().positive(),
    height: z.number().int().positive(),
    fps: z.number().positive(),
    duration: z.number().positive().nullable().optional(),
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
    shots: z.array(shotSchema).default([]),
  }),
})

export const clipStyleSchema = z.object({
  layout: layoutSchema,
  captionPreset: z.enum(['karaoke', 'pop', 'clean']),
  showHook: z.boolean(),
  hookTitle: z.string().max(80).nullable(),
  accent: z.string().regex(/^#[0-9A-Fa-f]{6}$/),
  captionPosition: z.enum(['lower', 'middle']),
  // Added later: styles saved before them parse to these defaults, and raw
  // props without them render the same (fonts.fontFor, ProgressBar).
  font: z.enum(['montserrat', 'poppins', 'anton', 'bebas']).default('montserrat'),
  progressBar: z.enum(['off', 'top', 'bottom']).default('off'),
  aspect: z.enum(['9:16', '4:5', '1:1']).default('9:16'),
  zoom: z.enum(['off', 'emphasis', 'dynamic']).default('off'),
})

// posterUrl is preview-only (the fit background in the browser Player, see
// layouts/LayoutView.tsx); renders never receive it.
export const clipPropsSchema = z.object({ spec: clipSpecSchema, style: clipStyleSchema, posterUrl: z.string().optional() })

export type Layout = z.infer<typeof layoutSchema>
export type Word = z.infer<typeof wordSchema>
export type TrackPoint = z.infer<typeof trackPointSchema>
export type Shot = z.infer<typeof shotSchema>
export type ClipSpec = z.infer<typeof clipSpecSchema>
export type ClipStyle = z.infer<typeof clipStyleSchema>
export type ClipProps = z.infer<typeof clipPropsSchema>
