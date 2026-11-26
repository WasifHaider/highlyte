-- A member can add a backup Groq key from a second Groq account. Groq's
-- free limits apply per account (organization), so clip selection and
-- transcription move to the backup key when the main one runs out.
alter table team_members add column if not exists groq_backup_key text;
