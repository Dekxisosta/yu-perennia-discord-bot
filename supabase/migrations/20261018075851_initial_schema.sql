-- Run once in the Supabase SQL editor.

create extension if not exists pgcrypto with schema extensions;

-- One row per config file (general, mod, utility, translate, exception ...).
create table if not exists public.bot_config (
  name        text primary key,
  data        jsonb not null check (jsonb_typeof(data) = 'object'),
  updated_at  timestamptz not null default now()
);

-- Admin keys are stored only as SHA-256 hashes.
create table if not exists public.admin_keys (
  id          uuid primary key default gen_random_uuid(),
  label       text,
  key_hash    text not null unique,
  created_at  timestamptz not null default now()
);

-- RLS on with no policies: the public (anon) key can't read or write either table
-- directly. The bot uses the service role key, which bypasses RLS.
alter table public.bot_config  enable row level security;
alter table public.admin_keys  enable row level security;

-- Internal check, not callable from the website.
create or replace function public.is_admin_key(p_key text)
returns boolean
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  if p_key is not null and length(p_key) > 0 and exists (
    select 1 from public.admin_keys
    where key_hash = encode(digest(p_key, 'sha256'), 'hex')
  ) then
    return true;
  end if;
  perform pg_sleep(1);  -- slow down guessing
  return false;
end;
$$;

-- Website RPC: list every config file.
create or replace function public.admin_list_configs(p_key text)
returns table (name text, data jsonb, updated_at timestamptz)
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  if not public.is_admin_key(p_key) then
    raise exception 'invalid admin key' using errcode = '28000';
  end if;
  return query select c.name, c.data, c.updated_at from public.bot_config c order by c.name;
end;
$$;

-- Website RPC: create or replace one config file.
create or replace function public.admin_save_config(p_key text, p_name text, p_data jsonb)
returns timestamptz
language plpgsql
security definer
set search_path = public, extensions
as $$
declare ts timestamptz := now();
begin
  if not public.is_admin_key(p_key) then
    raise exception 'invalid admin key' using errcode = '28000';
  end if;
  if p_name !~ '^[a-z0-9_]{1,40}$' then
    raise exception 'invalid config name';
  end if;
  insert into public.bot_config (name, data, updated_at) values (p_name, p_data, ts)
  on conflict (name) do update set data = excluded.data, updated_at = excluded.updated_at;
  return ts;
end;
$$;

revoke all on function public.is_admin_key(text)                    from public, anon, authenticated;
revoke all on function public.admin_list_configs(text)              from public;
revoke all on function public.admin_save_config(text, text, jsonb)  from public;
grant execute on function public.admin_list_configs(text)             to anon, authenticated;
grant execute on function public.admin_save_config(text, text, jsonb) to anon, authenticated;

-- ---------------------------------------------------------------------------
-- Translation channels: Discord channel id -> language (zh | ja | off).
-- The bot reads/writes this with the service role key; `label` is a free-form
-- note for the dashboard (the website can't look up Discord channel names).
-- ---------------------------------------------------------------------------
create table if not exists public.translate_channels (
  channel_id  text primary key check (channel_id ~ '^[0-9]{5,25}$'),
  language    text not null check (language ~ '^[a-zA-Z-]{2,10}$'),
  label       text,
  updated_at  timestamptz not null default now()
);
alter table public.translate_channels enable row level security;

create or replace function public.admin_list_translate_channels(p_key text)
returns table (channel_id text, language text, label text, updated_at timestamptz)
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  if not public.is_admin_key(p_key) then
    raise exception 'invalid admin key' using errcode = '28000';
  end if;
  return query select t.channel_id, t.language, t.label, t.updated_at
               from public.translate_channels t order by t.updated_at desc;
end;
$$;

create or replace function public.admin_set_translate_channel(
  p_key text, p_channel_id text, p_language text, p_label text default null)
returns void
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  if not public.is_admin_key(p_key) then
    raise exception 'invalid admin key' using errcode = '28000';
  end if;
  insert into public.translate_channels (channel_id, language, label, updated_at)
  values (p_channel_id, p_language, nullif(trim(p_label), ''), now())
  on conflict (channel_id) do update
    set language = excluded.language, label = excluded.label, updated_at = excluded.updated_at;
end;
$$;

create or replace function public.admin_delete_translate_channel(p_key text, p_channel_id text)
returns void
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  if not public.is_admin_key(p_key) then
    raise exception 'invalid admin key' using errcode = '28000';
  end if;
  delete from public.translate_channels where channel_id = p_channel_id;
end;
$$;

revoke all on function public.admin_list_translate_channels(text)                    from public;
revoke all on function public.admin_set_translate_channel(text, text, text, text)    from public;
revoke all on function public.admin_delete_translate_channel(text, text)             from public;
grant execute on function public.admin_list_translate_channels(text)                 to anon, authenticated;
grant execute on function public.admin_set_translate_channel(text, text, text, text) to anon, authenticated;
grant execute on function public.admin_delete_translate_channel(text, text)          to anon, authenticated;

-- Create your admin key (generate one with `openssl rand -hex 32`), then run:
-- insert into public.admin_keys (label, key_hash)
-- values ('main', encode(extensions.digest('PASTE-YOUR-KEY-HERE', 'sha256'), 'hex'));
