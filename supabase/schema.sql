-- Highlyte Supabase schema
-- Run this in the Supabase SQL editor (or via `supabase db push` with this
-- file as a migration). Metadata only — clip audio files stay on local
-- disk/backend storage for now; only job/clip/transcript rows live here.

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
  download_path text,
  created_at timestamptz not null default now()
);

create index if not exists clips_job_id_idx on clips(job_id);
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
