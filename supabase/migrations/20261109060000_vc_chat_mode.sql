-- /vcchatmodetoggle: the text channels where Yu takes part in the conversation instead of reading messages aloud.
alter table public.guild_settings add column if not exists chat_mode_channels text[] not null default '{}';
