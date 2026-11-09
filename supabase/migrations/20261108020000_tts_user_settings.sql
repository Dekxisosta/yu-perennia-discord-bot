-- Per-user TTS switch (/tts-enable). Written by the bot with the service key.
create table if not exists public.tts_user_settings (
  user_id     text primary key check (user_id ~ '^[0-9]{5,25}$'),
  enabled     boolean not null default true,
  updated_at  timestamptz not null default now()
);
alter table public.tts_user_settings enable row level security;
