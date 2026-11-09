-- /vcsayname: whether Yu says "<name> says." before reading messages.
-- Server default on (/server-settings vcsayname); a user's own choice wins, null follows the server.
alter table public.guild_settings add column if not exists vc_sayname boolean not null default true;
alter table public.tts_user_settings add column if not exists sayname boolean;
