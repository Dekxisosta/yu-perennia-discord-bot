-- /server-settings vcgreettoggle: Yu greets people who join her voice channel and says goodbye when they leave.
alter table public.guild_settings add column if not exists vc_greet boolean not null default false;
