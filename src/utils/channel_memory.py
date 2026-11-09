import time
from collections import OrderedDict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Turn:
    role: str  # "user" (someone in the channel) or "model" (Yu)
    name: str  # display name shown to Gemini
    text: str
    at: float  # clock() time the turn was stored


class ChannelMemory:
    """Short-term, in-RAM conversation memory, one rolling window per channel id.

    Only the last `max_turns` turns, no older than `max_age` seconds, are ever returned, and each turn is cut to
    `max_chars`. Nothing is written to disk or Supabase, so a restart (or /vcchatmodetoggle) forgets everything.
    The number of remembered channels is capped as well, so memory use stays bounded.
    """

    def __init__(
        self,
        max_turns: int = 12,
        max_age: float = 1800,
        max_chars: int = 300,
        max_channels: int = 200,
        clock=time.monotonic,
    ):
        self.max_turns = max_turns
        self.max_age = max_age
        self.max_chars = max_chars
        self.max_channels = max_channels
        self._clock = clock
        self._channels: OrderedDict[int, deque[Turn]] = OrderedDict()

    def configure(self, max_turns: int | None = None, max_age: float | None = None, max_chars: int | None = None) -> None:
        """Apply (reloaded) config. Shrinking max_turns trims on the next read."""
        if max_turns is not None:
            self.max_turns = max(1, int(max_turns))
        if max_age is not None:
            self.max_age = max(1.0, float(max_age))
        if max_chars is not None:
            self.max_chars = max(20, int(max_chars))

    def _cut(self, text: str) -> str:
        text = " ".join(text.split())
        if len(text) <= self.max_chars:
            return text
        return text[: self.max_chars - 1].rstrip() + "…"

    def add(self, channel_id: int, role: str, name: str, text: str) -> Turn | None:
        """Remember one turn. Blank text is ignored."""
        text = self._cut(text)
        if not text:
            return None
        turn = Turn(role=role, name=name, text=text, at=self._clock())
        turns = self._channels.get(channel_id)
        if turns is None:
            turns = self._channels[channel_id] = deque()
            while len(self._channels) > self.max_channels:
                self._channels.popitem(last=False)  # forget the channel that was used longest ago
        self._channels.move_to_end(channel_id)
        turns.append(turn)
        self._trim(turns)
        return turn

    def _trim(self, turns: "deque[Turn]") -> None:
        cutoff = self._clock() - self.max_age
        while turns and turns[0].at < cutoff:
            turns.popleft()
        while len(turns) > self.max_turns:
            turns.popleft()

    def recent(self, channel_id: int) -> list[Turn]:
        """This channel's remembered turns, oldest first."""
        turns = self._channels.get(channel_id)
        if not turns:
            return []
        self._trim(turns)
        if not turns:
            del self._channels[channel_id]
            return []
        return list(turns)

    def clear(self, channel_id: int) -> None:
        self._channels.pop(channel_id, None)
