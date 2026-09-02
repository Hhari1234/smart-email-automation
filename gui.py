"""
gui.py
Modern Tkinter GUI for ResumeMailer.
Tabs: Setup -> Recipients -> Template -> Send
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path

from config import Settings
import excel_io
from template_engine import render, text_to_html
from validators import is_valid_email
from mailer import EmailSender, SendError
from sender_worker import SendWorker

BASE_DIR = Path(__file__).resolve().parent

PLACEHOLDERS = ["hr_name", "company", "job_role", "location",
                "your_name", "your_email", "your_phone", "your_linkedin"]

BG = "#f4f6fb"
PRIMARY = "#2d5be3"
PRIMARY_DARK = "#1c3f9e"
SUCCESS = "#1f9d55"
DANGER = "#d93a3a"
TEXT_DARK = "#1b1f2a"


class ResumeMailerApp:
    def __init__(self, root):
        self.root = root
        self.settings = Settings()
        self.recipients = []
        self.worker = None

        root.title("ResumeMailer — Bulk Job Application Sender")
        root.geometry("980x700")
        root.configure(bg=BG)
        self._setup_style()

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=14, pady=14)

        self.tab_setup = ttk.Frame(self.notebook, padding=16)
        self.tab_recipients = ttk.Frame(self.notebook, padding=16)
        self.tab_template = ttk.Frame(self.notebook, padding=16)
        self.tab_send = ttk.Frame(self.notebook, padding=16)

        self.notebook.add(self.tab_setup, text="  1. Setup  ")
        self.notebook.add(self.tab_recipients, text="  2. Recipients  ")
        self.notebook.add(self.tab_template, text="  3. Template  ")
        self.notebook.add(self.tab_send, text="  4. Send  ")

        self._build_setup_tab()
        self._build_recipients_tab()
        self._build_template_tab()
        self._build_send_tab()

        self._load_settings_into_widgets()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------- styling ----
    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 10), font=("Segoe UI", 10, "bold"))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT_DARK, font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 13, "bold"))
        style.configure("TButton", font=("Segoe UI", 10), padding=6)
        style.configure("Primary.TButton", background=PRIMARY, foreground="white")
        style.map("Primary.TButton", background=[("active", PRIMARY_DARK)])
        style.configure("TEntry", padding=4)
        style.configure("Horizontal.TProgressbar", troughcolor="#dde3f0", background=PRIMARY)

    # ---------------------------------------------------------- tab 1 -----
    def _build_setup_tab(self):
        t = self.tab_setup
        ttk.Label(t, text="Your Details & Credentials", style="Header.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        self.var_name = tk.StringVar()
        self.var_email = tk.StringVar()
        self.var_phone = tk.StringVar()
        self.var_linkedin = tk.StringVar()

        self._labeled_entry(t, 1, "Your Name", self.var_name)
        self._labeled_entry(t, 2, "Your Sender Email (Gmail)", self.var_email)
        self._labeled_entry(t, 3, "Phone", self.var_phone)
        self._labeled_entry(t, 4, "LinkedIn URL", self.var_linkedin)

        ttk.Separator(t).grid(row=5, column=0, columnspan=3, sticky="ew", pady=14)

        ttk.Label(t, text="Resume file (PDF/DOCX)").grid(row=6, column=0, sticky="w", pady=4)
        self.var_resume = tk.StringVar()
        ttk.Entry(t, textvariable=self.var_resume, width=55, state="readonly").grid(row=6, column=1, sticky="w")
        ttk.Button(t, text="Browse...", command=self._pick_resume).grid(row=6, column=2, sticky="w", padx=6)

        ttk.Label(t, text="Extra attachments (optional)").grid(row=7, column=0, sticky="w", pady=4)
        self.var_extra = tk.StringVar()
        ttk.Entry(t, textvariable=self.var_extra, width=55, state="readonly").grid(row=7, column=1, sticky="w")
        ttk.Button(t, text="Add file...", command=self._pick_extra).grid(row=7, column=2, sticky="w", padx=6)

        ttk.Separator(t).grid(row=8, column=0, columnspan=3, sticky="ew", pady=14)

        ttk.Label(t, text="Sending Method", style="Header.TLabel").grid(row=9, column=0, columnspan=3, sticky="w")
        self.var_use_gmail_api = tk.BooleanVar(value=True)
        ttk.Checkbutton(t, text="Prefer Gmail API (falls back to SMTP automatically)",
                         variable=self.var_use_gmail_api).grid(row=10, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Label(t, text="SMTP fallback / credentials are read from the .env file "
                          "(SMTP_EMAIL, SMTP_APP_PASSWORD). See README.md.",
                  wraplength=650, foreground="#555").grid(row=11, column=0, columnspan=3, sticky="w", pady=(0, 8))

        ttk.Separator(t).grid(row=12, column=0, columnspan=3, sticky="ew", pady=14)
        ttk.Label(t, text="Sending Behavior", style="Header.TLabel").grid(row=13, column=0, columnspan=3, sticky="w")

        self.var_delay_min = tk.StringVar(value="5")
        self.var_delay_max = tk.StringVar(value="15")
        self.var_retries = tk.StringVar(value="3")

        row = 14
        ttk.Label(t, text="Delay between emails (seconds, min-max)").grid(row=row, column=0, sticky="w")
        frame = ttk.Frame(t)
        frame.grid(row=row, column=1, sticky="w")
        ttk.Entry(frame, textvariable=self.var_delay_min, width=6).pack(side="left")
        ttk.Label(frame, text=" to ").pack(side="left")
        ttk.Entry(frame, textvariable=self.var_delay_max, width=6).pack(side="left")

        row += 1
        ttk.Label(t, text="Max retries per email").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(t, textvariable=self.var_retries, width=6).grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Button(t, text="Save Settings", style="Primary.TButton",
                   command=self._save_settings).grid(row=row, column=0, pady=16, sticky="w")

    def _labeled_entry(self, parent, row, label, var):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=var, width=45).grid(row=row, column=1, columnspan=2, sticky="w")

    def _pick_resume(self):
        path = filedialog.askopenfilename(filetypes=[("Resume files", "*.pdf *.docx"), ("All files", "*.*")])
        if path:
            self.var_resume.set(path)

    def _pick_extra(self):
        paths = filedialog.askopenfilenames()
        if paths:
            existing = [p for p in self.var_extra.get().split(";") if p]
            existing.extend(paths)
            self.var_extra.set(";".join(existing))

    # ---------------------------------------------------------- tab 2 -----
    def _build_recipients_tab(self):
        t = self.tab_recipients
        ttk.Label(t, text="Import Recipients (Excel or CSV)", style="Header.TLabel").pack(anchor="w")
        ttk.Label(t, text="Required columns (any casing/order): HR Name, Company, Email, Job Role, Location",
                  foreground="#555").pack(anchor="w", pady=(2, 10))

        btn_row = ttk.Frame(t)
        btn_row.pack(anchor="w", pady=4)
        ttk.Button(btn_row, text="Import File...", style="Primary.TButton",
                   command=self._import_recipients).pack(side="left")
        ttk.Button(btn_row, text="Download Sample Template",
                   command=self._download_sample).pack(side="left", padx=8)

        ttk.Separator(t).pack(fill="x", pady=14)

        ttk.Label(t, text="Paste Email Addresses", style="Header.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(t, text="Paste emails (newline, comma, or semicolon separated). Supports Name <email> format.",
                  foreground="#555").pack(anchor="w", pady=(0, 6))
        self.txt_paste = scrolledtext.ScrolledText(t, width=95, height=8, font=("Segoe UI", 10), wrap="word")
        self.txt_paste.pack(pady=(0, 8))
        paste_btn_row = ttk.Frame(t)
        paste_btn_row.pack(anchor="w", pady=(0, 10))
        ttk.Button(paste_btn_row, text="Parse Emails", style="Primary.TButton",
                   command=self._parse_pasted_emails).pack(side="left")
        ttk.Button(paste_btn_row, text="Merge into Recipients",
                   command=self._merge_parsed_recipients).pack(side="left", padx=8)
        self.lbl_parse_summary = ttk.Label(t, text="", foreground="#555")
        self.lbl_parse_summary.pack(anchor="w", pady=(0, 10))

        self.lbl_recipient_count = ttk.Label(t, text="No recipients loaded.")
        self.lbl_recipient_count.pack(anchor="w", pady=(6, 6))

        columns = ("hr_name", "company", "email", "job_role", "location")
        self.tree = ttk.Treeview(t, columns=columns, show="headings", height=14)
        for col in columns:
            self.tree.heading(col, text=col.replace("_", " ").title())
            self.tree.column(col, width=150)
        self.tree.pack(fill="both", expand=True)

        self._parsed_valid = []
        self._parsed_invalid = []
        self._parsed_duplicates = []

    def _parse_pasted_emails(self):
        from recipient_parser import parse_recipients
        raw = self.txt_paste.get("1.0", "end").strip()
        if not raw:
            messagebox.showinfo("Empty", "Paste some email addresses first.")
            return
        result = parse_recipients(raw)
        self._parsed_valid = result["valid"]
        self._parsed_invalid = result["invalid"]
        self._parsed_duplicates = result["duplicates"]
        self.lbl_parse_summary.config(
            text=f"Valid: {len(result['valid'])} | Duplicates: {len(result['duplicates'])} | Invalid: {len(result['invalid'])}"
        )
        if result["invalid"]:
            messagebox.showinfo("Invalid Entries", "\n".join(result["invalid"]))

    def _merge_parsed_recipients(self):
        if not self._parsed_valid:
            messagebox.showinfo("Nothing to Merge", "Parse emails first.")
            return
        merged, new_count, dup_count = self._merge_recipients(self.recipients, self._parsed_valid)
        self.recipients = merged
        self._refresh_tree()
        self.txt_paste.delete("1.0", "end")
        self._parsed_valid = []
        self._parsed_invalid = []
        self._parsed_duplicates = []
        self.lbl_parse_summary.config(text=f"Merged {new_count} new (skipped {dup_count} duplicates)")

    def _import_recipients(self):
        path = filedialog.askopenfilename(filetypes=[("Spreadsheet", "*.xlsx *.xls *.csv")])
        if not path:
            return
        try:
            self.recipients = excel_io.load_recipients(path)
        except Exception as e:
            messagebox.showerror("Import Error", str(e))
            return
        self.settings.set("recipients_path", path)
        self._refresh_tree()

    def _refresh_tree(self):
        for row_id in self.tree.get_children():
            self.tree.delete(row_id)
        valid = 0
        for r in self.recipients:
            self.tree.insert("", "end", values=(r["hr_name"], r["company"], r["email"], r["job_role"], r["location"]))
            if is_valid_email(r.get("email", "")):
                valid += 1
        self.lbl_recipient_count.config(
            text=f"{len(self.recipients)} recipients loaded ({valid} with valid emails)."
        )

    def _merge_recipients(self, existing, new_ones):
        existing_lower = {r.get("email", "").lower(): r for r in existing if r.get("email")}
        merged = list(existing)
        new_count = 0
        dup_count = 0
        for r in new_ones:
            email = r.get("email", "").lower()
            if not email:
                continue
            if email in existing_lower:
                dup_count += 1
                continue
            merged.append(r)
            existing_lower[email] = r
            new_count += 1
        return merged, new_count, dup_count

    def _download_sample(self):
        out = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile="recipients_sample.xlsx")
        if out:
            excel_io.create_sample_recipients(Path(out))
            messagebox.showinfo("Saved", f"Sample template saved to:\n{out}")

    # ---------------------------------------------------------- tab 3 -----
    def _build_template_tab(self):
        t = self.tab_template
        ttk.Label(t, text="Subject").grid(row=0, column=0, sticky="w")
        self.var_subject = tk.StringVar(value="Application for {{job_role}} at {{company}}")
        ttk.Entry(t, textvariable=self.var_subject, width=90).grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 10))

        ttk.Label(t, text="Email Body (use placeholders below)").grid(row=2, column=0, sticky="w")
        self.txt_body = scrolledtext.ScrolledText(t, width=95, height=16, font=("Segoe UI", 10), wrap="word")
        self.txt_body.grid(row=3, column=0, columnspan=4, pady=(4, 8))

        ph_frame = ttk.Frame(t)
        ph_frame.grid(row=4, column=0, columnspan=4, sticky="w")
        ttk.Label(ph_frame, text="Insert:").pack(side="left")
        for ph in PLACEHOLDERS:
            ttk.Button(ph_frame, text="{{" + ph + "}}",
                       command=lambda p=ph: self.txt_body.insert("insert", "{{" + p + "}}")
                       ).pack(side="left", padx=2, pady=4)

        ttk.Label(t, text="HTML Signature").grid(row=5, column=0, sticky="w", pady=(10, 0))
        self.txt_sig = scrolledtext.ScrolledText(t, width=95, height=5, font=("Segoe UI", 10))
        self.txt_sig.grid(row=6, column=0, columnspan=4, pady=4)

        btn_row = ttk.Frame(t)
        btn_row.grid(row=7, column=0, columnspan=4, pady=10, sticky="w")
        ttk.Button(btn_row, text="Preview Email", style="Primary.TButton",
                   command=self._preview_email).pack(side="left")
        ttk.Button(btn_row, text="Send Test Email to Myself",
                   command=self._send_test_email).pack(side="left", padx=8)

        self.txt_body.insert("1.0", (
            "Dear {{hr_name}},\n\n"
            "I hope you're doing well. I'm reaching out to apply for the "
            "{{job_role}} position at {{company}}.\n\n"
            "I've attached my resume for your review and would be grateful for "
            "the opportunity to discuss how I could contribute to your team.\n\n"
            "Thank you for your time and consideration."
        ))
        self.txt_sig.insert("1.0", (
            "<br><br>Best regards,<br><b>{{your_name}}</b><br>"
            "{{your_phone}} | {{your_email}}<br>{{your_linkedin}}"
        ))

    def _sample_context(self):
        row = self.recipients[0] if self.recipients else {
            "hr_name": "Jane Doe", "company": "Example Corp",
            "job_role": "Software Engineer", "location": "Bengaluru",
        }
        return {
            "hr_name": row.get("hr_name", ""), "company": row.get("company", ""),
            "job_role": row.get("job_role", ""), "location": row.get("location", ""),
            "your_name": self.var_name.get(), "your_email": self.var_email.get(),
            "your_phone": self.var_phone.get(), "your_linkedin": self.var_linkedin.get(),
        }

    def _preview_email(self):
        ctx = self._sample_context()
        subject = render(self.var_subject.get(), ctx)
        body = render(self.txt_body.get("1.0", "end"), ctx)
        sig = render(self.txt_sig.get("1.0", "end"), ctx)

        win = tk.Toplevel(self.root)
        win.title("Email Preview")
        win.geometry("640x520")
        ttk.Label(win, text=f"Subject: {subject}", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12, pady=8)
        box = scrolledtext.ScrolledText(win, wrap="word")
        box.pack(fill="both", expand=True, padx=12, pady=8)
        box.insert("1.0", body + "\n\n[Signature HTML]\n" + sig)
        box.config(state="disabled")

    def _send_test_email(self):
        target = self.var_email.get().strip()
        if not is_valid_email(target):
            messagebox.showerror("Missing Email", "Enter a valid 'Your Sender Email' in the Setup tab first.")
            return
        ctx = self._sample_context()
        subject = "[TEST] " + render(self.var_subject.get(), ctx)
        body_html = text_to_html(render(self.txt_body.get("1.0", "end"), ctx))
        sig_html = render(self.txt_sig.get("1.0", "end"), ctx)
        attachments = self._collect_attachments()
        try:
            self._save_settings(silent=True)
            sender = EmailSender(self.settings)
            sender.send(target, subject, body_html + sig_html, attachments)
            messagebox.showinfo("Success", f"Test email sent to {target} via {sender.backend_name}.")
        except SendError as e:
            messagebox.showerror("Send Failed", str(e))

    # ---------------------------------------------------------- tab 4 -----
    def _build_send_tab(self):
        t = self.tab_send
        ttk.Label(t, text="Send Emails", style="Header.TLabel").pack(anchor="w")

        stats_frame = ttk.Frame(t)
        stats_frame.pack(anchor="w", pady=10)
        self.lbl_sent = ttk.Label(stats_frame, text="Sent: 0", foreground=SUCCESS, font=("Segoe UI", 11, "bold"))
        self.lbl_failed = ttk.Label(stats_frame, text="Failed: 0", foreground=DANGER, font=("Segoe UI", 11, "bold"))
        self.lbl_skipped = ttk.Label(stats_frame, text="Skipped: 0", font=("Segoe UI", 11, "bold"))
        self.lbl_remaining = ttk.Label(stats_frame, text="Remaining: 0", font=("Segoe UI", 11, "bold"))
        for w in (self.lbl_sent, self.lbl_failed, self.lbl_skipped, self.lbl_remaining):
            w.pack(side="left", padx=14)

        self.progress = ttk.Progressbar(t, orient="horizontal", length=880, mode="determinate")
        self.progress.pack(pady=10)

        btn_row = ttk.Frame(t)
        btn_row.pack(pady=8)
        self.btn_start = ttk.Button(btn_row, text="Start Sending", style="Primary.TButton", command=self._start_send)
        self.btn_pause = ttk.Button(btn_row, text="Pause", command=self._pause_send, state="disabled")
        self.btn_resume = ttk.Button(btn_row, text="Resume", command=self._resume_send, state="disabled")
        self.btn_stop = ttk.Button(btn_row, text="Stop", command=self._stop_send, state="disabled")
        for b in (self.btn_start, self.btn_pause, self.btn_resume, self.btn_stop):
            b.pack(side="left", padx=6)

        ttk.Label(t, text="Live Log").pack(anchor="w", pady=(10, 2))
        self.log_box = scrolledtext.ScrolledText(t, width=115, height=18, font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True)

    def _collect_attachments(self):
        files = []
        resume = self.var_resume.get().strip()
        if resume:
            files.append(resume)
        extra = self.var_extra.get().strip()
        if extra:
            files.extend([p for p in extra.split(";") if p])
        return files

    def _start_send(self):
        if not self.recipients:
            messagebox.showerror("No Recipients", "Import a recipient list in the Recipients tab first.")
            return
        if not self.var_resume.get().strip():
            if not messagebox.askyesno("No Resume Attached", "No resume file selected. Continue anyway?"):
                return
        self._save_settings(silent=True)

        self.progress["value"] = 0
        self.progress["maximum"] = len(self.recipients)
        self.log_box.delete("1.0", "end")

        self.worker = SendWorker(
            settings=self.settings.data,
            recipients=self.recipients,
            template_text=self.txt_body.get("1.0", "end"),
            subject_template=self.var_subject.get(),
            signature_html=self.txt_sig.get("1.0", "end"),
            attachments=self._collect_attachments(),
            on_progress=self._on_progress,
            on_log=self._on_log,
            on_done=self._on_done,
        )
        self.worker.start()
        self.btn_start.config(state="disabled")
        self.btn_pause.config(state="normal")
        self.btn_stop.config(state="normal")

    def _pause_send(self):
        if self.worker:
            self.worker.pause()
            self.btn_pause.config(state="disabled")
            self.btn_resume.config(state="normal")
            self._on_log("Paused.")

    def _resume_send(self):
        if self.worker:
            self.worker.resume()
            self.btn_pause.config(state="normal")
            self.btn_resume.config(state="disabled")
            self._on_log("Resumed.")

    def _stop_send(self):
        if self.worker:
            self.worker.stop()
            self.btn_stop.config(state="disabled")
            self._on_log("Stopping...")

    # These callbacks run on the worker thread -> marshal to main thread via `after`
    def _on_progress(self, sent, failed, skipped, total):
        self.root.after(0, self._update_progress_ui, sent, failed, skipped, total)

    def _update_progress_ui(self, sent, failed, skipped, total):
        self.lbl_sent.config(text=f"Sent: {sent}")
        self.lbl_failed.config(text=f"Failed: {failed}")
        self.lbl_skipped.config(text=f"Skipped: {skipped}")
        self.lbl_remaining.config(text=f"Remaining: {total - sent - failed - skipped}")
        self.progress["value"] = sent + failed + skipped

    def _on_log(self, message):
        self.root.after(0, self._append_log, message)

    def _append_log(self, message):
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")

    def _on_done(self, stats):
        self.root.after(0, self._finish_ui, stats)

    def _finish_ui(self, stats):
        self.btn_start.config(state="normal")
        self.btn_pause.config(state="disabled")
        self.btn_resume.config(state="disabled")
        self.btn_stop.config(state="disabled")
        messagebox.showinfo(
            "Send Complete",
            f"Sent: {stats.get('sent', 0)}\nFailed: {stats.get('failed', 0)}\n"
            f"Skipped (duplicates/invalid): {stats.get('skipped', 0)}\n\n"
            f"Logs saved in the 'logs' folder."
        )

    # ---------------------------------------------------------- settings --
    def _save_settings(self, silent=False):
        s = self.settings
        s.set("sender_name", self.var_name.get())
        s.set("sender_email", self.var_email.get())
        s.set("sender_phone", self.var_phone.get())
        s.set("sender_linkedin", self.var_linkedin.get())
        s.set("resume_path", self.var_resume.get())
        s.set("extra_attachments", self.var_extra.get())
        s.set("use_gmail_api", self.var_use_gmail_api.get())
        try:
            s.set("delay_min_seconds", float(self.var_delay_min.get()))
            s.set("delay_max_seconds", float(self.var_delay_max.get()))
            s.set("max_retries", int(self.var_retries.get()))
        except ValueError:
            if not silent:
                messagebox.showerror("Invalid Input", "Delay and retry fields must be numbers.")
            return
        if not silent:
            messagebox.showinfo("Saved", "Settings saved.")

    def _load_settings_into_widgets(self):
        s = self.settings
        self.var_name.set(s.get("sender_name", ""))
        self.var_email.set(s.get("sender_email", ""))
        self.var_phone.set(s.get("sender_phone", ""))
        self.var_linkedin.set(s.get("sender_linkedin", ""))
        self.var_resume.set(s.get("resume_path", ""))
        self.var_extra.set(s.get("extra_attachments", ""))
        self.var_use_gmail_api.set(s.get("use_gmail_api", True))
        self.var_delay_min.set(str(s.get("delay_min_seconds", 5)))
        self.var_delay_max.set(str(s.get("delay_max_seconds", 15)))
        self.var_retries.set(str(s.get("max_retries", 3)))

        recipients_path = s.get("recipients_path", "")
        if recipients_path and Path(recipients_path).exists():
            try:
                self.recipients = excel_io.load_recipients(recipients_path)
                self._refresh_tree()
            except Exception:
                pass

    def _on_close(self):
        self._save_settings(silent=True)
        if self.worker and self.worker.is_alive():
            self.worker.stop()
        self.root.destroy()
