# ResumeMailer

A premium web application for sending personalized job-application emails in bulk, with your resume attached, safely and without spamming.

## Features

- Modern 4-tab workflow: **Setup → Recipients → Template → Send**
- Import recipients from Excel/CSV (`HR Name, Company, Email, Job Role, Location`)
- `{{placeholder}}` templating for subject, body, and HTML signature
- Live email preview with desktop/mobile modes
- Send test email before running a real campaign
- **Gmail API** (OAuth2) preferred, automatic **SMTP** fallback (App Password)
- Email address validation before sending
- **Duplicate prevention** via a local SQLite database — an address that already succeeded won't be emailed again, even across app restarts
- Configurable **random delay** (default 5–15s) between sends
- **Pause / Resume / Stop** at any time, mid-run
- Up to 3 **automatic retries** per failed email
- Live progress bar + Sent/Failed/Skipped/Remaining counters
- Every send is logged to a timestamped CSV; failed emails are exported to `.xlsx`; a plain-text summary report is written at the end of each run
- Multiple attachments (resume + extra files) and custom HTML signature
- Premium dark-mode UI with glassmorphism, animated gradients, and smooth micro-interactions

## Technology Stack

- **Backend**: Python, FastAPI, Uvicorn
- **Frontend**: Vanilla HTML/CSS/JavaScript, Inter font
- **Database**: SQLite (duplicate prevention + send history)
- **Email**: Gmail API (OAuth2) / SMTP with App Password
- **Data I/O**: pandas, openpyxl

## Project Structure

```
ResumeMailer/
├── server.py                 # FastAPI backend entry point
├── app.py                    # Tkinter desktop app entry point (legacy)
├── gui.py                    # Original Tkinter GUI
├── mailer.py                 # Gmail API + SMTP sending backends
├── sender_worker.py          # Background thread: retries, delay, pause/stop
├── database.py               # SQLite duplicate-prevention + history
├── template_engine.py        # {{placeholder}} rendering
├── excel_io.py               # Recipient import + log/report export
├── validators.py             # Email validation
├── config.py                 # .env + settings.json handling
├── requirements.txt
├── .env.example
├── settings.example.json
├── README.md
├── frontend/
│   ├── index.html            # Premium SPA shell
│   ├── css/styles.css        # Design system + animations
│   └── js/app.js             # Frontend application logic
├── sample_data/
│   ├── recipients_sample.xlsx
│   └── email_template.txt
└── logs/                     # Auto-created: send logs, failed reports, summaries
```

## Installation

```bash
# Clone the repository
git clone https://github.com/Hhari1234/smart-email-automation.git
cd smart-email-automation/ResumeMailer

# Install Python dependencies
pip install -r requirements.txt
```

## Configuration

### 1. Environment Variables

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# SMTP fallback (used automatically if Gmail API isn't set up)
# Enable 2-Step Verification on your Google account, then create an App Password:
# https://myaccount.google.com/apppasswords
SMTP_EMAIL=your.email@gmail.com
SMTP_APP_PASSWORD=your-16-char-app-password

# Gmail API (preferred, optional)
# Only needed if you want to use Gmail API instead of SMTP.
# Leave as-is to use SMTP only.
GMAIL_CREDENTIALS_FILE=credentials/credentials.json
GMAIL_TOKEN_FILE=credentials/token.json
```

### 2. Local Settings

Copy `settings.example.json` to `settings.json` and update your personal details:

```bash
cp settings.example.json settings.json
```

Edit `settings.json` with your name, email, phone, LinkedIn, resume path, and sending preferences.

### 3. Optional: Gmail API Setup

If you want to use Gmail API instead of SMTP:

1. Go to https://console.cloud.google.com/ → create a project
2. Enable the **Gmail API**
3. Create OAuth **Client ID** credentials → Application type: **Desktop App**
4. Download the JSON and save it as `credentials/credentials.json`
5. On first send, a browser window will open for you to grant access; a `credentials/token.json` is then cached.

If Gmail API isn't configured, the app automatically falls back to SMTP.

## Running the Application

### Web Version (Recommended)

```bash
python server.py
```

Then open http://127.0.0.1:8000 in your browser.

### Desktop Version (Legacy Tkinter)

```bash
python app.py
```

## Using the App

1. **Setup tab** — enter your name/email/phone/LinkedIn, upload your resume, optionally add extra attachments, set delay/retry behavior, click **Save Settings**.
2. **Recipients tab** — click **Import File...** and choose your Excel/CSV, or **Download Sample Template** to see the expected format.
3. **Template tab** — write your email using the `{{placeholder}}` chips, click **Preview Email**, then **Send Test Email to Myself** to confirm it looks right.
4. **Send tab** — click **Start Sending**. Use **Pause/Resume/Stop** anytime.

When it finishes, check the `logs/` folder for the full send log, any failed-email report, and the summary.

## Notes on Responsible Use

- Gmail enforces daily sending limits (~500/day for regular Gmail accounts, higher for Google Workspace). Sending too fast or to too many unknown addresses can trigger spam flags — keep the delay settings reasonable.
- The app only emails addresses that pass validation and skips any address it has already successfully emailed, so re-running after an interruption is safe.
- This tool is intended for personal job-search outreach to individually named contacts — not for unsolicited mass marketing.

## Troubleshooting

- **"SMTP_EMAIL / SMTP_APP_PASSWORD not set"** → check your `.env` file.
- **"Gmail API credentials.json not found"** → either add the file or ensure SMTP is configured in `.env`.
- **Emails landing in spam** → increase the delay range, personalize the template further, and avoid sending to very large lists in one sitting.
- **`ModuleNotFoundError`** → run `pip install -r requirements.txt`.

## License

MIT
