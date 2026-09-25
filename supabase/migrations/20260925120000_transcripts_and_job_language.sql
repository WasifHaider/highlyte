-- Piece 1: the spoken language a job was submitted with and the one
-- actually used, plus the stored transcript (v1 segment data contract)
-- so clips can later be nudged and regenerated without transcribing again.
alter table jobs add column if not exists language_requested text;
alter table jobs add column if not exists language_used text;
alter table jobs add column if not exists language_note text;

create table if not exists transcripts (
  job_id text primary key references jobs(id) on delete cascade,
  language text not null,          -- 'hinglish' | 'english'
  source text not null,            -- 'groq' | 'whisper' | 'mixed'
  segments jsonb not null,
  created_at timestamptz not null default now()
);
alter table transcripts enable row level security;
