import customtkinter as ctk
from tkinter import filedialog
from src.constants import *


class SectionHeader(ctk.CTkFrame):
    def __init__(self, master, text, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        ctk.CTkLabel(self, text=text, font=("", FONT_SECTION, "bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w")


class Divider(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, height=1, fg_color=TEXT_MUTED, **kwargs)


class ValidatedEntry(ctk.CTkFrame):
    def __init__(self, master, textvariable, placeholder="", validator=None, width=None, show=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        entry_kwargs = {"textvariable": textvariable, "placeholder_text": placeholder}
        if width:
            entry_kwargs["width"] = width
        if show:
            entry_kwargs["show"] = show
        self.entry = ctk.CTkEntry(self, **entry_kwargs)
        self.entry.pack(side="left", fill="x", expand=True)
        self.error_label = ctk.CTkLabel(self, text="", text_color=ERROR, font=("", FONT_MUTED))
        self.validator = validator
        self._var = textvariable
        if validator:
            self._var.trace_add("write", self._validate)

    def _validate(self, *_):
        val = self._var.get()
        if not val:
            self.error_label.pack_forget()
            self.entry.configure(border_color=ACCENT_BLUE)
            return
        ok, msg = self.validator(val)
        if ok:
            self.error_label.pack_forget()
            self.entry.configure(border_color=SUCCESS)
        else:
            self.error_label.configure(text=msg)
            self.error_label.pack(side="left", padx=(5, 0))
            self.entry.configure(border_color=ERROR)


class FilePickerRow(ctk.CTkFrame):
    def __init__(self, master, label, textvariable, filetypes=None, directory=False, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        ctk.CTkLabel(self, text=label).pack(side="left")
        path_label = ctk.CTkLabel(self, textvariable=textvariable, text_color=TEXT_MUTED)
        path_label.pack(side="left", padx=5, expand=True, fill="x")

        def browse():
            if directory:
                result = filedialog.askdirectory() or ""
            else:
                result = filedialog.askopenfilename(filetypes=filetypes or []) or ""
            if result:
                textvariable.set(result)

        ctk.CTkButton(self, text="Browse", width=80, command=browse).pack(side="right")

    def add_extra_button(self, text, command, width=60):
        ctk.CTkButton(self, text=text, width=width, command=command).pack(side="right", padx=5)


class Tooltip:
    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._tip_window = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)

    def _schedule(self, event=None):
        self._after_id = self.widget.after(self.delay, self._show)

    def _show(self):
        if self._tip_window:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self._tip_window = tw = ctk.CTkToplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        frame = ctk.CTkFrame(tw, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        frame.pack()
        ctk.CTkLabel(frame, text=self.text, font=("", FONT_MUTED),
                     text_color=TEXT_SECONDARY, wraplength=300,
                     justify="left").pack(padx=SP_8, pady=SP_4)

    def _hide(self, event=None):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self._tip_window:
            self._tip_window.destroy()
            self._tip_window = None
