-- Caption editing: the clip's words as generated, kept from the first edit
-- so "Reset to original" can restore them. Null until the captions are edited.
alter table clips add column if not exists words_original jsonb;
