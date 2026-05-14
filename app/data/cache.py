"""Tiny in-process TTL cache used by the news/regime/chain loaders."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}


def cache_key(*parts: Any) -> str:
    return "|".join(str(p) for p in parts)


def cached_call(key: str, *, ttl_seconds: int, loader: Callable[[], Any], fresh: bool = False) -> Any:
    now = time.time()
    if not fresh:
        with _lock:
            hit = _store.get(key)
        if hit is not None:
            expires_at, value = hit
            if expires_at > now:
                return value
    value = loader()
    with _lock:
        _store[key] = (now + ttl_seconds, value)
    return value


def reset_cache() -> None:
    with _lock:
        _store.clear()
