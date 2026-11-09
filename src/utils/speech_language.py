"""Cheap check for whether a chat message needs translating to English before it is read aloud.

DeepL charges per character, so obviously-English messages are skipped without a call. This is only
a quota saver: a wrong guess just means one extra DeepL call (English comes back unchanged) or a
message read in its original language, as before.
"""
import re

# Words that are clearly English and not common in other major languages
ENGLISH_HINTS = frozenset(
    "the and is are were you your to of that this with for have has it its i im my what just but not be "
    "can does did so she they if how why when who yes ok okay lol hi hello hey thanks thank please good "
    "like get got go dont cant up out all there here now one wanna gonna gg wp".split()
)
WORD = re.compile(r"[a-z']+")


def looks_english(text: str) -> bool:
    words = WORD.findall(text.lower())
    if not words:
        return False
    hits = sum(w.replace("'", "") in ENGLISH_HINTS or w in ENGLISH_HINTS for w in words)
    return hits / len(words) >= 0.3


def needs_translation(text: str) -> bool:
    """True if the text might not be English and is worth sending to DeepL."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 2:
        return False
    if any(ord(c) > 127 for c in letters):
        return True  # accents, CJK, Cyrillic, ...
    return not looks_english(text)
