# Deployment

ResumeMailer is a **Python FastAPI + Uvicorn** web application — it is **not**
a static site. The backend serves the frontend AND runs the email-sending
logic, so the deployment target must run a long-lived Python process with
HTTPS, environment variables, and persistent storage.

## Architecture

```
HTTPS URL (platform TLS)
        ↓
uvicorn server:app --host 0.0.0.0 --port $PORT
  ├── FastAPI app (server.py)
  ├── SQLite database (duplicate prevention + history + templates/drafts/campaigns)
  ├── In-memory SendWorker (single process)
  └── Static frontend (index.html, login.html, /static/*)
```

## Requirements

- Python 3.10+
- A hosting platform that supports Python, FastAPI/Uvicorn, HTTPS,
  environment variables, and long-running web processes (Render, Railway,
  Fly.io, or a VPS with a reverse proxy).
- A persistent volume for the SQLite database, uploads, and logs
  (see "Persistent Storage" below).

## Environment Variables

Set these on the hosting platform's secret/environment-variable system.
**Never commit them to Git.**

| Variable | Required | Description |
|----------|----------|-------------|
| `APP_ENV` | yes | Set to `production` for any public deployment. |
| `APP_USERNAME` | yes (production) | Login username. |
| `APP_PASSWORD_HASH` | yes (production) | bcrypt hash of the password. |
| `APP_SECRET_KEY` | yes (production) | Long random string used to sign session cookies. |
| `APP_SESSION_HOURS` | no | Session lifetime in hours (default 12). |
| `CORS_ALLOW_ORIGINS` | no | Comma-separated extra CORS origins. Leave empty for same-origin. |
| `SMTP_EMAIL` | no | Sender email for SMTP fallback. |
| `SMTP_APP_PASSWORD` | no | SMTP app password for the fallback. |
| `GMAIL_CREDENTIALS_FILE` | no | Path to OAuth credentials JSON. |
| `GMAIL_TOKEN_FILE` | no | Path to cached OAuth token JSON. |

Generate the password hash locally:
```bash
python -c "from auth import hash_password; print(hash_password('YOUR_PASSWORD'))"
```

Generate the secret key locally:
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Deployment Steps

### Render

1. Create a Render account and connect your GitHub repository.
2. Create a **Web Service** (Python 3) from
   `https://github.com/Hhari1234/smart-email-automation`.
3. Set **Build Command**: `pip install -r requirements.txt`
4. Set **Start Command**:
   `APP_ENV=production uvicorn server:app --host 0.0.0.0 --port $PORT`
5. Add the required environment variables.
6. Add a persistent **disk** (e.g. 1 GB) mounted at the project root.
7. Set **Health Check Path**: `/health`
8. Deploy.

The included `render.yaml` captures this configuration.

### Railway

1. Create a Railway project and connect the GitHub repository.
2. Railway auto-detects Python and uses `railway.toml` for configuration.
3. Set the required environment variables.
4. Add a persistent **volume** for the project root.
5. Run `railway up` or push to trigger a deploy.

### Fly.io

Create a `Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
```

Then `fly launch`, set the environment variables, and `fly deploy`.

### VPS / Reverse Proxy

```bash
pip install -r requirements.txt
APP_ENV=production uvicorn server:app --host 127.0.0.1 --port 8000
```

Configure your reverse proxy (nginx, Caddy, etc.) to terminate TLS and
proxy to `http://127.0.0.1:8000`.

## Gmail Configuration

The Gmail API code path is implemented and will be used when
`credentials/credentials.json` is present. To use it:

1. Go to https://console.cloud.google.com/ → create a project.
2. Enable the **Gmail API**.
3. Create OAuth **Client ID** credentials → Application type: **Desktop App**.
4. Download the JSON and save it as `credentials/credentials.json`.
5. On first send, a browser window opens for you to grant access; the
   resulting token is cached in `credentials/token.json`.

**Important:** The OAuth flow uses `flow.run_local_server(port=0)`, which
opens a browser on the machine running the app. On a remote server this
cannot work interactively — use the **SMTP fallback** instead, or run the
OAuth flow locally first so a `token.json` is cached, then deploy the
cached token.

If Gmail API is not configured, the app automatically falls back to SMTP
using `SMTP_EMAIL` / `SMTP_APP_PASSWORD`.

## SMTP Configuration

1. Enable 2-Step Verification on your Google account.
2. Create an App Password at https://myaccount.google.com/apppasswords.
3. Set `SMTP_EMAIL` to your Gmail address and `SMTP_APP_PASSWORD` to the
   16-character app password in the hosting platform's environment.

## Persistent Storage

The SQLite database (`resumemailer.db`), uploaded attachments, and send
logs live in the working directory. On platforms with ephemeral filesystems
you **must** mount a persistent volume at the project root or override the
database path via environment. Without persistence:

- A process restart clears send history and duplicate-prevention state.
- Uploaded attachments are lost.

## Worker Limitations

The `SendWorker` runs on a single background thread inside a single
process. Do **not** configure multiple application workers
(`--workers > 1`) unless you change the architecture to support it.

A process restart terminates any in-memory campaign; there is no
automatic restart-resume across deploys.

## Security

- Single-user login (username + bcrypt password) with a server-side signed
  session cookie (HttpOnly, SameSite=Lax, Secure in production) and a
  configurable session lifetime.
- CSRF token required on every state-changing API request.
- Login rate limiting: 5 failures per IP per 10 minutes and 8 failures per
  username per 15 minutes, with `429` responses.
- Same-origin deployment by default. CORS is disabled unless
  `CORS_ALLOW_ORIGINS` is set, and is never combined with
  `allow_origins=["*"]`.
- Security headers: `X-Content-Type-Options`, `Referrer-Policy`,
  `X-Frame-Options`, a strict `Content-Security-Policy` on HTML responses,
  and `Strict-Transport-Security` in production.
- File uploads are limited to 25 MB, validated against a per-kind extension
  allowlist, written to a generated server-side filename, validated to stay
  inside the uploads directory, and cleaned up on failure.
- The SQLite database, OAuth token file, and `.env` are never served as
  static files.
- Python tracebacks are never returned to the user; they are logged
  server-side.
- Production refuses to start unless `APP_USERNAME`, `APP_PASSWORD_HASH`,
  and `APP_SECRET_KEY` are set.

## Testing

After deployment:

1. Open the HTTPS URL — you should land on `/login`.
2. Log in with `APP_USERNAME` and the password whose hash you configured.
3. Test `GET /health` — it should return `{"status":"ok"}`.
4. Test the dashboard loads.
5. Paste recipients, parse, merge.
6. Preview the email.
7. Send a test email to a configured test address.
8. Verify history.
9. Verify logout.

## Troubleshooting

- **"Refusing to start: APP_USERNAME, APP_PASSWORD_HASH and APP_SECRET_KEY
  must be set when APP_ENV=production"** → set those three values on the
  platform's environment.
- **"Authentication required"** on every request → log in at `/login`.
- **"CSRF token missing or invalid"** → your session was lost (cookie
  expired). Refresh and log in again.
- **"SMTP_EMAIL / SMTP_APP_PASSWORD not set"** → configure SMTP on the
  platform's environment.
- **"Gmail API credentials.json not found"** → either add the file or
  ensure SMTP is configured.
- **`ModuleNotFoundError`** → the platform did not install dependencies;
  check the build command.