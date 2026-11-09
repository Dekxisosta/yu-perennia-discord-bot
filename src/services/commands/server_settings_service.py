import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from utils.console_logger import log
from utils.supabase_client import get_client

MODULE = "SERVER_SETTINGS"

TRANSLATE_APIS = ("deepl", "google")

DEFAULTS = {"auto_join_channels": [], "chat_mode_channels": [], "voice": None, "vc_greet": False, "vc_enabled": True,
            "vc_sayname": True, "vc_translate": True, "translate_api": "deepl"}


class ServerSettings:
    """Per-server settings (guild id -> {auto_join_channels, chat_mode_channels, voice, vc_greet, vc_enabled,
    vc_sayname, vc_translate, translate_api}).

    `auto_join_channels` is the list of voice channel ids Yu auto-joins (a channel is on the list
    after `/server-settings auto-join toggle` or `auto-join add`). Servers have no "all channels"
    switch. Yu reads the chat of the voice channel she joins, so no text channel is stored.
    `chat_mode_channels` is the list of text channel ids where Yu takes part in the conversation instead of reading
    messages aloud (`/vcchatmodetoggle`). `voice` is the server's default voice key (None = the config default).

    Stored in Supabase (table `guild_settings`) when configured, with a local JSON
    file as an offline cache/fallback, the same way translate channels are.
    Supabase is read once at startup; changes are written through to both.
    """

    TABLE = "guild_settings"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._load()

    # ---- storage
    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            log(f"Could not read {self.path.name}: {e}", module_name=MODULE, success=False)
            return
        if isinstance(raw, dict):
            self._data = {str(k): self._clean(v) for k, v in raw.items() if isinstance(v, dict)}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            log(f"Could not save {self.path.name}: {e}", module_name=MODULE, success=False)

    @staticmethod
    def _ids(value) -> list[str]:
        if not isinstance(value, (list, tuple, set)):
            return []
        return sorted({str(c) for c in value if str(c).isdigit()})

    @staticmethod
    def _clean(value: dict) -> dict:
        voice = value.get("voice")
        return {
            "auto_join_channels": ServerSettings._ids(value.get("auto_join_channels")),
            "chat_mode_channels": ServerSettings._ids(value.get("chat_mode_channels")),
            "voice": str(voice) if voice else None,
            "vc_greet": bool(value.get("vc_greet")),
            "vc_enabled": bool(value.get("vc_enabled", True)),
            "vc_sayname": bool(value.get("vc_sayname", True)),
            "vc_translate": bool(value.get("vc_translate", True)),
            "translate_api": api if (api := str(value.get("translate_api") or "deepl").lower()) in TRANSLATE_APIS else "deepl",
        }

    def refresh(self) -> bool:
        """Pull settings from Supabase (blocking; run in a thread from async code)."""
        client = get_client()
        if client is None:
            return False
        try:
            rows = client.table(self.TABLE).select("guild_id,auto_join_channels,chat_mode_channels,voice,vc_greet,vc_enabled,vc_sayname,vc_translate,translate_api").execute().data or []
        except Exception as e:
            log(f"Could not load server settings from Supabase: {e}", module_name=MODULE, success=False)
            return False
        remote = {str(r["guild_id"]): self._clean(r) for r in rows}
        with self._lock:
            self._data = remote
        self._save()
        log(f"Loaded settings for {len(remote)} server(s) from Supabase.", module_name=MODULE, success=True)
        return True

    def _push(self, guild_id: str, value: dict) -> None:
        client = get_client()
        if client is None:
            return
        try:
            client.table(self.TABLE).upsert({
                "guild_id": guild_id,
                "auto_join_channels": value["auto_join_channels"],
                "chat_mode_channels": value["chat_mode_channels"],
                "voice": value["voice"],
                "vc_greet": value["vc_greet"],
                "vc_enabled": value["vc_enabled"],
                "vc_sayname": value["vc_sayname"],
                "vc_translate": value["vc_translate"],
                "translate_api": value["translate_api"],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            log(f"Could not save server {guild_id} to Supabase: {e}", module_name=MODULE, success=False)

    # ---- access
    def get(self, guild_id: int) -> dict:
        return {**DEFAULTS, **self._data.get(str(guild_id), {})}

    def set(self, guild_id: int, **fields) -> dict:
        with self._lock:
            value = self._clean({**self.get(guild_id), **fields})
            self._data[str(guild_id)] = value
        self._save()
        threading.Thread(target=self._push, args=(str(guild_id), value), daemon=True).start()
        return value

    def auto_join_guilds(self) -> list[int]:
        return [int(g) for g, v in self._data.items() if v.get("auto_join_channels")]

    # ---- auto-join channels (only these voice channels are auto-joined)
    def auto_join_channel_ids(self, guild_id: int) -> list[int]:
        return [int(c) for c in self.get(guild_id)["auto_join_channels"]]

    def is_auto_join_channel(self, guild_id: int, channel_id: int) -> bool:
        return str(channel_id) in self.get(guild_id)["auto_join_channels"]

    def set_auto_join_channel(self, guild_id: int, channel_id: int, enabled: bool) -> bool:
        """Add/remove one voice channel. Returns False if nothing changed (already in that state)."""
        current = set(self.get(guild_id)["auto_join_channels"])
        before = set(current)
        (current.add if enabled else current.discard)(str(channel_id))
        if current == before:
            return False
        self.set(guild_id, auto_join_channels=sorted(current))
        return True

    # ---- chat mode channels (Yu chats in these text channels instead of reading them aloud)
    def is_chat_mode_channel(self, guild_id: int, channel_id: int) -> bool:
        return str(channel_id) in self.get(guild_id)["chat_mode_channels"]

    def set_chat_mode_channel(self, guild_id: int, channel_id: int, enabled: bool) -> bool:
        """Turn chat mode on/off for one text channel. Returns False if nothing changed."""
        current = set(self.get(guild_id)["chat_mode_channels"])
        before = set(current)
        (current.add if enabled else current.discard)(str(channel_id))
        if current == before:
            return False
        self.set(guild_id, chat_mode_channels=sorted(current))
        return True


class UserSettings:
    """Per-user TTS settings (user id -> {enabled, voice}).

    `enabled` is the personal /user-settings vctoggle switch: True/False when the person chose, None when they
    never did (or reset it), in which case the server's vctoggle decides. `sayname` works the
    same way for /user-settings vcsayname: whether Yu says "<name> says." before reading their messages. `voice` is the personal voice key
    from /user-settings vcsetvoice (None = fall back to the server's voice, then the
    config default).

    Same storage as ServerSettings: Supabase table `tts_user_settings` when configured,
    with a local JSON file as the offline cache/fallback.
    """

    TABLE = "tts_user_settings"
    DEFAULTS = {"enabled": None, "voice": None, "sayname": None}

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = {str(k): self._clean(v) for k, v in raw.items()}
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log(f"Could not read {self.path.name}: {e}", module_name=MODULE, success=False)

    @staticmethod
    def _clean(value) -> dict:
        if isinstance(value, bool):  # old file format: user id -> enabled (True was just the default)
            return {"enabled": False if value is False else None, "voice": None, "sayname": None}
        value = value if isinstance(value, dict) else {}
        voice = value.get("voice")
        enabled = value.get("enabled")
        sayname = value.get("sayname")
        return {
            "enabled": None if enabled is None else bool(enabled),
            "voice": str(voice) if voice else None,
            "sayname": None if sayname is None else bool(sayname),
        }

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            log(f"Could not save {self.path.name}: {e}", module_name=MODULE, success=False)

    def refresh(self) -> bool:
        """Pull settings from Supabase (blocking; run in a thread from async code)."""
        client = get_client()
        if client is None:
            return False
        try:
            rows = client.table(self.TABLE).select("user_id,enabled,voice,sayname").execute().data or []
        except Exception as e:
            log(f"Could not load TTS user settings from Supabase: {e}", module_name=MODULE, success=False)
            return False
        with self._lock:
            self._data = {str(r["user_id"]): self._clean(r) for r in rows}
        self._save()
        return True

    def _push(self, user_id: str, value: dict) -> None:
        client = get_client()
        if client is None:
            return
        try:
            client.table(self.TABLE).upsert({
                "user_id": user_id,
                "enabled": value["enabled"],
                "voice": value["voice"],
                "sayname": value["sayname"],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            log(f"Could not save TTS setting for {user_id} to Supabase: {e}", module_name=MODULE, success=False)

    def get(self, user_id: int) -> dict:
        return {**self.DEFAULTS, **self._data.get(str(user_id), {})}

    def _set(self, user_id: int, **fields) -> None:
        with self._lock:
            value = self._clean({**self.get(user_id), **fields})
            self._data[str(user_id)] = value
        self._save()
        threading.Thread(target=self._push, args=(str(user_id), value), daemon=True).start()

    def get_enabled(self, user_id: int) -> bool | None:
        return self.get(user_id)["enabled"]

    def is_enabled(self, user_id: int, default: bool = True) -> bool:
        """The person's own choice if they made one, otherwise `default` (the server's setting)."""
        value = self.get(user_id)["enabled"]
        return default if value is None else value

    def set_enabled(self, user_id: int, enabled: bool | None) -> None:
        self._set(user_id, enabled=enabled)

    def get_sayname(self, user_id: int) -> bool | None:
        return self.get(user_id)["sayname"]

    def is_sayname(self, user_id: int, default: bool = True) -> bool:
        """The person's own choice if they made one, otherwise `default` (the server's setting)."""
        value = self.get(user_id)["sayname"]
        return default if value is None else value

    def set_sayname(self, user_id: int, sayname: bool | None) -> None:
        self._set(user_id, sayname=sayname)

    def get_voice(self, user_id: int) -> str | None:
        return self.get(user_id)["voice"]

    def set_voice(self, user_id: int, voice: str | None) -> None:
        self._set(user_id, voice=voice)
