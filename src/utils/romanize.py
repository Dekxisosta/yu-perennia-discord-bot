"""Turn non-Latin text (Japanese, Cyrillic, Korean, ...) into Latin letters a voice can pronounce.

Without this the English voices read each foreign character as "Japanese letter". Japanese uses
pykakasi (proper readings for kanji); other scripts use anyascii. If a library isn't installed the
foreign characters are simply dropped instead.
"""
import re
import unicodedata

from utils.console_logger import log

MODULE = "ROMANIZE"

JAPANESE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f\u3400-\u4dbf\u4e00-\u9fff]")
# CJK punctuation -> what the splicer and the voice understand
PUNCTUATION = str.maketrans({"。": ". ", "、": ", ", "！": "! ", "？": "? ", "：": ": ", "；": "; ",
                             "「": '"', "」": '"', "『": '"', "』": '"', "（": "(", "）": ")", "〜": "~"})

_kakasi = None  # the pykakasi converter, or False once we know it is missing
_warned: set[str] = set()


def _warn_once(key: str, message: str) -> None:
    if key not in _warned:
        _warned.add(key)
        log(message, module_name=MODULE, success=False)


# ---- built-in kana -> Hepburn, so hiragana/katakana names are read even without any library.
_KANA = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "ゐ": "i", "ゑ": "e", "を": "o", "ん": "n",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ゔ": "vu", "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
}
_KANA_COMBO = {  # syllable + small ゃゅょ/ぁぃぅぇぉ
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo", "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho", "じゃ": "ja", "じゅ": "ju", "じょ": "jo",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho", "ぢゃ": "ja", "ぢゅ": "ju", "ぢょ": "jo",
    "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo", "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "びゃ": "bya", "びゅ": "byu", "びょ": "byo", "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo", "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    "ふぁ": "fa", "ふぃ": "fi", "ふぇ": "fe", "ふぉ": "fo", "ゔぁ": "va", "ゔぃ": "vi", "ゔぇ": "ve", "ゔぉ": "vo",
    "てぃ": "ti", "でぃ": "di", "とぅ": "tu", "どぅ": "du", "うぃ": "wi", "うぇ": "we", "うぉ": "wo",
    "しぇ": "she", "じぇ": "je", "ちぇ": "che", "つぁ": "tsa", "つぃ": "tsi", "つぇ": "tse", "つぉ": "tso",
}


def _kana(run: str) -> str | None:
    """Hiragana/katakana (with ッ, ー, small kana) to Hepburn. None if the run has anything else (kanji)."""
    # katakana -> hiragana (ァ..ヶ are exactly 0x60 above ぁ..ゖ); ー and ・ stay
    text = "".join(chr(ord(c) - 0x60) if "\u30a1" <= c <= "\u30f6" else c for c in run)
    out: list[str] = []
    double = False  # a small っ doubles the next consonant
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "っ":
            double = True
            i += 1
            continue
        if ch == "ー":
            vowel = next((c for c in reversed("".join(out)) if c in "aiueo"), "")
            out.append(vowel)
            i += 1
            continue
        if ch in "・ 　":
            out.append(" ")
            i += 1
            continue
        syllable = _KANA_COMBO.get(text[i:i + 2])
        step = 2
        if syllable is None:
            syllable, step = _KANA.get(ch), 1
        if syllable is None:
            return None
        if double:
            syllable = ("t" if syllable.startswith("ch") else syllable[0]) + syllable
            double = False
        out.append(syllable)
        i += step
    return "".join(out)


def _is_foreign(ch: str) -> bool:
    return ch.isalpha() and not unicodedata.name(ch, "").startswith("LATIN")


def has_non_latin(text: str) -> bool:
    return any(_is_foreign(ch) for ch in text)


def _japanese(run: str) -> str | None:
    global _kakasi
    if _kakasi is None:
        try:
            import pykakasi

            _kakasi = pykakasi.kakasi()
        except Exception as e:
            _kakasi = False
            _warn_once("pykakasi", f"pykakasi is not usable ({type(e).__name__}: {e}); kanji can't be romanized. "
                                   "Install it with: pip install pykakasi")
    if not _kakasi:
        return None
    try:
        return " ".join(part["hepburn"] for part in _kakasi.convert(run) if part.get("hepburn"))
    except Exception:
        return None


def _generic(run: str) -> str:
    try:
        from anyascii import anyascii

        return anyascii(run)
    except Exception as e:
        _warn_once("anyascii", f"anyascii is not usable ({type(e).__name__}: {e}); non-Japanese scripts can't be "
                               "romanized. Install it with: pip install anyascii")
        return ""


def _romanize_run(run: str) -> str:
    if JAPANESE.search(run):
        converted = _japanese(run)
        if converted is not None:
            return converted
        converted = _kana(run)  # no pykakasi: kana-only runs still work
        if converted is not None:
            return converted
    return _generic(run)


def romanize(text: str) -> str:
    """Replace every run of non-Latin letters with its Latin spelling. Latin text is untouched."""
    text = text.translate(PUNCTUATION)
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            out.append(" " + _romanize_run("".join(run)) + " ")
            run.clear()

    for ch in text:
        if _is_foreign(ch):
            run.append(ch)
        else:
            flush()
            out.append(ch)
    flush()
    joined = re.sub(r"\s+", " ", "".join(out))
    return re.sub(r"\s+([.,!?;:)])", r"\1", joined).strip()  # no gap before punctuation
