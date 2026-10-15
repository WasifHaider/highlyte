-- Each member can bring their own Groq key (teammates running the app
-- locally on separate machines, each with their own free-tier quota)
-- instead of relying on a single shared GROQ_KEY env var.
alter table team_members add column if not exists groq_key text;
