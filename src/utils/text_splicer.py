"""Chop text into speakable chunks along its punctuation.

Sentences are kept whole where possible. A sentence that is too long is cut at clause punctuation
(commas, semicolons, dashes), then at a space, and only as a last resort in the middle of a word.
Short neighbours are packed together so the voice doesn't speak in tiny fragments. The first chunk
gets a smaller limit so speech starts quickly.
"""

SENTENCE_END = ".!?…。！？\n"
CLAUSE_END = ",;:—–、，；："
CLOSERS = "\"')]}»”’"
ASCII_ENDINGS = ".!?,;:"  # these only count when followed by whitespace ("3.5" and "a.b" stay whole)
# A period after these doesn't end a sentence
ABBREVIATIONS = frozenset({"mr", "mrs", "ms", "dr", "prof", "vs", "st", "jr", "sr", "e.g", "i.e", "approx", "no"})


def _is_abbreviation(text: str, dot_index: int) -> bool:
    start = dot_index
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    return text[start:dot_index].lower().strip("(\"'") in ABBREVIATIONS


def split_units(text: str, ends: str) -> list[str]:
    """Split after each punctuation run in `ends` (plus any closing quotes). Pieces keep their
    punctuation and are stripped of surrounding whitespace."""
    units: list[str] = []
    start = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch not in ends:
            i += 1
            continue
        j = i
        while j < n and text[j] in ends:
            j += 1
        while j < n and text[j] in CLOSERS:
            j += 1
        at_end = j >= n or text[j].isspace()
        boundary = at_end if ch in ASCII_ENDINGS else True
        if ch == "\n":
            boundary = True
        if boundary and ch == "." and _is_abbreviation(text, i):
            boundary = False
        if boundary:
            piece = text[start:j].strip()
            if piece:
                units.append(piece)
            start = j
        i = j
    tail = text[start:].strip()
    if tail:
        units.append(tail)
    return units


def _wrap(text: str, limit: int) -> list[str]:
    """Cut at spaces, or mid-word if there are none (e.g. Japanese without spaces)."""
    out = []
    while len(text) > limit:
        cut = text.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        out.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        out.append(text)
    return out


def _fit(sentence: str, limit: int) -> list[str]:
    """Break one sentence into pieces no longer than `limit`."""
    if len(sentence) <= limit:
        return [sentence]
    pieces: list[str] = []
    current = ""
    for clause in split_units(sentence, CLAUSE_END):
        for part in _wrap(clause, limit):
            if current and len(current) + 1 + len(part) > limit:
                pieces.append(current)
                current = part
            else:
                current = f"{current} {part}".strip()
    if current:
        pieces.append(current)
    return pieces


def splice(text: str, max_len: int = 120, first_len: int | None = None) -> list[str]:
    """Chunks of at most `max_len` characters (`first_len` for the first one), in order."""
    max_len = max(10, max_len)
    first_len = min(first_len, max_len) if first_len else max_len
    units: list[str] = []
    for sentence in split_units(text, SENTENCE_END):
        units.extend(_fit(sentence, max_len))

    chunks: list[str] = []
    current = ""
    for unit in units:
        limit = first_len if not chunks else max_len
        if current and len(current) + 1 + len(unit) > limit:
            chunks.append(current)
            current = unit
        else:
            current = f"{current} {unit}".strip()
    if current:
        chunks.append(current)
    return chunks
