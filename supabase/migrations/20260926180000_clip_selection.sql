-- Piece 2, clip selection.
-- Loudness per 0.5 s (dB) so a retried selection needs no audio.
alter table transcripts add column if not exists loudness jsonb;
-- Partial-failure note shown above the clip grid, e.g. skipped time ranges.
alter table jobs add column if not exists selection_note text;
-- QA flags per clip: low_confidence, weak_pick, no_face_start.
alter table clips add column if not exists qa_flags jsonb not null default '[]'::jsonb;
