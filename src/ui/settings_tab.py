import threading
import customtkinter as ctk
from tkinter import filedialog, messagebox

from src import config as cfg
from src.constants import *
from src.llm_provider import LLMProvider, PROVIDERS, detect_ollama_url
from src.ui.widgets import SectionHeader, Divider, Tooltip


class SettingsTab:
    def __init__(self, parent, state, app_ref):
        self.state = state
        self.app = app_ref

        scroll = ctk.CTkScrollableFrame(parent)
        scroll.pack(fill="both", expand=True)

        # --- LLM Configuration ---
        SectionHeader(scroll, "LLM Configuration").pack(pady=(SP_12, SP_12), anchor="w", padx=SP_12)
        llm_check = ctk.CTkCheckBox(scroll, text="Enable LLM (keyword detection + Cliffhanger mode)",
                                     variable=state.llm_enabled)
        llm_check.pack(anchor="w", padx=SP_12, pady=SP_4)
        Tooltip(llm_check, "LLM improves caption keyword highlighting and enables Cliffhanger cut mode")

        # Provider
        prov_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        prov_frame.pack(fill="x", padx=SP_12, pady=SP_4)
        ctk.CTkLabel(prov_frame, text="Provider:").pack(side="left")
        prov_menu = ctk.CTkOptionMenu(prov_frame,
                                       values=["groq", "openai", "gemini", "claude", "ollama", "custom"],
                                       variable=state.llm_provider)
        prov_menu.pack(side="left", padx=SP_4)
        Tooltip(prov_menu, "groq: Free tier available\nopenai: GPT models\ngemini: Google AI\nclaude: Anthropic\nollama: Local models\ncustom: Any OpenAI-compatible endpoint")

        # API Key
        key_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        key_frame.pack(fill="x", padx=SP_12, pady=SP_4)
        ctk.CTkLabel(key_frame, text="API Key:").pack(side="left")
        ctk.CTkEntry(key_frame, textvariable=state.llm_api_key, show="*").pack(
            side="left", padx=SP_4, fill="x", expand=True)

        # Model selector
        mod_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        mod_frame.pack(fill="x", padx=SP_12, pady=SP_4)
        ctk.CTkLabel(mod_frame, text="Model:").pack(side="left")
        self.model_status = ctk.CTkLabel(mod_frame, text="", text_color=TEXT_MUTED, font=("", 11))
        self.model_status.pack(side="right")

        default_model = PROVIDERS.get(state.llm_provider.get(), {}).get("default_model", "")
        initial_models = [default_model] if default_model else ["(default)"]

        self.model_dropdown = ctk.CTkOptionMenu(mod_frame, values=initial_models,
                                                 variable=state.llm_model, width=250)
        self.model_dropdown.pack(side="left", padx=SP_4)

        self.fetch_models_btn = ctk.CTkButton(mod_frame, text="Fetch Models", width=100,
                                               height=28, command=self._fetch_models)
        self.fetch_models_btn.pack(side="left", padx=SP_4)

        # Provider change handler
        def _on_provider_change(*_):
            provider = state.llm_provider.get()
            info = PROVIDERS.get(provider, {})
            default = info.get("default_model", "")
            state.llm_model.set(default)
            self.model_dropdown.configure(values=[default] if default else ["(default)"])
            self.model_status.configure(text="")
            if provider == "ollama":
                def _detect_and_fetch():
                    detected = detect_ollama_url()
                    def _apply():
                        if detected:
                            state.llm_base_url.set(detected)
                            self.model_status.configure(
                                text=f"Found Ollama on {detected.replace('/v1','')}",
                                text_color=SUCCESS)
                        else:
                            self.model_status.configure(text="Ollama not detected", text_color=ERROR)
                        self._fetch_models()
                    self.app.after(0, _apply)
                threading.Thread(target=_detect_and_fetch, daemon=True).start()
        state.llm_provider.trace_add("write", _on_provider_change)

        # Base URL
        url_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        url_frame.pack(fill="x", padx=SP_12, pady=SP_4)
        ctk.CTkLabel(url_frame, text="Base URL:").pack(side="left")
        ctk.CTkEntry(url_frame, textvariable=state.llm_base_url,
                     placeholder_text="Only for custom endpoints").pack(
            side="left", padx=SP_4, fill="x", expand=True)

        # --- Settings Management ---
        Divider(scroll).pack(fill="x", padx=SP_12, pady=SP_16)
        SectionHeader(scroll, "Settings Management").pack(anchor="w", padx=SP_12, pady=(0, SP_8))

        mgmt_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        mgmt_frame.pack(fill="x", padx=SP_12, pady=SP_4)

        ctk.CTkButton(mgmt_frame, text="Export Settings", width=130, height=32,
                      fg_color="transparent", border_width=1,
                      command=self._export_settings).pack(side="left", padx=(0, SP_4))
        ctk.CTkButton(mgmt_frame, text="Import Settings", width=130, height=32,
                      fg_color="transparent", border_width=1,
                      command=self._import_settings).pack(side="left", padx=(0, SP_4))
        ctk.CTkButton(mgmt_frame, text="Reset to Defaults", width=130, height=32,
                      fg_color=ERROR, hover_color="#dc2626",
                      command=self._reset_defaults).pack(side="left")

        # More actions
        Divider(scroll).pack(fill="x", padx=SP_12, pady=SP_16)
        actions_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        actions_frame.pack(fill="x", padx=SP_12, pady=SP_4)
        ctk.CTkButton(actions_frame, text="Run Setup Wizard", width=140, height=32,
                      fg_color="transparent", border_width=1,
                      command=self._run_onboarding).pack(side="left", padx=(0, SP_4))
        ctk.CTkButton(actions_frame, text="Open Error Log", width=130, height=32,
                      fg_color="transparent", border_width=1,
                      command=self._open_error_log).pack(side="left", padx=(0, SP_4))
        ctk.CTkButton(actions_frame, text="About", width=80, height=32,
                      fg_color="transparent", border_width=1,
                      command=self._show_about).pack(side="left")

    def _fetch_models(self):
        self.fetch_models_btn.configure(state="disabled", text="Fetching...")
        self.model_status.configure(text="Fetching...", text_color=TEXT_MUTED)
        provider = self.state.llm_provider.get()
        api_key = self.state.llm_api_key.get()
        base_url = self.state.llm_base_url.get()

        def _do_fetch():
            llm = LLMProvider(provider=provider, api_key=api_key, base_url=base_url)
            models = llm.list_models()
            def _update():
                self.fetch_models_btn.configure(state="normal", text="Fetch Models")
                if models:
                    self.model_dropdown.configure(values=models)
                    if self.state.llm_model.get() not in models:
                        self.state.llm_model.set(models[0])
                    self.model_status.configure(text=f"{len(models)} models", text_color=SUCCESS)
                else:
                    self.model_status.configure(text="No models found", text_color=ERROR)
            self.app.after(0, _update)
        threading.Thread(target=_do_fetch, daemon=True).start()

    def _export_settings(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if path:
            try:
                cfg.export_config(path)
                messagebox.showinfo("Export", f"Settings exported to {path}")
            except Exception as e:
                messagebox.showerror("Export Error", str(e))

    def _import_settings(self):
        path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if path:
            try:
                cfg.import_config(path)
                messagebox.showinfo("Import", "Settings imported. Restart to apply all changes.")
            except Exception as e:
                messagebox.showerror("Import Error", str(e))

    def _reset_defaults(self):
        if messagebox.askyesno("Reset", "Reset all settings to defaults?"):
            cfg.reset_to_defaults()
            messagebox.showinfo("Reset", "Settings reset. Restart to apply all changes.")

    def _open_error_log(self):
        import os
        log_path = cfg.get_config_dir() / "logs" / "errors.log"
        if log_path.exists():
            os.startfile(str(log_path))
        else:
            messagebox.showinfo("Error Log", "No error log file found yet.")

    def _run_onboarding(self):
        from src.ui.onboarding import OnboardingPanel
        OnboardingPanel(self.app)

    def _show_about(self):
        from src.ui.about_dialog import AboutPanel
        AboutPanel(self.app)
