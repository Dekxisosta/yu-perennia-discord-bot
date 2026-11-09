import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from services.commands import translate_service as ts  # noqa: E402

SUPPORTED = [
    "English", "Spanish", "Mandarin Chinese", "Simplified Chinese", "Traditional Chinese",
    "French", "German", "Arabic", "Hindi", "Japanese", "Russian", "Portuguese",
]

# text -> language DeepL would detect
DETECT = {"hello there": "EN", "hola amigo": "ES", "bonjour tout le monde": "FR", "guten tag": "DE", "olá pessoal": "PT"}


class FakeDeepL:
    """Records calls; 'translates' by tagging the text with the target code."""

    configured = True

    def __init__(self):
        self.calls = []

    async def translate(self, text, target_code, source_code=None):
        self.calls.append((text, target_code, source_code))
        return ts.Translation(f"[{target_code}] {text}", DETECT.get(text, ""))


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- language list
def test_only_the_requested_languages_exist():
    assert [l.label for l in ts.LANGUAGES.values()] == SUPPORTED


@pytest.mark.parametrize("value,key", [
    ("English", "en"), ("en", "en"), ("spanish", "es"), ("Mandarin Chinese", "cmn"), ("mandarin", "cmn"),
    ("Simplified Chinese", "zh"), ("chinese", "zh"), ("Traditional Chinese", "zhhant"), ("zh-hant", "zhhant"),
    ("French", "fr"), ("german", "de"), ("Arabic", "ar"), ("hindi", "hi"), ("japanese", "ja"),
    ("russian", "ru"), ("Portuguese", "pt"), ("pt-br", "pt"),
])
def test_resolve_language(value, key):
    assert ts.resolve_language(value) == key


@pytest.mark.parametrize("value", ["korean", "filipino", "tagalog", "italian", "klingon", "", None])
def test_unsupported_languages_are_rejected(value):
    assert ts.resolve_language(value) is None


def test_off_and_auto():
    assert ts.resolve_language("off") == "off"
    assert ts.resolve_source("auto") == "auto"
    assert ts.resolve_source(None) == "auto"
    assert ts.resolve_source("Japanese") == "ja"
    assert ts.resolve_source("off") is None


def test_autocomplete_offers_auto_for_input_and_off_for_output():
    assert ts.language_options(extra=("Auto-detect", "auto"))[0] == ("Auto-detect", "auto")
    assert ts.language_options()[0] == ("Off", "off")
    assert len(ts.language_options()) == 13


# ---------------------------------------------------------------- saved settings
@pytest.mark.parametrize("saved,source,target", [
    ("fr", None, "fr"),
    ("ja-fr", "ja", "fr"),
    ("zhhant-cmn", "zhhant", "cmn"),
    ("zh-hant", None, "zhhant"),   # saved by an older version
    ("pt-br", None, "pt"),         # saved by an older version
])
def test_decode_setting(saved, source, target):
    conf = ts.decode_setting(saved)
    assert (conf.source.key if conf.source else None) == source
    assert conf.target.key == target


@pytest.mark.parametrize("saved", ["off", "tl", "ko", "ja-ja", "xx-fr", "", None])
def test_decode_setting_unsupported_or_off(saved):
    assert ts.decode_setting(saved) is None


def test_encode_fits_the_database_constraint():
    import re
    for s in ts.LANGUAGES:
        for t in ts.LANGUAGES:
            if s != t:
                assert re.fullmatch(r"[a-zA-Z0-9-]{2,12}", ts.encode_setting(s, t))
                assert ts.decode_setting(ts.encode_setting(s, t)).target.key == t


# ---------------------------------------------------------------- direction logic
L = ts.LANGUAGES


def test_auto_input_translates_to_target():
    d = FakeDeepL()
    text, lang = run(ts.translate_for(d, "hello there", L["fr"]))
    assert (text, lang.key) == ("[FR] hello there", "fr")


def test_auto_input_already_in_target_goes_to_english():
    d = FakeDeepL()
    text, lang = run(ts.translate_for(d, "bonjour tout le monde", L["fr"]))
    assert lang.key == "en" and text.startswith("[EN-US]")


def test_auto_input_own_script_goes_to_english():
    d = FakeDeepL()
    _, lang = run(ts.translate_for(d, "こんにちは", L["ja"]))
    assert lang.key == "en"
    assert len(d.calls) == 1


def test_auto_input_english_target_skips_english_text():
    with pytest.raises(ts.SameLanguage):
        run(ts.translate_for(FakeDeepL(), "hello there", L["en"]))


def test_auto_input_english_target_translates_others():
    _, lang = run(ts.translate_for(FakeDeepL(), "hola amigo", L["en"]))
    assert lang.key == "en"


def test_pair_source_to_target_and_back():
    d = FakeDeepL()
    # Japanese text (own script) -> French
    _, lang = run(ts.translate_for(d, "こんにちは", L["fr"], L["ja"]))
    assert lang.key == "fr"
    # French text (DeepL detects FR) -> Japanese
    _, lang = run(ts.translate_for(d, "bonjour tout le monde", L["fr"], L["ja"]))
    assert lang.key == "ja"
    # something else entirely -> French
    _, lang = run(ts.translate_for(d, "hola amigo", L["fr"], L["ja"]))
    assert lang.key == "fr"


def test_pair_script_languages_need_no_detection():
    d = FakeDeepL()
    _, lang = run(ts.translate_for(d, "привет", L["en"], L["ru"]))
    assert lang.key == "en" and len(d.calls) == 1
    _, lang = run(ts.translate_for(d, "hello there", L["ru"], L["en"]))
    assert lang.key == "ru"


def test_japanese_is_not_mistaken_for_chinese():
    # kana means it is not Chinese, even though it contains Han characters
    _, lang = run(ts.translate_for(FakeDeepL(), "日本語を話します", L["cmn"]))
    assert lang.key == "cmn"


def test_symbols_only_are_ignored():
    assert run(ts.translate_for(FakeDeepL(), "123 !!! 😂", L["fr"])) is None


def test_chinese_variants_convert_one_way():
    d = FakeDeepL()
    _, lang = run(ts.translate_for(d, "你好", L["zhhant"], L["zh"]))
    assert lang.key == "zhhant"
    assert d.calls == [("你好", "ZH-HANT", "ZH")]


# ---------------------------------------------------------------- command + prefix parsing
def test_prefix_from_token():
    assert ts._split_source("from:ja hello", "auto") == ("ja", "hello")
    assert ts._split_source("source=Japanese  hello world", "auto") == ("Japanese", "hello world")
    assert ts._split_source("hello from:ja", "auto") == ("auto", "hello from:ja")
    assert ts._split_source(None, "auto") == ("auto", None)


class Ctx:
    def __init__(self, guild=True):
        self.sent = []
        self.guild = object() if guild else None
        self.channel = type("C", (), {"id": 42})()

    async def send(self, content=None, **kw):
        self.sent.append(content)

    async def defer(self):
        pass


class MemSettings:
    def __init__(self):
        self.saved = {}

    def set(self, channel_id, key):
        self.saved[channel_id] = key


CFG = {
    "format": "{flag} {text}", "server-only": "server only", "off-with-text": "off with text",
    "unsupported": "unsupported", "channel-off": "off", "not-configured": "no key",
    "quota": "q", "rate-limit": "r", "failed": "f",
}


def cmd(language, text=None, source="auto", guild=True):
    ctx, st, d = Ctx(guild), MemSettings(), FakeDeepL()
    run(ts.translate_command(ctx, d, st, language, text, CFG, source))
    return ctx, st, d


def test_channel_setup_auto_is_default():
    ctx, st, _ = cmd("french")
    assert st.saved == {42: "fr"}
    assert "French" in ctx.sent[0] and "English" in ctx.sent[0]


def test_channel_setup_with_source_pair():
    ctx, st, _ = cmd("french", source="Japanese")
    assert st.saved == {42: "ja-fr"}
    assert "Japanese" in ctx.sent[0] and "French" in ctx.sent[0]


def test_channel_setup_english_target():
    ctx, st, _ = cmd("english")
    assert st.saved == {42: "en"}


def test_channel_off():
    _, st, _ = cmd("off")
    assert st.saved == {42: "off"}


def test_one_shot_auto():
    ctx, _, d = cmd("french", "hello there")
    assert ctx.sent == ["🇫🇷 [FR] hello there"]
    assert d.calls[-1][2] is None


def test_one_shot_forced_source():
    ctx, _, d = cmd("french", "hello there", source="japanese")
    assert d.calls == [("hello there", "FR", "JA")]


def test_one_shot_source_from_prefix_token():
    ctx, _, d = cmd("french", "from:ja こんにちは")
    assert d.calls == [("こんにちは", "FR", "JA")]


def test_one_shot_already_english():
    ctx, _, _ = cmd("english", "hello there")
    assert "already" in ctx.sent[0]


def test_same_language_is_rejected():
    ctx, st, _ = cmd("french", source="french")
    assert "different" in ctx.sent[0] and not st.saved


@pytest.mark.parametrize("language,source", [("korean", "auto"), ("french", "korean"), ("filipino", "auto")])
def test_unsupported_language_lists_the_supported_ones(language, source):
    ctx, st, _ = cmd(language, source=source)
    assert "Mandarin Chinese" in ctx.sent[0] and "Portuguese" in ctx.sent[0]
    assert not st.saved


def test_dm_cannot_configure_a_channel():
    ctx, st, _ = cmd("french", guild=False)
    assert ctx.sent == ["server only"] and not st.saved
