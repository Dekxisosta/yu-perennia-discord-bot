-- Website RPC: delete one config file. The bot falls back to its bundled YAML for it.
create or replace function public.admin_delete_config(p_key text, p_name text)
returns void
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  if not public.is_admin_key(p_key) then
    raise exception 'invalid admin key' using errcode = '28000';
  end if;
  delete from public.bot_config where name = p_name;
end;
$$;

revoke all on function public.admin_delete_config(text, text) from public;
grant execute on function public.admin_delete_config(text, text) to anon, authenticated;
