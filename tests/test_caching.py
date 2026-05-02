"""Second poke within window should not re-call the underlying loader."""

from app.data.cache import cache_key, cached_call, reset_cache


def test_loader_called_once_within_ttl():
    reset_cache()
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return [{"ok": True}]

    key = cache_key("news", 24, "test")
    a = cached_call(key, ttl_seconds=60, loader=loader)
    b = cached_call(key, ttl_seconds=60, loader=loader)
    assert a == b
    assert calls["n"] == 1


def test_fresh_bypasses_cache():
    reset_cache()
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return calls["n"]

    key = cache_key("news", 24, "test2")
    cached_call(key, ttl_seconds=60, loader=loader)
    cached_call(key, ttl_seconds=60, loader=loader, fresh=True)
    assert calls["n"] == 2
