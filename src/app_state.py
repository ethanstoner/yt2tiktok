import threading

import customtkinter as ctk
from src import config as cfg
from src import uploader


class AppState:
    def __init__(self):
        self._initializing = True
        self._save_timers: dict[str, threading.Timer] = {}
        self._save_lock = threading.Lock()

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
        # Numeric vars use get_number: a malformed value in a hand-edited
        # config file would otherwise raise TclError and crash startup.
        self.caption_y = ctk.DoubleVar(value=cfg.get_number("caption_y", float))
        self.transcription_status = ctk.StringVar(value="")
        self.keep_source_video = ctk.BooleanVar(value=cfg.get("keep_source_video"))
        # Moments settings are StringVars (parsed at submit in ClipTab):
        # an IntVar bound to a CTkEntry spams TclError tracebacks whenever
        # the field is momentarily empty while retyping. get_number still
        # guards against malformed config values at startup.
        self.moments_count = ctk.StringVar(value=str(cfg.get_number("moments_count", int)))
        self.moments_min_dur = ctk.StringVar(value=str(cfg.get_number("moments_min_dur", int)))
        self.moments_max_dur = ctk.StringVar(value=str(cfg.get_number("moments_max_dur", int)))

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
            (self.moments_count, "moments_count"),
            (self.moments_min_dur, "moments_min_dur"),
            (self.moments_max_dur, "moments_max_dur"),
        ]
        for var, key in persist_list:
            var.trace_add("write", lambda *_, k=key, v=var: (
                self._debounced_save(k, v) if not self._initializing else None
            ))

    def _debounced_save(self, key: str, var):
        """Coalesce rapid writes (e.g. typing in a text field) into a single
        config write ~0.5s after the last change, instead of one disk
        read+write per keystroke."""
        try:
            value = var.get()
        except Exception:
            return
        with self._save_lock:
            existing = self._save_timers.get(key)
            if existing is not None:
                existing.cancel()
            timer = threading.Timer(0.5, self._flush_save, args=(key, value))
            timer.daemon = True
            self._save_timers[key] = timer
            timer.start()

    def _flush_save(self, key: str, value):
        with self._save_lock:
            self._save_timers.pop(key, None)
        cfg.set(key, value)

    def reload_from_config(self):
        """Reload all persisted vars from the current config file (after import/reset)."""
        # Cancel any pending debounced writes so they can't clobber the
        # freshly imported/reset values a moment later.
        with self._save_lock:
            for t in self._save_timers.values():
                t.cancel()
            self._save_timers.clear()

        def _set(var, value, caster):
            try:
                var.set(caster(value))
            except Exception:
                pass  # skip malformed value, keep current

        self._initializing = True
        try:
            _set(self.mode, cfg.get("mode"), str)
            _set(self.cut_mode, cfg.get("cut_mode"), str)
            _set(self.captions_enabled, cfg.get("captions_enabled"), bool)
            _set(self.preset, cfg.get("preset"), str)
            _set(self.caption_y, cfg.get("caption_y"), float)
            _set(self.headless, cfg.get("headless"), bool)
            _set(self.caption_template, cfg.get("caption_template"), str)
            _set(self.start_time, cfg.get("start_time"), str)
            _set(self.interval, cfg.get("interval"), str)
            _set(self.llm_enabled, cfg.get("llm_enabled"), bool)
            _set(self.llm_provider, cfg.get("llm_provider"), str)
            _set(self.llm_api_key, cfg.get("llm_api_key"), str)
            _set(self.llm_model, cfg.get("llm_model"), str)
            _set(self.llm_base_url, cfg.get("llm_base_url"), str)
            _set(self.keep_source_video, cfg.get("keep_source_video"), bool)
            _set(self.moments_count, cfg.get("moments_count"), str)
            _set(self.moments_min_dur, cfg.get("moments_min_dur"), str)
            _set(self.moments_max_dur, cfg.get("moments_max_dur"), str)
        finally:
            self._initializing = False
