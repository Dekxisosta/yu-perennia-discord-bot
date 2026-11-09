-- Voice choices: server default voice (/server-settings setvoice) and personal voice (/setvoice).
-- Auto-join now reads the joined voice channel's own chat, so text_channel_id is no longer used.
alter table public.guild_settings add column if not exists voice text;
alter table public.tts_user_settings add column if not exists voice text;
