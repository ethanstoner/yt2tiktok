import requests

PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "format": "openai",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "format": "openai",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.0-flash",
        "format": "openai",
    },
    "claude": {
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-sonnet-4-latest",
        "format": "anthropic",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3.1:8b",
        "format": "openai",
    },
}


def detect_ollama_url() -> str | None:
    """Try common Ollama ports and return the first responding base URL."""
    for port in [11434, 11435, 11436]:
        url = f"http://localhost:{port}"
        try:
            r = requests.get(f"{url}/api/tags", timeout=2)
            if r.status_code == 200:
                return f"{url}/v1"
        except Exception:
            pass
    return None


class LLMProvider:
    def __init__(self, provider: str, api_key: str = "", model: str = "", base_url: str = ""):
        self.provider = provider.lower()
        info = PROVIDERS.get(self.provider, {})
        self.base_url = base_url or info.get("base_url", "")
        self.model = model or info.get("default_model", "")
        self.api_key = api_key
        self.format = info.get("format", "openai")
        if provider.lower() == "custom":
            self.format = "openai"

    def is_available(self) -> bool:
        if self.provider == "ollama":
            try:
                r = requests.get(f"{self.base_url}/models", timeout=3)
                return r.status_code == 200
            except Exception:
                return False
        return bool(self.api_key)

    def list_models(self) -> list[str]:
        try:
            if self.provider == "ollama":
                # Ollama native API for local models
                base = self.base_url.replace("/v1", "")
                r = requests.get(f"{base}/api/tags", timeout=5)
                r.raise_for_status()
                return [m["name"] for m in r.json().get("models", [])]
            elif self.provider == "claude":
                # Anthropic doesn't have a public models list endpoint
                return [
                    "claude-sonnet-4-latest",
                    "claude-haiku-4-latest",
                    "claude-opus-4-latest",
                ]
            elif self.format == "openai":
                headers = {"Content-Type": "application/json"}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                r = requests.get(
                    f"{self.base_url}/models",
                    headers=headers,
                    timeout=10,
                )
                r.raise_for_status()
                models = r.json().get("data", [])
                names = sorted(m["id"] for m in models if isinstance(m, dict) and "id" in m)
                return names
        except Exception:
            pass
        # Fallback: return default model
        info = PROVIDERS.get(self.provider, {})
        default = info.get("default_model", "")
        return [default] if default else []

    def complete(self, prompt: str, max_tokens: int = 256) -> str:
        if self.format == "anthropic":
            return self._complete_anthropic(prompt, max_tokens)
        return self._complete_openai(prompt, max_tokens)

    def _complete_openai(self, prompt: str, max_tokens: int) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
        r = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    def _complete_anthropic(self, prompt: str, max_tokens: int) -> str:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }
        r = requests.post(
            f"{self.base_url}/messages",
            headers=headers,
            json=payload,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()
