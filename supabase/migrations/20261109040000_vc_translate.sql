-- /server-settings vctranslatetoggle and /server-settings translate-api (deepl | google).
alter table public.guild_settings add column if not exists vc_translate boolean not null default true;
alter table public.guild_settings add column if not exists translate_api text not null default 'deepl'
  check (translate_api in ('deepl', 'google'));
