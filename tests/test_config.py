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

    def test_get_explicit_none_default(self, temp_config):
        assert cfg.get("nonexistent", None) is None

    def test_save_recovers_from_corrupt_file(self, temp_config):
        temp_config.parent.mkdir(parents=True, exist_ok=True)
        temp_config.write_text("{ this is not json", encoding="utf-8")
        cfg.set("mode", "Black Bars")
        assert cfg.get("mode") == "Black Bars"

    def test_load_recovers_from_corrupt_file(self, temp_config):
        temp_config.parent.mkdir(parents=True, exist_ok=True)
        temp_config.write_text("garbage", encoding="utf-8")
        assert cfg.load_config()["preset"] == "Opus Clean"

    def test_import_malformed_raises_valueerror(self, temp_config, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json at all", encoding="utf-8")
        with pytest.raises(ValueError):
            cfg.import_config(str(bad))

    def test_import_missing_file_raises_valueerror(self, temp_config, tmp_path):
        with pytest.raises(ValueError):
            cfg.import_config(str(tmp_path / "nope.json"))

    def test_import_replaces_stale_keys(self, temp_config, tmp_path):
        cfg.set("llm_api_key", "secret")
        imp = tmp_path / "imp.json"
        imp.write_text(json.dumps({"llm_provider": "openai"}), encoding="utf-8")
        cfg.import_config(str(imp))
        assert cfg.get("llm_provider") == "openai"
        assert cfg.get("llm_api_key") == ""  # stale key cleared, back to default

    def test_unicode_round_trip(self, temp_config):
        cfg.set("caption_template", "{title} 🔥 Part {part}")
        assert cfg.get("caption_template") == "{title} 🔥 Part {part}"
