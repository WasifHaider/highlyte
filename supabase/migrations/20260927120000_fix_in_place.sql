-- Piece 3a, fix in place.
-- {start, end} of the clip before its first nudge, for Reset.
alter table clips add column if not exists bounds_original jsonb;
-- The ranker's one-line reason, shown on the clip card.
alter table clips add column if not exists reason text;
-- 'swap' | 'regenerate' while one runs in the background, else null.
alter table clips add column if not exists pending_action text;
-- The last swap/regenerate failure, shown on the clip card.
alter table clips add column if not exists action_error text;
-- Bumped when a clip is replaced, so browsers reload its file.
alter table clips add column if not exists revision integer not null default 0;
-- Runner-up moments from clip selection, for Swap scene.
alter table jobs add column if not exists alternates jsonb not null default '[]'::jsonb;
