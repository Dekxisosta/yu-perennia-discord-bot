-- Auto-join is now per voice channel (/server-settings auto-join toggle | add | remove) instead of server-wide.
-- The old guild-wide `auto_join` flag is no longer read; servers re-pick their channels.
alter table public.guild_settings add column if not exists auto_join_channels text[] not null default '{}';
