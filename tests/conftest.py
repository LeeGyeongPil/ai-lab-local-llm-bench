"""Pin the screen language so the host locale never changes test results."""
import pytest


@pytest.fixture(autouse=True)
def _pin_language(monkeypatch):
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLMBENCH_LANG", "ko")  # existing assertions are Korean
