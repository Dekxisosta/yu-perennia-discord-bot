-- /vctoggle now exists for the server (/server-settings vctoggle) and the user (/vctoggle,
-- /user-settings vctoggle). The user's choice wins; no choice (null) follows the server.
alter table public.guild_settings add column if not exists vc_enabled boolean not null default true;

alter table public.tts_user_settings alter column enabled drop not null;
alter table public.tts_user_settings alter column enabled drop default;
-- Old rows had enabled = true only because it was the default, so treat those as "no choice".
update public.tts_user_settings set enabled = null where enabled = true;
