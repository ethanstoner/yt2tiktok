import os
import threading
import customtkinter as ctk
from tkinter import messagebox

from src import uploader
from src.constants import *
from src.ui.widgets import SectionHeader, Divider, FilePickerRow, Tooltip
from src.validators import validate_time_format, validate_interval


class UploadTab:
    def __init__(self, parent, state, workers_module):
        self.state = state
        self.workers = workers_module

        scroll = ctk.CTkScrollableFrame(parent)
        scroll.pack(fill="both", expand=True)

        ctk.CTkLabel(scroll, text="TikTok Upload", font=("", FONT_HEADER, "bold")).pack(pady=(SP_12, SP_12))

        # Clip folder
        folder_row = FilePickerRow(scroll, "Clip folder:", state.clip_dir, directory=True)
        folder_row.pack(fill="x", padx=SP_12, pady=SP_4)

        # --- Account card ---
        acct_card = ctk.CTkFrame(scroll, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        acct_card.pack(fill="x", padx=SP_12, pady=SP_4)
        self.acct_user = ctk.CTkLabel(acct_card, text="No account loaded",
                                      font=("", FONT_LABEL, "bold"))
        self.acct_user.pack(anchor="w", padx=SP_12, pady=(SP_8, 0))
        self.acct_health = ctk.CTkLabel(acct_card, text="", text_color=TEXT_MUTED)
        self.acct_health.pack(anchor="w", padx=SP_12, pady=(0, SP_4))
        btnrow = ctk.CTkFrame(acct_card, fg_color="transparent")
        btnrow.pack(fill="x", padx=SP_12, pady=(0, SP_8))
        ctk.CTkButton(btnrow, text="Paste cookies JSON", width=150,
                      command=self._paste_cookies).pack(side="left", padx=(0, SP_4))
        ctk.CTkButton(btnrow, text="Load .json", width=90,
                      command=self._load_cookies_file).pack(side="left", padx=SP_4)
        ctk.CTkButton(btnrow, text="Re-verify", width=90,
                      command=self._reverify).pack(side="left", padx=SP_4)
        self._render_account_card()

        # Caption template
        Divider(scroll).pack(fill="x", padx=SP_12, pady=SP_12)
        ctk.CTkLabel(scroll, text="Caption template", font=("", FONT_LABEL)).pack(anchor="w", padx=SP_12)
        ctk.CTkEntry(scroll, textvariable=state.caption_template,
                     placeholder_text="{title} - Part {part}").pack(fill="x", padx=SP_12, pady=(0, SP_4))
        ctk.CTkLabel(scroll, text="Placeholders: {title}, {part}, {total}",
                     text_color=TEXT_MUTED, font=("", 11)).pack(anchor="w", padx=SP_12)

        # Schedule settings
        Divider(scroll).pack(fill="x", padx=SP_12, pady=SP_12)
        schedule_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        schedule_frame.pack(fill="x", padx=SP_12, pady=SP_4)
        ctk.CTkLabel(schedule_frame, text="Start time:").pack(side="left")
        ctk.CTkEntry(schedule_frame, textvariable=state.start_time, width=80,
                     placeholder_text="HH:MM").pack(side="left", padx=SP_4)
        ctk.CTkLabel(schedule_frame, text="Interval (hrs):").pack(side="left", padx=(SP_16, 0))
        ctk.CTkEntry(schedule_frame, textvariable=state.interval, width=60).pack(side="left", padx=SP_4)

        # Headless
        ctk.CTkCheckBox(scroll, text="Headless mode (uncheck to debug)",
                        variable=state.headless).pack(anchor="w", padx=SP_12, pady=SP_4)

        # Troubleshooting
        troubleshoot_ref = [None]
        def toggle_troubleshoot():
            if troubleshoot_ref[0] is not None:
                troubleshoot_ref[0].destroy()
                troubleshoot_ref[0] = None
                troubleshoot_btn.configure(text="Show Troubleshooting Tips")
            else:
                f = ctk.CTkFrame(scroll, fg_color=BG_INPUT, corner_radius=RADIUS_CARD)
                f.pack(fill="x", padx=SP_12, pady=SP_4, before=self.upload_btn)
                ctk.CTkLabel(f, text=(
                    "If verification fails or uploads get CAPTCHA blocked:\n"
                    "1. Uncheck 'Headless mode' and try again\n"
                    "2. Solve any CAPTCHA or login prompt in that window\n"
                    "3. Close the window, re-export cookies, and try again\n"
                    "4. Cookies expire regularly - re-export when sessions fail"
                ), justify="left", wraplength=580).pack(padx=SP_12, pady=SP_12)
                troubleshoot_ref[0] = f
                troubleshoot_btn.configure(text="Hide Troubleshooting Tips")

        troubleshoot_btn = ctk.CTkButton(
            scroll, text="Show Troubleshooting Tips", width=200, height=28,
            fg_color="transparent", border_width=1, command=toggle_troubleshoot,
        )
        troubleshoot_btn.pack(anchor="w", padx=SP_12, pady=(SP_4, SP_4))

        # Upload button
        self.upload_btn = ctk.CTkButton(
            scroll, text="Upload to TikTok", height=40,
            font=("", 15, "bold"), command=self._on_upload,
        )
        self.upload_btn.pack(fill="x", padx=SP_12, pady=(SP_12, SP_12))

    def _render_account_card(self):
        from src.tiktok.account import get_account
        a = get_account("main")
        if not a:
            self.acct_user.configure(text="No account loaded")
            self.acct_health.configure(text="Paste or load your TikTok cookies.",
                                       text_color=TEXT_MUTED)
            return
        self.acct_user.configure(
            text=f"@{a.username}" if a.username else "Loaded (not verified)")
        h = a.health()
        color = {"valid": SUCCESS, "expiring": WARNING, "expired": ERROR,
                 "session-only": TEXT_MUTED, "missing": ERROR}.get(
                     h["status"], TEXT_MUTED)
        self.acct_health.configure(text=h["detail"], text_color=color)

    def _store_cookies(self, source: str):
        from src.tiktok.cookies import parse_cookie_json
        from src.tiktok.account import Account, save_account
        from tkinter import messagebox
        try:
            cookies = parse_cookie_json(source)
        except ValueError as e:
            messagebox.showerror("Invalid cookies", str(e))
            return
        save_account(Account(id="main", label="Main", cookies=cookies))
        self._render_account_card()
        self._reverify()

    def _paste_cookies(self):
        dlg = ctk.CTkToplevel(self.acct_user.winfo_toplevel())
        dlg.title("Paste cookies JSON")
        dlg.geometry("520x360")
        box = ctk.CTkTextbox(dlg)
        box.pack(fill="both", expand=True, padx=SP_12, pady=SP_12)
        def _load():
            txt = box.get("1.0", "end").strip()
            dlg.destroy()
            if txt:
                self._store_cookies(txt)
        ctk.CTkButton(dlg, text="Load", command=_load).pack(pady=(0, SP_12))

    def _load_cookies_file(self):
        from tkinter import filedialog
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if p:
            self._store_cookies(p)

    def _reverify(self):
        import threading
        from src.tiktok.account import get_account, verify
        a = get_account("main")
        if not a:
            return
        self.acct_health.configure(text="Verifying…", text_color=TEXT_MUTED)
        def _run():
            verify(a, headless=self.state.headless.get())
            self.acct_user.winfo_toplevel().after(0, self._render_account_card)
        threading.Thread(target=_run, daemon=True).start()

    def _on_upload(self):
        from src.tiktok.account import get_account
        a = get_account("main")
        if a is None or a.health()["status"] in {"expired", "missing"}:
            messagebox.showerror("No TikTok account", "Load and verify your TikTok cookies first.")
            return
        if not self.state.clip_dir.get() or not os.path.isdir(self.state.clip_dir.get()):
            messagebox.showerror("Error", "Select a valid clip folder.")
            return
        valid, err = validate_time_format(self.state.start_time.get())
        if not valid:
            messagebox.showerror("Invalid Start Time", err)
            return
        valid, err = validate_interval(self.state.interval.get())
        if not valid:
            messagebox.showerror("Invalid Interval", err)
            return
        self.upload_btn.configure(state="disabled", text="Uploading...")
        clip_count = len([f for f in os.listdir(self.state.clip_dir.get())
                         if f.endswith(".mp4") and "_clip_" in f])
        threading.Thread(
            target=self.workers.uploader_worker,
            args=(self.state.clip_dir.get(), self.state.title.get(), clip_count,
                  "main", self.state.caption_template.get(),
                  self.state.start_time.get(), self.state.interval.get(),
                  self.state.headless.get(), self.upload_btn),
            daemon=True,
        ).start()
