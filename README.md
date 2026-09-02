# ResumeMailer

A premium web application for sending personalized job-application emails in bulk, with your resume attached, safely and without spamming.

## Features

### Core Workflow
- Modern 4-tab workflow: **Setup → Recipients → Template → Send**
- Import recipients from Excel/CSV (`HR Name, Company, Email, Job Role, Location`)
- **Paste Email Addresses** — paste a list of emails directly (newline, comma, or semicolon separated)
- Supports `Name <email@example.com>` format in pasted lists
- Smart parsing shows **valid**, **duplicate**, and **invalid** counts before merging
- `{{placeholder}}` templating for subject, body, and HTML signature
- **Fallback values**: use `{{name|there}}` to show a default when a field is missing
- Live email preview with desktop/mobile modes
- Send test email before running a real campaign

### Sending & Safety
- **Gmail API** (OAuth2) preferred, automatic **SMTP** fallback (App Password)
- Email address validation before sending
- **Duplicate prevention** via a local SQLite database — an address that already succeeded won't be emailed again, even across app restarts
- Configurable **random delay** (default 5–15s) between sends
- **Pause / Resume / Stop** at any time, mid-run
- Up to 3 **automatic retries** per failed email
- Live progress bar + Sent/Failed/Skipped/Remaining counters
- **Pre-send confirmation screen** with campaign summary before starting
- Every send is logged to a timestamped CSV; failed emails are exported to `.xlsx`; a plain-text summary report is written at the end of each run
- Multiple attachments (resume + extra files) and custom HTML signature
- Premium dark-mode UI with glassmorphism, animated gradients, and smooth micro-interactions

### Templates & Drafts
- **Template Library** — save, load, duplicate, and delete reusable email templates
- **Drafts** — save partial campaigns and resume them later
- **Campaign History** — view past campaigns with status and recipient details
- Export campaign recipients to CSV

## Technology Stack

- **Backend**: Python, FastAPI, Uvicorn
- **Frontend**: Vanilla HTML/CSS/JavaScript, Inter font
- **Database**: SQLite (duplicate prevention + send history + templates + drafts + campaigns)
- **Email**: Gmail API (OAuth2) / SMTP with App Password
- **Data I/O**: pandas, openpyxl

## Project Structure

```
ResumeMailer/
├── server.py                 # FastAPI backend entry point
├── auth.py                   # Single-user login, sessions, CSRF, rate limit
├── app.py                    # Tkinter desktop app entry point (legacy)
├── gui.py                    # Original Tkinter GUI
├── mailer.py                 # Gmail API + SMTP sending backends
├── sender_worker.py          # Background thread: retries, delay, pause/stop
├── database.py               # SQLite duplicate-prevention + history + templates + drafts + campaigns
├── template_engine.py        # {{placeholder}} rendering with fallback support
├── excel_io.py               # Recipient import + log/report export
├── recipient_parser.py       # Smart bulk email parser for pasted text
├── validators.py             # Email validation
├── config.py                 # .env + settings.json handling
├── requirements.txt
├── Procfile                  # Production start command
├── .env.example
├── settings.example.json
├── README.md
├── DEPLOYMENT.md
├── frontend/
│   ├── index.html            # Premium SPA shell
│   ├── login.html            # Sign-in page
│   ├── css/styles.css        # Design system + animations
│   ├── css/login.css         # Login page styles
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

Edit `.env`. The most important variables:

```env
# Set to "production" for any public deployment.
APP_ENV=development

# Long random string used to sign session cookies.
APP_SECRET_KEY=

# Login username and bcrypt password hash (see "Authentication" below).
APP_USERNAME=
APP_PASSWORD_HASH=

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

### 2. Authentication (single-user login)

The web UI is protected by a username + password login. When `APP_USERNAME`,
`APP_PASSWORD_HASH` and `APP_SECRET_KEY` are all set in `.env`, every sensitive
API endpoint requires an authenticated session. When none of those are set,
the app runs with auth disabled (the original local workflow is unchanged).

**Never put a plaintext password in source code or in `.env`.** Generate a
bcrypt hash and put the hash in `.env` instead.

From the project root:

```bash
python -c "from auth import hash_password; print(hash_password('YOUR_PASSWORD'))"
```

Copy the printed hash into `APP_PASSWORD_HASH` in `.env`. Then set
`APP_USERNAME` and `APP_SECRET_KEY` (generate the secret with
`python -c "import secrets; print(secrets.token_urlsafe(48))"`).

Once configured, the only public endpoints are `/login`, `/health`,
`/api/health`, `/api/auth/*`, and the static frontend assets. Every
sensitive endpoint returns `401` for unauthenticated requests and
`403` if the CSRF token is missing on state-changing requests.

To run the web app **without** authentication (legacy local mode), simply
leave the three auth variables empty.

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
2. **Recipients tab** — either:
   - Click **Browse Files** to import an Excel/CSV file, or
   - Paste a list of email addresses into the textarea and click **Parse Emails**. Review the valid/duplicate/invalid counts, then click **Merge into Recipients**.
3. **Template tab** — write your email using the `{{placeholder}}` chips, click **Preview Email**, then **Send Test Email** to confirm it looks right. Use the **Templates** button to save/load templates.
4. **Send tab** — review the campaign summary, then click **Confirm & Start**. Use **Pause/Resume/Stop** anytime.

When it finishes, check the `logs/` folder for the full send log, any failed-email report, and the summary.

## Recipient Parser

The smart parser supports multiple formats:

```
hr@company1.com
careers@company2.com
recruiter@company3.com
John <john@company.com>
Recruiter Name <recruiter@company3.com>
hr@company1.com, careers@company2.com, recruiter@company3.com
hr@company1.com; careers@company2.com; recruiter@company3.com
```

After parsing:
- **Valid** emails are ready to merge
- **Duplicates** are detected and skipped
- **Invalid** entries are shown for review

## Placeholder Fallback

Use the `|` syntax for fallback values:

```
{{name|there}}
```

If `name` exists in the recipient data, it is used. Otherwise, `there` is shown.

## Notes on Responsible Use

- Gmail enforces daily sending limits (~500/day for regular Gmail accounts, higher for Google Workspace). Sending too fast or to too many unknown addresses can trigger spam flags — keep the delay settings reasonable.
- The app only emails addresses that pass validation and skips any address it has already successfully emailed, so re-running after an interruption is safe.
- This tool is intended for personal job-search outreach to individually named contacts — not for unsolicited mass marketing.

## Security

This application sends real emails. **Do not expose an unauthenticated
instance to the public internet.** Use authentication and HTTPS for any
remote deployment. **Never commit Gmail OAuth credentials, SMTP
passwords, or your `APP_PASSWORD_HASH`/`APP_SECRET_KEY` to Git.**

What the deployment is hardened with:

- Single-user login (username + bcrypt password) with a server-side
  signed session cookie (HttpOnly, SameSite=Lax, Secure in production)
  and a `12` hour default session lifetime.
- CSRF token required on every state-changing API request when
  authentication is enabled.
- Login rate limiting: 5 failures per IP per 10 minutes and
  8 failures per username per 15 minutes, with `429` responses.
- Same-origin deployment by default. CORS is disabled unless
  `CORS_ALLOW_ORIGINS` is set, and is never combined with
  `allow_origins=["*"]`.
- Security headers: `X-Content-Type-Options`, `Referrer-Policy`,
  `X-Frame-Options`, a strict `Content-Security-Policy` on HTML
  responses, and `Strict-Transport-Security` in production.
- File uploads are limited to 25 MB, validated against a per-kind
  extension allowlist, written to a generated server-side filename,
  validated to stay inside the uploads directory, and cleaned up on
  failure.
- The SQLite database, OAuth token file, and `.env` are never served
  as static files.
- Python tracebacks are never returned to the user; they are logged
  server-side.

See [DEPLOYMENT.md](DEPLOYMENT.md) for the step-by-step remote
deployment checklist.

## Production Deployment

This application is a **Python FastAPI + Uvicorn backend**, not a static
site. The backend serves the frontend AND runs the email-sending logic,
so the deployment target must run a long-lived Python process with
HTTPS, environment variables, and persistent storage.

### Architecture

```
HTTPS URL (platform TLS)
        ↓
uvicorn server:app --host 0.0.0.0 --port $PORT
  ├── FastAPI app (server.py)
  ├── SQLite database (duplicate prevention + history + templates/drafts/campaigns)
  ├── In-memory SendWorker (single process)
  └── Static frontend (index.html, login.html, /static/*)
```

### Hosting Platforms

Any platform that supports **Python, FastAPI/Uvicorn, HTTPS, environment
variables, and long-running web processes** works:

| Platform | Build Command | Start Command |
|----------|---------------|---------------|
| Render | `pip install -r requirements.txt` | `APP_ENV=production uvicorn server:app --host 0.0.0.0 --port $PORT` |
| Railway | auto-detected | `uvicorn server:app --host 0.0.0.0 --port $PORT` (see `railway.toml`) |
| Fly.io | via Dockerfile | `uvicorn server:app --host 0.0.0.0 --port $PORT` |
| VPS / reverse proxy | `pip install -r requirements.txt` | `APP_ENV=production uvicorn server:app --host 0.0.0.0 --port $PORT` |

See `Procfile`, `render.yaml`, and `railway.toml` for ready-to-use
configurations.

### Required Environment Variables

Set these on the hosting platform's secret/environment-variable system
(never commit them to Git):

```env
# --- Authentication (required for production) ---
APP_ENV=production
APP_USERNAME=your-username
APP_PASSWORD_HASH=<bcrypt hash of your password>
APP_SECRET_KEY=<64+ random chars>

# --- SMTP fallback (used automatically if Gmail API isn't set up) ---
SMTP_EMAIL=your.email@gmail.com
SMTP_APP_PASSWORD=your-16-char-app-password

# --- Gmail API (preferred, optional) ---
GMAIL_CREDENTIALS_FILE=credentials/credentials.json
GMAIL_TOKEN_FILE=credentials/token.json
```

Generate the password hash locally:
```bash
python -c "from auth import hash_password; print(hash_password('YOUR_PASSWORD'))"
```

Generate the secret key locally:
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Persistent Storage

The SQLite database (`resumemailer.db`), uploaded attachments, and send
logs live in the working directory. On platforms with ephemeral filesystems
you **must** mount a persistent volume at the project root or override the
database path via environment. Without persistence, a process restart
clears send history and duplicate-prevention state.

### Worker Limitations

The `SendWorker` runs on a single background thread inside a single
process. Do **not** configure multiple application workers
(`--workers > 1`) unless you change the architecture to support it.
A process restart terminates any in-memory campaign; there is no
automatic restart-resume across deploys.

### HTTPS

HTTPS must be terminated by the platform or a reverse proxy. The app
sets `Strict-Transport-Security` in production but does not speak TLS
itself.

### Gmail API status

The Gmail API code path is implemented and will be used when
`credentials/credentials.json` is present, but **real Gmail API sending
has not been verified end-to-end** because no live credentials were
available during development. To use it, you must:

1. Create a Google Cloud project and enable the **Gmail API**.
2. Create an OAuth **Desktop App** client and download the JSON to
   `credentials/credentials.json`.
3. Make sure the OAuth client's redirect URI matches what the app
   uses for the local OAuth flow.
4. Trigger any send — the first call will open a browser window for
   you to grant access; the resulting token is cached in
   `credentials/token.json`.

If the Gmail API is not configured, the app automatically falls back
to SMTP using `SMTP_EMAIL` / `SMTP_APP_PASSWORD` from `.env`.

## Troubleshooting

- **"SMTP_EMAIL / SMTP_APP_PASSWORD not set"** → check your `.env` file.
- **"Gmail API credentials.json not found"** → either add the file or ensure SMTP is configured in `.env`.
- **"Refusing to start: APP_USERNAME, APP_PASSWORD_HASH and APP_SECRET_KEY must be set when APP_ENV=production"** → set those three values in `.env` (or unset `APP_ENV`).
- **"Authentication required"** on every request → log in at `/login`. If you intentionally want to run without auth, clear all three of `APP_USERNAME`, `APP_PASSWORD_HASH`, `APP_SECRET_KEY` from `.env`.
- **"CSRF token missing or invalid"** → your session was lost (cookie expired). Refresh and log in again.
- **Emails landing in spam** → increase the delay range, personalize the template further, and avoid sending to very large lists in one sitting.
- **`ModuleNotFoundError`** → run `pip install -r requirements.txt`.

## License

MIT
