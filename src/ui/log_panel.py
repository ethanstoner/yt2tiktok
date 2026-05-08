import customtkinter as ctk
from src.constants import *


class LogPanel(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.pack(fill="x", pady=(0, SP_4))
        self.progress_bar.set(0)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x")
        ctk.CTkLabel(header, text="Log", font=("", FONT_BODY, "bold")).pack(side="left")
        self.progress_label = ctk.CTkLabel(header, text="", text_color=SUCCESS, font=("", FONT_MUTED))
        self.progress_label.pack(side="left", padx=SP_12)

        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.pack(side="right")

        ctk.CTkButton(
            btn_frame, text="Clear", width=60, height=24,
            fg_color="transparent", border_width=1, font=("", 11),
            command=self._clear_log,
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            btn_frame, text="Copy", width=60, height=24,
            fg_color="transparent", border_width=1, font=("", 11),
            command=self._copy_log,
        ).pack(side="left", padx=2)

        self.toggle_btn = ctk.CTkButton(
            btn_frame, text="Show Log", width=80, height=24,
            fg_color="transparent", border_width=1, font=("", 11),
            command=self._toggle,
        )
        self.toggle_btn.pack(side="left", padx=2)

        self.log_box = ctk.CTkTextbox(
            self, height=180, font=("Consolas", 12),
            fg_color=BG_DARK, text_color=LOG_INFO,
        )
        self._visible = False

    def _toggle(self):
        if self._visible:
            self.log_box.pack_forget()
            self._visible = False
            self.toggle_btn.configure(text="Show Log")
        else:
            self.log_box.pack(fill="x", pady=(SP_4, 0))
            self._visible = True
            self.toggle_btn.configure(text="Hide Log")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")

    def _copy_log(self):
        text = self.log_box.get("1.0", "end").strip()
        if text:
            self.winfo_toplevel().clipboard_clear()
            self.winfo_toplevel().clipboard_append(text)

    def append_log(self, msg: str):
        # Color-code based on content
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        if not self._visible:
            self._toggle()

    def set_progress(self, fraction: float):
        self.progress_bar.set(fraction)

    def set_progress_text(self, text: str):
        self.progress_label.configure(text=text)

    @property
    def is_visible(self):
        return self._visible
