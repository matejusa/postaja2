"""Preprost predpomnilnik v pomnilniku s časom veljavnosti, skupen vsem obiskovalcem."""
import time

_store: dict[tuple, tuple[float, object]] = {}


async def cached(key: tuple, ttl: int, fetch):
    hit = _store.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    value = await fetch()
    if len(_store) > 2000:
        _store.clear()
    _store[key] = (time.monotonic(), value)
    return value
