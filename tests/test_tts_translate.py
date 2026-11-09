import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from services.commands import tts_service as ts  # noqa: E402
from utils.speech_language import needs_translation  # noqa: E402


@pytest.mark.parametrize("text", ["hello everyone how are you", "i think the movie is good", "lol", "gg wp", "😂", "123", "dont worry about it"])
def test_english_and_symbols_skip_deepl(text):
    assert not needs_translation(text)


@pytest.mark.parametrize("text", ["hola como estas", "kumusta ka na", "こんにちは", "привет", "café"])
def test_other_languages_go_to_deepl(text):
    assert needs_translation(text)


class FakeTranslator:
    configured = True

    def __init__(self, text="Hello, how are you?", source="ES", error=None, delay=0):
        self.text, self.source, self.error, self.delay, self.calls = text, source, error, delay, []

    async def translate(self, text, target):
        self.calls.append((text, target))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return type("R", (), {"text": self.text, "source": self.source})()


def manager(tr, settings=None):
    return ts.TTSManager(None, lambda: {"settings": settings or {}}, None, None, tr)


def item(body, lead=""):
    return ts.QueueItem(lead + body, "v", lead)


@pytest.mark.asyncio
async def test_translates_body_but_not_the_speaker_lead():
    m = manager(FakeTranslator())
    out = await m._maybe_translate(item("hola, como estas?", "Nel says. "))
    assert out.text == "Nel says. Hello, how are you?"
    assert m.translator.calls == [("hola, como estas?", "EN-US")]


@pytest.mark.asyncio
async def test_english_detected_by_deepl_is_left_alone():
    m = manager(FakeTranslator(source="EN", text="changed"))
    assert (await m._maybe_translate(item("cafe time"))).text == "cafe time"


@pytest.mark.asyncio
async def test_obvious_english_never_calls_deepl():
    m = manager(FakeTranslator())
    await m._maybe_translate(item("hello how are you"))
    assert m.translator.calls == []


@pytest.mark.asyncio
async def test_disabled_or_missing_translator_reads_original():
    assert (await manager(None)._maybe_translate(item("hola amigo"))).text == "hola amigo"
    m = manager(FakeTranslator(), {"translate": False})
    assert (await m._maybe_translate(item("hola amigo"))).text == "hola amigo"


@pytest.mark.asyncio
async def test_timeout_reads_original():
    m = manager(FakeTranslator(delay=5), {"translate-timeout": 0.1})
    assert (await m._maybe_translate(item("hola amigo"))).text == "hola amigo"


@pytest.mark.asyncio
async def test_quota_error_pauses_translation():
    err = Exception("quota")
    err.kind = "quota"
    m = manager(FakeTranslator(error=err))
    await m._maybe_translate(item("hola amigo"))
    await m._maybe_translate(item("hola otra vez"))
    assert len(m.translator.calls) == 1


# ---------------------------------------------------------------- per-server translate settings
from services.commands import translate_service as tsvc  # noqa: E402
from services.commands.server_settings_service import ServerSettings  # noqa: E402


def server_manager(tmp_path, deepl=None, google=None, **conf):
    settings = ServerSettings(tmp_path / "s.json")
    if conf:
        settings.set(1, **conf)
    return ts.TTSManager(None, lambda: {"settings": {}}, settings, None, deepl, google)


@pytest.mark.asyncio
async def test_server_picks_the_translation_api(tmp_path):
    deepl, google = FakeTranslator(text="from deepl"), FakeTranslator(text="from google")
    m = server_manager(tmp_path, deepl, google)
    assert (await m._maybe_translate(item("hola amigo"), 1)).text == "from deepl"  # default
    m.server_settings.set(1, translate_api="google")
    assert (await m._maybe_translate(item("hola amigo"), 1)).text == "from google"
    assert len(deepl.calls) == 1 and len(google.calls) == 1


@pytest.mark.asyncio
async def test_vctranslatetoggle_off_reads_original(tmp_path):
    deepl = FakeTranslator()
    m = server_manager(tmp_path, deepl, None, vc_translate=False)
    assert (await m._maybe_translate(item("hola amigo"), 1)).text == "hola amigo"
    assert deepl.calls == []


@pytest.mark.asyncio
async def test_unconfigured_google_reads_original_and_pause_is_per_api(tmp_path):
    google = tsvc.GoogleTranslator(api_key="")
    deepl = FakeTranslator(text="from deepl")
    m = server_manager(tmp_path, deepl, google, translate_api="google")
    assert (await m._maybe_translate(item("hola amigo"), 1)).text == "hola amigo"

    err = Exception("quota")
    err.kind = "quota"
    broken = FakeTranslator(error=err)
    m2 = server_manager(tmp_path, deepl, broken, translate_api="google")
    await m2._maybe_translate(item("hola amigo"), 1)
    await m2._maybe_translate(item("hola otra vez"), 1)
    assert len(broken.calls) == 1  # google paused...
    m2.server_settings.set(1, translate_api="deepl")
    assert (await m2._maybe_translate(item("hola amigo"), 1)).text == "from deepl"  # ...deepl unaffected


class _FakeResponse:
    def __init__(self, status, payload):
        self.status, self._payload = status, payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return str(self._payload)


class _FakeSession:
    closed = False

    def __init__(self, response):
        self.response, self.sent = response, None

    def post(self, url, **kwargs):
        self.sent = (url, kwargs)
        return self.response


@pytest.mark.asyncio
async def test_google_translator_request_and_response():
    g = tsvc.GoogleTranslator(api_key="k")
    session = _FakeSession(_FakeResponse(200, {"data": {"translations": [
        {"translatedText": "Hello, how are you?", "detectedSourceLanguage": "es"}]}}))
    g._session = session
    result = await g.translate("hola, como estas?", "EN-US")
    assert (result.text, result.source) == ("Hello, how are you?", "ES")
    url, kw = session.sent
    assert url == tsvc.GoogleTranslator.URL and kw["params"] == {"key": "k"}
    assert kw["json"] == {"q": "hola, como estas?", "target": "en", "format": "text"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status, body, kind", [
    (429, {}, "rate_limit"), (403, {"error": {"errors": [{"reason": "dailyLimitExceeded"}]}}, "quota"),
    (400, {"error": {"message": "API key not valid"}}, "auth"), (500, {}, "failed"),
])
async def test_google_translator_errors(status, body, kind):
    g = tsvc.GoogleTranslator(api_key="k")
    g._session = _FakeSession(_FakeResponse(status, body))
    with pytest.raises(tsvc.TranslationError) as e:
        await g.translate("hola", "EN-US")
    assert e.value.kind == kind


@pytest.mark.asyncio
async def test_google_translator_without_key_is_not_configured():
    with pytest.raises(tsvc.TranslationError) as e:
        await tsvc.GoogleTranslator(api_key="").translate("hola", "EN-US")
    assert e.value.kind == "not_configured"
