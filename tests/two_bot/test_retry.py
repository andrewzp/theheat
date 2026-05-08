import pytest

from src.two_bot.retry import call_with_retries


def test_call_with_retries_returns_after_transient_exception():
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] == 1:
            raise TimeoutError("slow provider")
        return "ok"

    assert call_with_retries("test", flaky, sleep_seconds=0) == "ok"
    assert calls["count"] == 2


def test_call_with_retries_preserves_final_error():
    def always_boom():
        raise RuntimeError("still down")

    with pytest.raises(RuntimeError, match="still down"):
        call_with_retries("test", always_boom, attempts=2, sleep_seconds=0)
