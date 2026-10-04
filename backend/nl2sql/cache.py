"""Reuse a recent answer to the same question, instead of asking the model again.

A model answer takes 20 to 80 seconds; the same question asked again a
minute later (an FAQ click, a demo, a teammate checking) has the same
answer, because the data only changes when someone runs a db/ script.
So successful answers are kept for a few minutes, keyed by the question
and everything that changes how it is answered.

Only successes are kept: a refusal or a failed query may succeed on the
next try, and an outage must never be replayed. Entries live in this
process's memory, so a restart empties the cache.
"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

from nl2sql.pipeline import Answer

# Oldest entries are dropped beyond this; answers are small, but rows can
# be up to 1,000 each.
MAX_ENTRIES = 256


def cache_key(question: str, *parts: object) -> str:
    """The same question in any case or spacing, with trailing punctuation
    ignored, plus whatever else decides the answer (model, retrieval)."""
    normalized = re.sub(r"\s+", " ", question).strip().rstrip("?.! ").casefold()
    return "\x1f".join([normalized, *map(str, parts)])


class AnswerCache:
    """A small time-limited cache of successful answers. Thread-safe,
    because FastAPI runs each question in a worker thread."""

    def __init__(
        self,
        ttl_seconds: int,
        max_entries: int = MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, Answer]] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.ttl_seconds > 0

    def get(self, key: str) -> Answer | None:
        if not self.enabled:
            return None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, answer = entry
            if self._clock() - stored_at > self.ttl_seconds:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return answer

    def put(self, key: str, answer: Answer) -> None:
        if not self.enabled or answer.error is not None:
            return
        with self._lock:
            self._entries[key] = (self._clock(), answer)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
