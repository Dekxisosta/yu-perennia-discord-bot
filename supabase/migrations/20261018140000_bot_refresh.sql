-- "Refresh bot" button: the website stamps a time on the bot_status row, and the bot notices it on its
-- regular status poll (no extra requests) and reloads its config.
alter table public.bot_status add column if not exists refresh_requested_at timestamptz;

create or replace function public.admin_request_refresh(p_key text)
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
  -- If no status has been saved yet, the inserted values mirror DEFAULT in src/cogs/events/cog_presence.py
  -- so a refresh request never changes what Yu is showing.
  insert into public.bot_status (id, status, activity_type, message, refresh_requested_at)
  values (1, 'dnd', 'playing', 'Apologies, Masters... Under Maintenance', ts)
  on conflict (id) do update set refresh_requested_at = ts;
  return ts;
end;
$$;

revoke all on function public.admin_request_refresh(text) from public;
grant execute on function public.admin_request_refresh(text) to anon, authenticated;
