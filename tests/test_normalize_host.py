import pytest

from llmbench.client import normalize_host


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("127.0.0.1", "http://127.0.0.1:11434"),
        ("localhost", "http://localhost:11434"),
        ("0.0.0.0", "http://127.0.0.1:11434"),
        ("0.0.0.0:8080", "http://127.0.0.1:8080"),
        ("http://0.0.0.0:11434", "http://127.0.0.1:11434"),
        ("http://example.com", "http://example.com"),
        ("https://example.com", "https://example.com"),
        ("https://example.com/", "https://example.com"),
        ("127.0.0.1:11434", "http://127.0.0.1:11434"),
        ("http://host:1234/", "http://host:1234"),
        ("  localhost:9 ", "http://localhost:9"),
        ("[::1]", "http://[::1]:11434"),
        ("[::1]:8080", "http://[::1]:8080"),
    ],
)
def test_normalize_host(raw, expected):
    assert normalize_host(raw) == expected
