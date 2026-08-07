"""Small process-local cache for frequently clicked word definitions."""

from collections import OrderedDict
from threading import RLock
from time import monotonic


MAX_ENTRIES = 4096
TTL_SECONDS = 60 * 60
_cache = OrderedDict()
_lock = RLock()


def get(word):
    key = str(word or "").strip().lower()
    if not key:
        return None
    now = monotonic()
    with _lock:
        item = _cache.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at <= now:
            _cache.pop(key, None)
            return None
        _cache.move_to_end(key)
        return dict(value)


def set_value(entry):
    if not entry or not entry.get("word"):
        return
    key = str(entry["word"]).strip().lower()
    value = dict(entry)
    value["word"] = key
    with _lock:
        _cache[key] = (monotonic() + TTL_SECONDS, value)
        _cache.move_to_end(key)
        while len(_cache) > MAX_ENTRIES:
            _cache.popitem(last=False)


def prime(entries):
    for entry in entries or []:
        set_value(entry)


def clear():
    with _lock:
        _cache.clear()
