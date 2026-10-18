-- Yu's Discord presence (single row, id = 1). The bot polls it; the website edits it via RPC.
create table if not exists public.bot_status (
  id             int primary key default 1 check (id = 1),
  status         text not null default 'online'
                 check (status in ('online', 'idle', 'dnd', 'invisible')),
  activity_type  text not null default 'playing'
                 check (activity_type in ('none', 'playing', 'listening', 'watching', 'competing', 'custom')),
  message        text check (message is null or length(message) <= 128),
  updated_at     timestamptz not null default now()
);
alter table public.bot_status enable row level security;

create or replace function public.admin_get_status(p_key text)
returns table (status text, activity_type text, message text, updated_at timestamptz)
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  if not public.is_admin_key(p_key) then
    raise exception 'invalid admin key' using errcode = '28000';
  end if;
  return query select s.status, s.activity_type, s.message, s.updated_at
               from public.bot_status s where s.id = 1;
end;
$$;

create or replace function public.admin_set_status(
  p_key text, p_status text, p_activity_type text, p_message text default null)
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
  insert into public.bot_status (id, status, activity_type, message, updated_at)
  values (1, p_status, p_activity_type, nullif(trim(p_message), ''), ts)
  on conflict (id) do update
    set status = excluded.status, activity_type = excluded.activity_type,
        message = excluded.message, updated_at = excluded.updated_at;
  return ts;
end;
$$;

revoke all on function public.admin_get_status(text)                     from public;
revoke all on function public.admin_set_status(text, text, text, text)   from public;
grant execute on function public.admin_get_status(text)                   to anon, authenticated;
grant execute on function public.admin_set_status(text, text, text, text) to anon, authenticated;
