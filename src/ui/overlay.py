import customtkinter as ctk
from src.constants import *


class Overlay(ctk.CTkFrame):
    """A full-window overlay that renders on top of app content instead of spawning a new window."""

    def __init__(self, master, title="", on_close=None, **kwargs):
        super().__init__(master, fg_color=BG_DARK, corner_radius=0, **kwargs)
        self._on_close = on_close

        # Header bar
        header = ctk.CTkFrame(self, fg_color=BG_CARD, height=48, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)

        back_btn = ctk.CTkButton(
            header, text="< Back", width=70, height=32,
            fg_color="transparent", hover_color=BG_INPUT,
            font=("", FONT_BODY), anchor="w",
            command=self.close,
        )
        back_btn.pack(side="left", padx=SP_8)

        if title:
            ctk.CTkLabel(header, text=title, font=("", FONT_SECTION, "bold")).pack(side="left", padx=SP_4)

        # Content area — subclasses pack widgets into this
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=SP_24, pady=SP_16)

    def show(self):
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.lift()
        self.focus_set()

    def close(self):
        if self._on_close:
            self._on_close()
        self.place_forget()
        self.destroy()
