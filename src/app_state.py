import customtkinter as ctk
from src import config as cfg
from src import uploader


class AppState:
    def __init__(self):
        self._initializing = True

        # Clip tab
        self.url = ctk.StringVar()
        self.local_path = ctk.StringVar()
        self.yt_cookie = ctk.StringVar()
        self.video_path = ctk.StringVar()
        self.clip_dir = ctk.StringVar()
        self.title = ctk.StringVar()
        self.transcript_count = ctk.StringVar()
        self.highlight = ctk.StringVar()
        self.mode = ctk.StringVar(value=cfg.get("mode"))
        self.cut_mode = ctk.StringVar(value=cfg.get("cut_mode"))
        self.captions_enabled = ctk.BooleanVar(value=cfg.get("captions_enabled"))
        self.preset = ctk.StringVar(value=cfg.get("preset"))
        self.caption_y = ctk.DoubleVar(value=cfg.get("caption_y"))
        self.transcription_status = ctk.StringVar(value="")
        self.keep_source_video = ctk.BooleanVar(value=cfg.get("keep_source_video"))

        # Upload tab
        self.tk_cookie = ctk.StringVar(value=uploader.load_last_cookie_path())
        self.tk_status = ctk.StringVar()
        self.headless = ctk.BooleanVar(value=cfg.get("headless"))
        self.caption_template = ctk.StringVar(value=cfg.get("caption_template"))
        self.start_time = ctk.StringVar(value=cfg.get("start_time"))
        self.interval = ctk.StringVar(value=cfg.get("interval"))

        # LLM settings
        self.llm_enabled = ctk.BooleanVar(value=cfg.get("llm_enabled"))
        self.llm_provider = ctk.StringVar(value=cfg.get("llm_provider"))
        self.llm_api_key = ctk.StringVar(value=cfg.get("llm_api_key"))
        self.llm_model = ctk.StringVar(value=cfg.get("llm_model"))
        self.llm_base_url = ctk.StringVar(value=cfg.get("llm_base_url"))

        # Thumbnail holders
        self.thumb_ctk_image = None
        self.thumb_pil_image = None

        # Persist settings on change
        self._setup_auto_persist()
        self._initializing = False

    def _setup_auto_persist(self):
        persist_list = [
            (self.mode, "mode"),
            (self.cut_mode, "cut_mode"),
            (self.captions_enabled, "captions_enabled"),
            (self.preset, "preset"),
            (self.caption_y, "caption_y"),
            (self.headless, "headless"),
            (self.caption_template, "caption_template"),
            (self.start_time, "start_time"),
            (self.interval, "interval"),
            (self.llm_enabled, "llm_enabled"),
            (self.llm_provider, "llm_provider"),
            (self.llm_api_key, "llm_api_key"),
            (self.llm_model, "llm_model"),
            (self.llm_base_url, "llm_base_url"),
            (self.keep_source_video, "keep_source_video"),
        ]
        for var, key in persist_list:
            var.trace_add("write", lambda *_, k=key, v=var: (
                cfg.set(k, v.get()) if not self._initializing else None
            ))

    def reload_from_config(self):
        """Reload all persisted vars from the current config file (after import/reset)."""
        self._initializing = True
        try:
            self.mode.set(cfg.get("mode"))
            self.cut_mode.set(cfg.get("cut_mode"))
            self.captions_enabled.set(cfg.get("captions_enabled"))
            self.preset.set(cfg.get("preset"))
            self.caption_y.set(cfg.get("caption_y"))
            self.headless.set(cfg.get("headless"))
            self.caption_template.set(cfg.get("caption_template"))
            self.start_time.set(cfg.get("start_time"))
            self.interval.set(cfg.get("interval"))
            self.llm_enabled.set(cfg.get("llm_enabled"))
            self.llm_provider.set(cfg.get("llm_provider"))
            self.llm_api_key.set(cfg.get("llm_api_key"))
            self.llm_model.set(cfg.get("llm_model"))
            self.llm_base_url.set(cfg.get("llm_base_url"))
            self.keep_source_video.set(cfg.get("keep_source_video"))
        finally:
            self._initializing = False
