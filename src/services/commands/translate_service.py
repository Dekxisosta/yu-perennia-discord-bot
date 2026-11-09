import asyncio
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import aiohttp
import discord
from discord.ext import commands
from dotenv import load_dotenv

from utils.console_logger import log
from utils.supabase_client import get_client

load_dotenv()

MODULE = "TRANSLATE"

HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
KANA = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")

# Fast path: if the text contains a language's own script it is already in that
# language, so no detection is needed. Latin-script languages (Spanish, French,
# German, Portuguese, English) are handled by DeepL's language detection.
SCRIPTS: dict[str, re.Pattern] = {
    "ZH": HAN,
    "JA": re.compile(HAN.pattern[:-1] + KANA.pattern[1:]),
    "RU": re.compile(r"[\u0400-\u04ff]"),
    "AR": re.compile(r"[\u0600-\u06ff\u0750-\u077f]"),
    "HI": re.compile(r"[\u0900-\u097f]"),
}


# ---------------------------------------------------------------- languages
@dataclass(frozen=True)
class Language:
    key: str    # internal key, also what is stored in the channel config (letters/digits only)
    label: str  # shown to users
    deepl: str  # DeepL target_lang code
    flag: str

    @property
    def base(self) -> str:
        """DeepL base code, e.g. 'PT-BR' -> 'PT'. Also what DeepL reports as the detected/source language."""
        return self.deepl.split("-")[0].upper()


# The only languages Yu supports. Keys stay free of hyphens so a channel setting
# can be stored as "<source>-<target>" (see encode_setting).
LANGUAGES: dict[str, Language] = {
    lang.key: lang
    for lang in (
        Language("en", "English", "EN-US", "\U0001f1fa\U0001f1f8"),
        Language("es", "Spanish", "ES", "\U0001f1ea\U0001f1f8"),
        Language("cmn", "Mandarin Chinese", "ZH", "\U0001f1e8\U0001f1f3"),
        Language("zh", "Simplified Chinese", "ZH-HANS", "\U0001f1e8\U0001f1f3"),  # "zh" is what older saves use
        Language("zhhant", "Traditional Chinese", "ZH-HANT", "\U0001f1f9\U0001f1fc"),
        Language("fr", "French", "FR", "\U0001f1eb\U0001f1f7"),
        Language("de", "German", "DE", "\U0001f1e9\U0001f1ea"),
        Language("ar", "Arabic", "AR", "\U0001f1f8\U0001f1e6"),
        Language("hi", "Hindi", "HI", "\U0001f1ee\U0001f1f3"),
        Language("ja", "Japanese", "JA", "\U0001f1ef\U0001f1f5"),
        Language("ru", "Russian", "RU", "\U0001f1f7\U0001f1fa"),
        Language("pt", "Portuguese", "PT-BR", "\U0001f1e7\U0001f1f7"),
    )
}
ENGLISH = LANGUAGES["en"]

# Keys saved by older versions (when every DeepL language was allowed)
LEGACY_KEYS = {"zh-hant": "zhhant", "zh-hans": "zh", "pt-br": "pt", "pt-pt": "pt"}

OFF_WORDS = {"off", "none", "disable", "stop"}
AUTO_WORDS = {"auto", "automatic", "detect", "auto-detect", "autodetect"}
ALIASES = {
    "mandarin": "cmn",
    "chinese": "zh", "cn": "zh", "simplified": "zh", "zh-hans": "zh", "\u4e2d\u6587": "zh",
    "traditional": "zhhant", "zh-hant": "zhhant", "tw": "zhhant",
    "jp": "ja", "\u65e5\u672c\u8a9e": "ja",
    "pt-br": "pt", "pt-pt": "pt", "brazilian": "pt",
    "en-us": "en", "en-gb": "en",
}


def _lookup(value: str | None) -> str | None:
    """Language key for a key, alias, display name or DeepL code; None if unsupported."""
    v = (value or "").strip().lower()
    if not v:
        return None
    if v in LANGUAGES:
        return v
    if ALIASES.get(v) in LANGUAGES:
        return ALIASES[v]
    for lang in LANGUAGES.values():
        if v in (lang.deepl.lower(), lang.label.lower()):
            return lang.key
    return None


def resolve_language(value: str | None) -> str | None:
    """Target language: a language key, 'off', or None if unknown."""
    if (value or "").strip().lower() in OFF_WORDS:
        return "off"
    return _lookup(value)


def resolve_source(value: str | None) -> str | None:
    """Input language: a language key, 'auto' (also for an empty value), or None if unknown."""
    v = (value or "").strip().lower()
    if not v or v in AUTO_WORDS:
        return "auto"
    return _lookup(v)


def supported_names() -> str:
    return ", ".join(lang.label for lang in LANGUAGES.values())


def language_options(query: str = "", limit: int = 25, extra: tuple[str, str] = ("Off", "off")) -> list[tuple[str, str]]:
    """(label, key) pairs for slash-command autocomplete; `extra` (Off / Auto-detect) first."""
    q = query.strip().lower()
    pool = [extra] + [(f"{l.flag} {l.label}", l.key) for l in LANGUAGES.values()]
    hits = [(n, k) for n, k in pool if not q or q in n.lower() or q in k]
    return hits[:limit]


# ------------------------------------------------------------------ DeepL
class TranslationError(Exception):
    """kind: not_configured | quota | rate_limit | auth | failed"""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(detail or kind)
        self.kind = kind


class Translation(NamedTuple):
    text: str
    source: str  # DeepL's detected source language, base code ("ES", "ZH"); "" if unknown


class Translator:
    """Thin async DeepL client. One shared aiohttp session per instance."""

    def __init__(self, api_key: str | None = None, url: str | None = None):
        self.api_key = api_key if api_key is not None else os.getenv("DEEPL_API_KEY")
        self._url = url
        self._session: aiohttp.ClientSession | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def url(self) -> str:
        if self._url:
            return self._url
        # Free-tier keys end in ":fx" and use a different host
        if self.api_key and self.api_key.endswith(":fx"):
            return "https://api-free.deepl.com/v2/translate"
        return "https://api.deepl.com/v2/translate"

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def translate(self, text: str, target_code: str, source_code: str | None = None) -> Translation:
        """Translate into target_code. source_code forces the input language; None lets DeepL detect it."""
        if not self.configured:
            raise TranslationError("not_configured")
        body = {"text": [text], "target_lang": target_code}
        if source_code:
            body["source_lang"] = source_code.split("-")[0].upper()
        try:
            async with self._get_session().post(
                self.url,
                headers={"Authorization": f"DeepL-Auth-Key {self.api_key}"},
                json=body,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as res:
                if res.status == 200:
                    t = (await res.json())["translations"][0]
                    return Translation(t["text"], (t.get("detected_source_language") or "").split("-")[0].upper())
                if res.status == 429:
                    raise TranslationError("rate_limit")
                if res.status == 456:
                    raise TranslationError("quota")
                if res.status in (401, 403):
                    raise TranslationError("auth", f"DeepL rejected the API key ({res.status})")
                raise TranslationError("failed", f"DeepL returned {res.status}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise TranslationError("failed", str(e) or type(e).__name__)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


class GoogleTranslator:
    """Async Google Cloud Translation (v2, API key) client with the same interface as Translator.

    Reads GOOGLE_TRANSLATE_API_KEY. Used for voice-chat reading when a server picks it with
    /server-settings translate-api.
    """

    URL = "https://translation.googleapis.com/language/translate/v2"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key if api_key is not None else os.getenv("GOOGLE_TRANSLATE_API_KEY")
        self._session: aiohttp.ClientSession | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def translate(self, text: str, target_code: str, source_code: str | None = None) -> Translation:
        if not self.configured:
            raise TranslationError("not_configured")
        target = target_code.split("-")[0].lower()  # "EN-US" -> "en"
        body = {"q": text, "target": target, "format": "text"}
        if source_code:
            body["source"] = source_code.split("-")[0].lower()
        try:
            async with self._get_session().post(
                self.URL,
                params={"key": self.api_key},
                json=body,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as res:
                if res.status == 200:
                    t = (await res.json())["data"]["translations"][0]
                    source = (t.get("detectedSourceLanguage") or "").split("-")[0].upper()
                    return Translation(t["translatedText"], source)
                body = (await res.text()).lower()
                if res.status == 429 or "ratelimit" in body:
                    raise TranslationError("rate_limit")
                if res.status in (400, 401, 403):
                    if "quota" in body or "dailylimit" in body:
                        raise TranslationError("quota")
                    raise TranslationError("auth", f"Google rejected the API key or request ({res.status})")
                raise TranslationError("failed", f"Google returned {res.status}")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, IndexError) as e:
            raise TranslationError("failed", str(e) or type(e).__name__)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


# -------------------------------------------------------- per-channel config
class ChannelConfig(NamedTuple):
    source: Language | None  # None = auto-detect the input language
    target: Language


def encode_setting(source_key: str | None, target_key: str) -> str:
    """'fr' (auto-detect input, translate into French) or 'ja-fr' (Japanese <-> French)."""
    return target_key if not source_key else f"{source_key}-{target_key}"


def decode_setting(value: str | None) -> ChannelConfig | None:
    """Inverse of encode_setting. None for 'off', unknown or no-longer-supported languages."""
    v = (value or "").strip().lower()
    v = LEGACY_KEYS.get(v, v)
    if v in LANGUAGES:
        return ChannelConfig(None, LANGUAGES[v])
    if "-" in v:
        src, tgt = (LEGACY_KEYS.get(part, part) for part in v.split("-", 1))
        if src in LANGUAGES and tgt in LANGUAGES and src != tgt:
            return ChannelConfig(LANGUAGES[src], LANGUAGES[tgt])
    return None


class ChannelSettings:
    """channel id -> setting ('<target>' or '<source>-<target>', see encode_setting).

    Stored in Supabase (table `translate_channels`) when configured, with a local
    JSON file as an offline cache/fallback. Channels listed in TRANSLATE_CHANNEL_IDS
    are seeded with a default language; anything set with /translate or in the admin
    dashboard overrides the seed (and 'off' disables a seeded channel).
    """

    TABLE = "translate_channels"

    def __init__(self, path: str | Path, seed_ids: set[int], default_key: str):
        self.path = Path(path)
        self._seed = {cid: default_key for cid in seed_ids}
        self._saved: dict[str, str] = {}
        self._pending = 0
        self._lock = threading.Lock()
        self._load()
        self.refresh()

    @staticmethod
    def _valid(data: dict) -> dict[str, str]:
        # Lenient on purpose: the language list may not be loaded from DeepL yet, and
        # dropping an unknown key here would erase that channel's saved setting.
        return {str(k): v for k, v in data.items() if isinstance(v, str) and re.fullmatch(r"[a-z0-9-]{2,12}|off", v)}

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            log(f"Could not read {self.path.name}: {e}", module_name=MODULE, success=False)
            return
        self._saved = self._valid(data)

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._saved, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            log(f"Could not save {self.path.name}: {e}", module_name=MODULE, success=False)

    def refresh(self) -> bool:
        """Pull channel settings from Supabase (blocking; run in a thread from async code).

        Returns True if Supabase answered. On any failure the current values stay.
        """
        client = get_client()
        if client is None:
            return False
        with self._lock:
            if self._pending:  # a local change is still being pushed; don't overwrite it
                return False
        try:
            rows = client.table(self.TABLE).select("channel_id,language").execute().data or []
        except Exception as e:
            log(f"Could not load translate channels from Supabase: {e}", module_name=MODULE, success=False)
            return False
        remote = self._valid({r["channel_id"]: r["language"] for r in rows})
        with self._lock:
            if self._pending:
                return False
            changed = remote != self._saved
            self._saved = remote
        if changed:
            self._save()
            log(f"Loaded {len(remote)} translate channel(s) from Supabase.", module_name=MODULE, success=True)
        return True

    def _push(self, channel_id: str, key: str) -> None:
        client = get_client()
        try:
            if client is not None:
                client.table(self.TABLE).upsert(
                    {"channel_id": channel_id, "language": key, "updated_at": datetime.now(timezone.utc).isoformat()}
                ).execute()
        except Exception as e:
            log(f"Could not save channel {channel_id} to Supabase: {e}", module_name=MODULE, success=False)
        finally:
            with self._lock:
                self._pending -= 1

    def get(self, channel_id: int) -> ChannelConfig | None:
        return decode_setting(self._saved.get(str(channel_id), self._seed.get(channel_id)))

    def set(self, channel_id: int, key: str) -> None:
        self._saved[str(channel_id)] = key
        self._save()
        if get_client() is not None:
            with self._lock:
                self._pending += 1
            threading.Thread(target=self._push, args=(str(channel_id), key), daemon=True).start()

    @property
    def active_count(self) -> int:
        ids = set(self._seed) | {int(k) for k in self._saved}
        return sum(1 for cid in ids if self.get(cid) is not None)

    @property
    def unsupported_count(self) -> int:
        """Channels saved with a language that is no longer in the supported list (they stay silent)."""
        ids = set(self._seed) | {int(k) for k in self._saved}
        return sum(
            1 for cid in ids
            if self.get(cid) is None and self._saved.get(str(cid), self._seed.get(cid)) not in (None, "off")
        )


# ------------------------------------------------------------- core logic
def clean(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text)    # URLs
    text = re.sub(r"<a?:\w+:\d+>", "", text)    # custom emoji
    text = re.sub(r"<[@#&!]+\d+>", "", text)    # mentions / channels
    text = re.sub(r"<(?:t:-?\d+(?::[a-zA-Z])?|id:\w+)>", "", text)  # timestamps / guild nav
    text = re.sub(r"```[\s\S]*?```", "", text)  # code blocks
    return text.strip()


def parse_channel_ids(raw: str | None) -> set[int]:
    return {int(c) for c in (raw or "").split(",") if c.strip().isdigit()}


class SameLanguage(Exception):
    """The text is already in the language it would be translated into."""


MESSAGE_DEFAULTS = {
    "unknown-language": "Sorry, that's not on the menu! Yu can do: {languages}.",
    "same-language": "Hm? Both sides are {language}! Pick two different languages!",
    "already-target": "That's already in {language}! Nothing for Yu to translate!",
    "channel-set": "Order received! Yu will translate everything in this channel into {language} {flag}, and anything already in {language} into English! \U0001f375",
    "channel-set-english": "Order received! Yu will translate everything in this channel into English {flag}! \U0001f375",
    "channel-set-pair": "Order received! Yu will translate between {source} {source_flag} and {language} {flag} in this channel! \U0001f375",
}


def _msg(cfg: dict, key: str, **fmt) -> str:
    text = cfg.get(key) or MESSAGE_DEFAULTS[key]
    try:
        return text.format(**fmt)
    except (KeyError, IndexError):
        return text


def _in_script(base: str, text: str) -> bool:
    """True if the text contains the language's own script (Japanese kana rule Chinese out)."""
    pattern = SCRIPTS.get(base)
    if not pattern or not pattern.search(text):
        return False
    return not (base == "ZH" and KANA.search(text))


async def translate_for(
    translator: Translator, text: str, target: Language, source: Language | None = None
) -> tuple[str, Language] | None:
    """Translate `text` and pick the direction automatically.

    source=None (auto): the input can be in any language and is translated into
    `target`. Text that is already in `target` goes to English instead.

    source=<language>: a two-way pair. Text in `source` goes to `target`, text in
    `target` goes to `source`, and anything else goes to `target`.

    Returns (text, language_it_was_translated_into), or None if the text has no
    letters (digits, symbols, emoji only). Raises SameLanguage when there is
    nothing to translate (already English and the target is English).
    """
    if not any(ch.isalpha() for ch in text):
        return None

    if source is None:
        if _in_script(target.base, text):
            return (await translator.translate(text, ENGLISH.deepl)).text, ENGLISH
        first = await translator.translate(text, target.deepl)
        if first.source == target.base:
            if target.base == ENGLISH.base:
                raise SameLanguage()
            return (await translator.translate(text, ENGLISH.deepl)).text, ENGLISH
        return first.text, target

    if source.base == target.base:  # e.g. Simplified <-> Traditional: same script detection, so go one way
        return (await translator.translate(text, target.deepl, source.base)).text, target
    if _in_script(source.base, text):
        return (await translator.translate(text, target.deepl)).text, target
    if _in_script(target.base, text):
        return (await translator.translate(text, source.deepl)).text, source
    first = await translator.translate(text, target.deepl)
    if first.source == target.base:
        return (await translator.translate(text, source.deepl)).text, source
    return first.text, target


def _error_text(err: TranslationError, cfg: dict) -> str:
    key = {
        "not_configured": "not-configured",
        "quota": "quota",
        "rate_limit": "rate-limit",
    }.get(err.kind, "failed")
    return cfg[key]


_SOURCE_TOKEN = re.compile(r"^\s*(?:from|source)[:=]\s*(\S+)\s*", re.IGNORECASE)


def _split_source(text: str | None, source: str | None) -> tuple[str | None, str | None]:
    """Prefix commands have no 'from' option, so `yp!translate fr from:ja hello` is read from the text."""
    match = _SOURCE_TOKEN.match(text or "")
    if not match:
        return source, text
    return match.group(1), (text or "")[match.end():]


# /translate <to> [text] [from]
#   no text   -> set this channel's auto-translate languages (or 'off')
#   with text -> translate that text once
#   from      -> the input language; "auto" (default) detects it
async def translate_command(
    ctx: commands.Context,
    translator: Translator,
    settings: ChannelSettings,
    language: str,
    text: str | None,
    cfg: dict,
    source: str | None = "auto",
):
    unknown = _msg(cfg, "unknown-language", languages=supported_names())
    target_key = resolve_language(language)
    if target_key is None:
        await ctx.send(unknown, ephemeral=True)
        return

    source, text = _split_source(text, source)
    source_key = resolve_source(source)
    if source_key is None:
        await ctx.send(unknown, ephemeral=True)
        return
    if target_key != "off" and source_key == target_key:
        await ctx.send(_msg(cfg, "same-language", language=LANGUAGES[target_key].label), ephemeral=True)
        return
    src = None if source_key == "auto" else LANGUAGES[source_key]

    text = clean(text or "")
    if not text:
        if ctx.guild is None:
            await ctx.send(cfg["server-only"], ephemeral=True)
            return
        await _configure_channel(ctx, translator, settings, target_key, src, cfg)
        return

    if target_key == "off":
        await ctx.send(cfg["off-with-text"], ephemeral=True)
        return

    target = LANGUAGES[target_key]
    await ctx.defer()
    try:
        if src is None:
            result = await translate_for(translator, text, target)
        elif not any(ch.isalpha() for ch in text):
            result = None
        else:  # an explicit input language is taken at its word: input -> output
            result = (await translator.translate(text, target.deepl, src.base)).text, target
    except SameLanguage:
        await ctx.send(_msg(cfg, "already-target", language=target.label), ephemeral=True)
        return
    except TranslationError as e:
        log(f"Command failed: {e}", module_name=MODULE, success=False)
        await ctx.send(_error_text(e, cfg), ephemeral=True)
        return
    if result is None:
        await ctx.send(cfg["unsupported"], ephemeral=True)
        return

    translated, shown = result
    msg = cfg["format"].format(flag=shown.flag, language=shown.label, text=translated)
    await ctx.send(msg[:2000], allowed_mentions=discord.AllowedMentions.none())


async def _configure_channel(ctx, translator, settings, target_key, source, cfg):
    if target_key == "off":
        settings.set(ctx.channel.id, "off")
        await ctx.send(cfg["channel-off"])
        return

    target = LANGUAGES[target_key]
    settings.set(ctx.channel.id, encode_setting(source.key if source else None, target_key))
    if source is not None:
        msg = _msg(cfg, "channel-set-pair", source=source.label, source_flag=source.flag,
                   language=target.label, flag=target.flag)
    elif target.key == ENGLISH.key:
        msg = _msg(cfg, "channel-set-english", language=target.label, flag=target.flag)
    else:
        msg = _msg(cfg, "channel-set", language=target.label, flag=target.flag)
    if not translator.configured:
        msg += "\n" + cfg["not-configured"]
    await ctx.send(msg)


# Auto-translate: posts "<username> : <translation>" for normal messages
# in channels that have a language configured
async def auto_translate(
    message: discord.Message,
    translator: Translator,
    settings: ChannelSettings,
    prefix: str,
    cfg: dict,
):
    if message.author.bot or message.guild is None:
        return
    conf = settings.get(message.channel.id)
    if conf is None:
        return
    if message.content.startswith(prefix):
        return  # let command handling deal with it

    text = clean(message.content)
    if not text:
        return

    try:
        result = await translate_for(translator, text, conf.target, conf.source)
    except SameLanguage:
        return
    except TranslationError as e:
        log(f"Auto-translate failed: {e}", module_name=MODULE, success=False)
        return
    if result is None:
        return

    translated, target = result
    if translated.strip().lower() == text.lower():
        return

    msg = cfg["format"].format(
        username=discord.utils.escape_markdown(message.author.display_name),
        text=translated,
        flag=target.flag,
        language=target.label,
    )
    try:
        await message.channel.send(
            msg[:2000], allowed_mentions=discord.AllowedMentions.none()
        )
    except discord.HTTPException as e:
        log(f"Could not post translation: {e}", module_name=MODULE, success=False)
