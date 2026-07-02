from unittest.mock import patch, MagicMock

from requests.exceptions import ConnectionError

from src.llm_provider import LLMProvider, detect_ollama_url


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


class TestOllamaUrlAutoDetect:
    def test_ollama_without_explicit_base_url_calls_detect(self):
        with patch("src.llm_provider.detect_ollama_url", return_value="http://localhost:11435/v1") as detect, \
             patch.object(LLMProvider, "list_models", return_value=["llama3.1:8b"]):
            llm = LLMProvider("ollama", model="llama3.1:8b")
        detect.assert_called_once()
        assert llm.base_url == "http://localhost:11435/v1"

    def test_ollama_detect_failure_falls_back_to_static_default(self):
        with patch("src.llm_provider.detect_ollama_url", return_value=None) as detect, \
             patch.object(LLMProvider, "list_models", return_value=["llama3.1:8b"]):
            llm = LLMProvider("ollama", model="llama3.1:8b")
        detect.assert_called_once()
        assert llm.base_url == "http://localhost:11434/v1"

    def test_explicit_base_url_wins_and_skips_detection(self):
        with patch("src.llm_provider.detect_ollama_url") as detect, \
             patch.object(LLMProvider, "list_models", return_value=["llama3.1:8b"]):
            llm = LLMProvider("ollama", model="llama3.1:8b", base_url="http://localhost:11436/v1")
        detect.assert_not_called()
        assert llm.base_url == "http://localhost:11436/v1"

    def test_non_ollama_provider_never_calls_detect(self):
        with patch("src.llm_provider.detect_ollama_url") as detect:
            LLMProvider("groq", api_key="k")
        detect.assert_not_called()


class TestOllamaModelFallback:
    def test_empty_model_picks_first_installed(self):
        with patch("src.llm_provider.detect_ollama_url", return_value="http://localhost:11435/v1"), \
             patch.object(LLMProvider, "list_models", return_value=["qwen3-coder:30b-a3b-q4_K_M", "gemma4"]):
            llm = LLMProvider("ollama")
        assert llm.model == "qwen3-coder:30b-a3b-q4_K_M"

    def test_empty_model_and_no_installed_models_falls_back_to_static_default(self):
        with patch("src.llm_provider.detect_ollama_url", return_value="http://localhost:11435/v1"), \
             patch.object(LLMProvider, "list_models", return_value=[]):
            llm = LLMProvider("ollama")
        assert llm.model == "llama3.1:8b"

    def test_explicit_model_skips_list_models(self):
        with patch("src.llm_provider.detect_ollama_url", return_value="http://localhost:11435/v1"), \
             patch.object(LLMProvider, "list_models") as list_models:
            llm = LLMProvider("ollama", model="gemma4")
        list_models.assert_not_called()
        assert llm.model == "gemma4"

    def test_non_ollama_provider_never_calls_list_models_in_init(self):
        with patch.object(LLMProvider, "list_models") as list_models:
            LLMProvider("groq", api_key="k")
        list_models.assert_not_called()

    def test_detect_failure_skips_model_probe(self):
        # If the port probe already said Ollama is down, asking it for
        # installed models is pointless network I/O on the UI thread.
        with patch("src.llm_provider.detect_ollama_url", return_value=None), \
             patch.object(LLMProvider, "list_models") as list_models:
            llm = LLMProvider("ollama")
        list_models.assert_not_called()
        assert llm.model == "llama3.1:8b"

    def test_construction_survives_ollama_down(self):
        # detect_ollama_url returns None (nothing listening) and
        # list_models's real implementation swallows connection errors,
        # returning the static default -- construction must not raise.
        with patch("src.llm_provider.detect_ollama_url", return_value=None), \
             patch("src.llm_provider.requests.get", side_effect=ConnectionError("refused")):
            llm = LLMProvider("ollama")
        assert llm.model == "llama3.1:8b"
        assert llm.base_url == "http://localhost:11434/v1"


class TestDetectOllamaUrlProbe:
    """The probe must be fast enough to run on the UI thread: 127.0.0.1
    (localhost resolves to ::1 first on Windows, doubling every timeout)
    and a sub-second timeout per port."""

    def test_probes_127_0_0_1_with_short_timeout(self):
        recorded = []

        class FakeResp:
            status_code = 200

        def fake_get(url, timeout=None):
            recorded.append((url, timeout))
            return FakeResp()

        with patch("src.llm_provider.requests.get", side_effect=fake_get):
            url = detect_ollama_url()

        assert url == "http://127.0.0.1:11434/v1"
        probe_url, timeout = recorded[0]
        assert probe_url.startswith("http://127.0.0.1:")
        assert timeout is not None and timeout <= 0.5

    def test_unreachable_ports_return_none(self):
        def fake_get(url, timeout=None):
            raise OSError("connection refused")

        with patch("src.llm_provider.requests.get", side_effect=fake_get):
            assert detect_ollama_url() is None
