import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import aiohttp
import discord
from discord.ext import commands
from dotenv import load_dotenv

from utils.console_logger import log

load_dotenv()

MODULE = "TRANSLATE"

HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
KANA = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")
LATIN = re.compile(r"[A-Za-z\u00c0-\u024f]")


# ---------------------------------------------------------------- languages
@dataclass(frozen=True)
class Language:
    key: str    # internal key, also what is stored in the channel config
    label: str  # shown to users
    deepl: str  # DeepL target_lang code
    flag: str


ENGLISH = Language("en", "English", "EN-US", "🇺🇸")

# English is always the other side of the pair
LANGUAGES: dict[str, Language] = {
    "zh": Language("zh", "Chinese", "ZH-HANS", "🇨🇳"),
    "ja": Language("ja", "Japanese", "JA", "🇯🇵"),
}

ALIASES = {
    "zh": "zh", "cn": "zh", "chinese": "zh", "中文": "zh",
    "ja": "ja", "jp": "ja", "japanese": "ja", "日本語": "ja",
    "off": "off", "none": "off", "disable": "off", "stop": "off",
}


def resolve_language(value: str | None) -> str | None:
    """Returns 'zh' | 'ja' | 'off', or None if unknown."""
    return ALIASES.get((value or "").strip().lower())


# ------------------------------------------------------------------ DeepL
class TranslationError(Exception):
    """kind: not_configured | quota | rate_limit | auth | failed"""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(detail or kind)
        self.kind = kind


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

    async def translate(self, text: str, target_code: str) -> str:
        if not self.configured:
            raise TranslationError("not_configured")
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        try:
            async with self._session.post(
                self.url,
                headers={"Authorization": f"DeepL-Auth-Key {self.api_key}"},
                json={"text": [text], "target_lang": target_code},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as res:
                if res.status == 200:
                    return (await res.json())["translations"][0]["text"]
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


# -------------------------------------------------------- per-channel config
class ChannelSettings:
    """channel id -> language key, saved to a JSON file.

    Channels listed in TRANSLATE_CHANNEL_IDS are seeded with a default
    language; anything set with /translate overrides the seed (and 'off'
    disables a seeded channel).
    """

    def __init__(self, path: str | Path, seed_ids: set[int], default_key: str):
        self.path = Path(path)
        self._seed = {cid: default_key for cid in seed_ids}
        self._saved: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            log(f"Could not read {self.path.name}: {e}", module_name=MODULE, success=False)
            return
        self._saved = {
            str(k): v for k, v in data.items() if v in LANGUAGES or v == "off"
        }

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._saved, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            log(f"Could not save {self.path.name}: {e}", module_name=MODULE, success=False)

    def get(self, channel_id: int) -> Language | None:
        key = self._saved.get(str(channel_id), self._seed.get(channel_id))
        return LANGUAGES.get(key) if key else None

    def set(self, channel_id: int, key: str) -> None:
        self._saved[str(channel_id)] = key
        self._save()

    @property
    def active_count(self) -> int:
        ids = set(self._seed) | {int(k) for k in self._saved}
        return sum(1 for cid in ids if self.get(cid) is not None)


# ------------------------------------------------------------- core logic
def clean(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text)    # URLs
    text = re.sub(r"<a?:\w+:\d+>", "", text)    # custom emoji
    text = re.sub(r"<[@#&!]+\d+>", "", text)    # mentions / channels
    text = re.sub(r"```[\s\S]*?```", "", text)  # code blocks
    return text.strip()


def parse_channel_ids(raw: str | None) -> set[int]:
    return {int(c) for c in (raw or "").split(",") if c.strip().isdigit()}


async def translate_for(
    translator: Translator, text: str, lang: Language
) -> tuple[str, Language] | None:
    """Translate between English and `lang`, picking the direction by script.

    Chinese/Japanese characters -> English; Latin letters -> `lang`.
    Returns (text, language_it_was_translated_into), or None if the text has
    nothing translatable (digits, symbols, emoji only).
    """
    native = HAN.search(text) or (lang.key == "ja" and KANA.search(text))
    if native:
        return await translator.translate(text, ENGLISH.deepl), ENGLISH
    if LATIN.search(text):
        return await translator.translate(text, lang.deepl), lang
    return None


def _error_text(err: TranslationError, cfg: dict) -> str:
    key = {
        "not_configured": "not-configured",
        "quota": "quota",
        "rate_limit": "rate-limit",
    }.get(err.kind, "failed")
    return cfg[key]


# /translate <language> [text]
#   no text   -> set this channel's auto-translate language (or 'off')
#   with text -> translate that text once
async def translate_command(
    ctx: commands.Context,
    translator: Translator,
    settings: ChannelSettings,
    language: str,
    text: str | None,
    cfg: dict,
):
    key = resolve_language(language)
    if key is None:
        await ctx.send(cfg["unknown-language"], ephemeral=True)
        return

    text = clean(text or "")
    if not text:
        if ctx.guild is None:
            await ctx.send(cfg["server-only"], ephemeral=True)
            return
        await _configure_channel(ctx, translator, settings, key, cfg)
        return

    if key == "off":
        await ctx.send(cfg["off-with-text"], ephemeral=True)
        return

    await ctx.defer()
    try:
        result = await translate_for(translator, text, LANGUAGES[key])
    except TranslationError as e:
        log(f"Command failed: {e}", module_name=MODULE, success=False)
        await ctx.send(_error_text(e, cfg), ephemeral=True)
        return
    if result is None:
        await ctx.send(cfg["unsupported"], ephemeral=True)
        return

    translated, target = result
    msg = cfg["format"].format(flag=target.flag, language=target.label, text=translated)
    await ctx.send(msg[:2000], allowed_mentions=discord.AllowedMentions.none())


async def _configure_channel(ctx, translator, settings, key, cfg):
    settings.set(ctx.channel.id, key)
    if key == "off":
        await ctx.send(cfg["channel-off"])
        return

    lang = LANGUAGES[key]
    msg = cfg["channel-set"].format(flag=lang.flag, language=lang.label)
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
    lang = settings.get(message.channel.id)
    if lang is None:
        return
    if message.content.startswith(prefix):
        return  # let command handling deal with it

    text = clean(message.content)
    if not text:
        return

    try:
        result = await translate_for(translator, text, lang)
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
