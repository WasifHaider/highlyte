-- Highlyte Supabase schema
-- Run this in the Supabase SQL editor (or via `supabase db push` with this
-- file as a migration). Metadata only — the actual clip video files live
-- in local disk or a Cloudflare R2 bucket (see backend/storage.py), not
-- in Supabase; these tables just track what was generated and where to
-- find it, so a user's clip history survives a backend restart.

create table if not exists jobs (
  id text primary key,
  url text not null,
  status text not null default 'queued',
  error text,
  video_title text,
  video_channel text,
  video_duration numeric,
  transcript_source text,
  whisper_model text default 'small',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists clips (
  id text primary key,
  job_id text not null references jobs(id) on delete cascade,
  idx integer not null,
  start_s numeric not null,
  end_s numeric not null,
  text text,
  tag text,
  score numeric,
  -- Stable app-served path, e.g. /api/clips/{job_id}/clip_0.mp4 — proxies
  -- through to wherever the bytes actually live (see get_clip in main.py).
  -- Always safe to use as-is; doesn't need storage_provider/storage_key.
  download_path text,
  -- Where the clip's bytes actually live: 'r2' or 'local'. Informational
  -- (shown in the Library tab) — get_clip resolves this itself at
  -- request time rather than trusting this column, since a clip can be
  -- moved/re-uploaded after the row is written.
  storage_provider text not null default 'local',
  -- Bucket key when storage_provider = 'r2' (job_id/filename). Lets the
  -- backend regenerate a presigned URL for this exact object without
  -- guessing the filename from download_path.
  storage_key text,
  created_at timestamptz not null default now()
);

-- Migration for tables created before storage_provider/storage_key
-- existed (`create table if not exists` above won't add columns to an
-- already-existing table).
alter table clips add column if not exists storage_provider text not null default 'local';
alter table clips add column if not exists storage_key text;

create index if not exists clips_job_id_idx on clips(job_id);
create index if not exists clips_created_at_idx on clips(created_at desc);
create index if not exists jobs_status_idx on jobs(status);
create index if not exists jobs_created_at_idx on jobs(created_at desc);

-- Keep updated_at current on job row changes.
create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists jobs_set_updated_at on jobs;
create trigger jobs_set_updated_at
  before update on jobs
  for each row execute function set_updated_at();
