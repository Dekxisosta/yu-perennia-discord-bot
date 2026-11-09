-- Per-server bot settings (currently: voice auto-join). Written by the bot with the service key.
create table if not exists public.guild_settings (
  guild_id         text primary key check (guild_id ~ '^[0-9]{5,25}$'),
  auto_join        boolean not null default false,
  text_channel_id  text check (text_channel_id is null or text_channel_id ~ '^[0-9]{5,25}$'),
  updated_at       timestamptz not null default now()
);
alter table public.guild_settings enable row level security;
