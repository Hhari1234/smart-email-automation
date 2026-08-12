"""
sender_worker.py
Runs the bulk-send loop on a background thread so the Tkinter GUI stays responsive.
Supports pause / resume / stop, per-email retries, randomized delay, duplicate
skipping via the local database, and live progress callbacks back to the GUI.
"""
import random
import threading
import time
from pathlib import Path
from datetime import datetime

from validators import is_valid_email, clean_email
from template_engine import render, text_to_html
from mailer import EmailSender, SendError
from database import Database
import excel_io


class SendWorker(threading.Thread):
    def __init__(self, settings, recipients, template_text, subject_template,
                 signature_html, attachments, on_progress, on_log, on_done):
        """
        on_progress(sent, failed, skipped, total) -> called after every recipient
        on_log(message: str) -> called for human-readable log lines
        on_done(stats: dict) -> called once the run finishes/stops
        """
        super().__init__(daemon=True)
        self.settings = settings
        self.recipients = recipients
        self.template_text = template_text
        self.subject_template = subject_template
        self.signature_html = signature_html
        self.attachments = attachments
        self.on_progress = on_progress
        self.on_log = on_log
        self.on_done = on_done

        self._pause_event = threading.Event()
        self._pause_event.set()  # set = running, cleared = paused
        self._stop_flag = threading.Event()

        self.db = Database()
        self.sent = 0
        self.failed = 0
        self.skipped = 0
        self.failed_records = []

        log_dir = Path(__file__).resolve().parent / "logs"
        log_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_csv = log_dir / f"send_log_{ts}.csv"
        self.failed_xlsx = log_dir / f"failed_{ts}.xlsx"
        self.summary_txt = log_dir / f"summary_{ts}.txt"

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def stop(self):
        self._stop_flag.set()
        self._pause_event.set()  # unblock if paused so the thread can exit

    def _sleep_with_checks(self, seconds):
        """Sleeps in small increments so stop() is responsive even mid-delay."""
        end = time.time() + seconds
        while time.time() < end:
            if self._stop_flag.is_set():
                return
            self._pause_event.wait()
            time.sleep(min(0.5, max(0, end - time.time())))

    def run(self):
        try:
            sender = EmailSender(self.settings)
        except SendError as e:
            self.on_log(f"FATAL: Could not initialize email backend: {e}")
            self.on_done({"sent": 0, "failed": 0, "skipped": 0, "error": str(e)})
            return

        self.on_log(f"Using backend: {sender.backend_name}")
        total = len(self.recipients)
        max_retries = int(self.settings.get("max_retries", 3))
        delay_min = float(self.settings.get("delay_min_seconds", 5))
        delay_max = float(self.settings.get("delay_max_seconds", 15))

        context_static = {
            "your_name": self.settings.get("sender_name", ""),
            "your_email": self.settings.get("sender_email", ""),
            "your_phone": self.settings.get("sender_phone", ""),
            "your_linkedin": self.settings.get("sender_linkedin", ""),
        }

        for idx, row in enumerate(self.recipients, start=1):
            if self._stop_flag.is_set():
                self.on_log("Stopped by user.")
                break
            self._pause_event.wait()

            email = clean_email(row.get("email", ""))
            hr_name = row.get("hr_name", "").strip()
            company = row.get("company", "").strip()
            job_role = row.get("job_role", "").strip()
            location = row.get("location", "").strip()

            if not is_valid_email(email):
                self.skipped += 1
                self.on_log(f"[{idx}/{total}] SKIP invalid email: '{row.get('email','')}'")
                self._progress_update(total)
                continue

            if self.db.is_already_sent(email):
                self.skipped += 1
                self.on_log(f"[{idx}/{total}] SKIP duplicate (already sent): {email}")
                self._progress_update(total)
                continue

            context = dict(context_static)
            context.update({
                "hr_name": hr_name, "company": company,
                "job_role": job_role, "location": location,
            })

            subject = render(self.subject_template, context)
            body_html = text_to_html(render(self.template_text, context))
            sig_html = render(self.signature_html, context)
            full_html = f"{body_html}{sig_html}"

            last_error = ""
            success = False
            attempts = 0
            for attempt in range(1, max_retries + 1):
                if self._stop_flag.is_set():
                    break
                attempts = attempt
                try:
                    sender.send(email, subject, full_html, self.attachments)
                    success = True
                    break
                except SendError as e:
                    last_error = str(e)
                    self.on_log(f"[{idx}/{total}] Attempt {attempt} failed for {email}: {e}")
                    if attempt < max_retries:
                        self._sleep_with_checks(3)

            status = "sent" if success else "failed"
            self.db.record(email, hr_name, company, job_role, status, attempts, last_error)
            excel_io.append_log(self.log_csv, {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "email": email, "hr_name": hr_name, "company": company,
                "job_role": job_role, "status": status,
                "attempts": attempts, "error": last_error,
            })

            if success:
                self.sent += 1
                self.on_log(f"[{idx}/{total}] SENT to {email} ({company})")
            else:
                self.failed += 1
                self.failed_records.append({**row, "error": last_error})
                self.on_log(f"[{idx}/{total}] FAILED for {email}: {last_error}")

            self._progress_update(total)

            if idx < total and not self._stop_flag.is_set():
                delay = random.uniform(delay_min, delay_max)
                self.on_log(f"Waiting {delay:.1f}s before next email...")
                self._sleep_with_checks(delay)

        if self.failed_records:
            excel_io.export_failed(self.failed_records, self.failed_xlsx)
        stats = {"sent": self.sent, "failed": self.failed, "skipped": self.skipped}
        excel_io.export_summary(stats, self.summary_txt)
        self.on_log(
            f"Done. Sent={self.sent} Failed={self.failed} Skipped={self.skipped}. "
            f"Log: {self.log_csv.name}"
        )
        self.on_done(stats)

    def _progress_update(self, total):
        self.on_progress(self.sent, self.failed, self.skipped, total)
