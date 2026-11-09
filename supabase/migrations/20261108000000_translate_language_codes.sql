-- Allow every DeepL language key (e.g. 'zh-hant', 'pt-br', and codes with digits like 'es-419').
alter table public.translate_channels
  drop constraint if exists translate_channels_language_check;
alter table public.translate_channels
  add constraint translate_channels_language_check
  check (language ~ '^[a-zA-Z0-9-]{2,12}$');
