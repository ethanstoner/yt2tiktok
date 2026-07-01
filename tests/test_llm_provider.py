from unittest.mock import patch, MagicMock

from src.llm_provider import LLMProvider


def _fake_response():
    r = MagicMock()
    r.ok = True
    r.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
    return r


class TestCompleteTimeout:
    def test_default_timeout_is_30(self):
        llm = LLMProvider("groq", api_key="k")
        with patch("src.llm_provider.requests.post", return_value=_fake_response()) as post:
            llm.complete("prompt")
        assert post.call_args.kwargs["timeout"] == 30

    def test_custom_timeout_passed_through(self):
        llm = LLMProvider("groq", api_key="k")
        with patch("src.llm_provider.requests.post", return_value=_fake_response()) as post:
            llm.complete("prompt", timeout=90)
        assert post.call_args.kwargs["timeout"] == 90

    def test_anthropic_custom_timeout(self):
        r = MagicMock()
        r.ok = True
        r.json.return_value = {"content": [{"text": "hi"}]}
        llm = LLMProvider("claude", api_key="k")
        with patch("src.llm_provider.requests.post", return_value=r) as post:
            llm.complete("prompt", timeout=90)
        assert post.call_args.kwargs["timeout"] == 90
