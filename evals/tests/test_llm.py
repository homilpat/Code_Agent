import pytest

from evals.runner.llm import ChatClient


@pytest.mark.parametrize(
    "url",
    ["http://localhost:1234/v1", "http://127.0.0.1:1234/v1", "http://[::1]:1234/v1"],
)
def test_local_benchmark_endpoints_are_allowed(url):
    assert ChatClient(url, "test-model").base_url == url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/v1",
        "http://example.com/v1",
        "file:///etc/passwd",
        "http://localhost.evil.example:1234/v1",
        "http://user:password@localhost:1234/v1",
        "http://localhost:1234/v1?token=value",
    ],
)
def test_remote_or_ambiguous_benchmark_endpoints_are_rejected(url):
    with pytest.raises(ValueError):
        ChatClient(url, "test-model")
