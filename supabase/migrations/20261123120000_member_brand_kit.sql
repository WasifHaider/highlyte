-- Each member's brand kit: the accent colour, caption font and progress bar
-- their new clips start with (Settings > My brand kit). Null means the
-- default style.
alter table team_members add column if not exists brand_kit jsonb;
