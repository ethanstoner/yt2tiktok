import json
import pytest
from pathlib import Path
from src import config as cfg


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    config_dir = tmp_path / ".yt2tiktok"
    config_file = config_dir / "config.json"
    monkeypatch.setattr(cfg, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg, "_CONFIG_PATH", config_file)
    return config_file


class TestConfig:
    def test_defaults(self, temp_config):
        config = cfg.load_config()
        assert config["llm_enabled"] is False
        assert config["preset"] == "Opus Clean"

    def test_save_and_load(self, temp_config):
        cfg.save_config({"llm_provider": "openai"})
        assert cfg.get("llm_provider") == "openai"

    def test_set_and_get(self, temp_config):
        cfg.set("mode", "Black Bars")
        assert cfg.get("mode") == "Black Bars"

    def test_reset_to_defaults(self, temp_config):
        cfg.set("mode", "Black Bars")
        cfg.reset_to_defaults()
        assert cfg.get("mode") == "Blurred"

    def test_export_import(self, temp_config, tmp_path):
        cfg.set("llm_provider", "claude")
        export_path = str(tmp_path / "export.json")
        cfg.export_config(export_path)
        cfg.reset_to_defaults()
        assert cfg.get("llm_provider") == "groq"
        cfg.import_config(export_path)
        assert cfg.get("llm_provider") == "claude"

    def test_get_with_default(self, temp_config):
        assert cfg.get("nonexistent", "fallback") == "fallback"
