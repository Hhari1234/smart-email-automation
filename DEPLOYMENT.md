# Deployment Checklist

This is a step-by-step checklist for deploying ResumeMailer to a remote
hosting platform (Render, Railway, Fly.io, a VPS with a reverse proxy,
etc.). HTTPS is assumed to be terminated by the platform or reverse
proxy — do **not** run your own TLS server.

## Before you deploy

1. **Pick a platform** that gives you a public HTTPS URL and a way to
   set environment variables (and ideally a persistent disk for the
   SQLite database and uploaded files).
2. **Push your code** to a Git repository (GitHub, GitLab, etc.).
3. **Create an `.env` locally** (do not commit it) with:
   - `APP_ENV=production`
   - `APP_USERNAME=your-username`
   - `APP_PASSWORD_HASH=<bcrypt hash, see README>`
   - `APP_SECRET_KEY=<64+ random chars>`
   - `SMTP_EMAIL` and `SMTP_APP_PASSWORD` (or Gmail API credentials)
4. **Generate the password hash** locally:
   ```bash
   python -c "from auth import hash_password; print(hash_password('YOUR_PASSWORD'))"
   ```

## Deploy steps

1. [ ] Create a hosting account (Render, Railway, Fly.io, etc.).
2. [ ] Connect your GitHub repository.
3. [ ] Configure environment variables on the platform:
   - `APP_ENV=production`
   - `APP_USERNAME`
   - `APP_PASSWORD_HASH`
   - `APP_SECRET_KEY`
   - `SMTP_EMAIL` (if using SMTP fallback)
   - `SMTP_APP_PASSWORD` (if using SMTP fallback)
   - `GMAIL_CREDENTIALS_FILE` (only if using Gmail API; the value is a
     path inside the container — you will need to mount the file
     separately because it is not in the repo)
   - `GMAIL_TOKEN_FILE` (same as above)
4. [ ] Configure the Gmail OAuth redirect URI on Google Cloud Console
   to match the platform's domain (only required if you are actually
   using the Gmail API; not needed for the SMTP fallback).
5. [ ] Configure SMTP if used (App Password, not your real Gmail
   password).
6. [ ] Deploy.
7. [ ] Open the HTTPS URL — you should land on `/login`.
8. [ ] Log in with `APP_USERNAME` and the password whose hash you put
   in `APP_PASSWORD_HASH`.
9. [ ] Test `GET /health` — it should return `{"status":"ok"}`.
10. [ ] Send a test email to yourself.
11. [ ] Test a small campaign (5–10 recipients).
12. [ ] Verify history (`/api/send/history` or the History modal).
13. [ ] Verify pause / resume / stop.
14. [ ] Verify attachments (resume + extra files).
15. [ ] Verify duplicate prevention (re-run the same small campaign —
    no second emails should be sent).

## Production notes

- The app binds to `0.0.0.0:${PORT}` when started with the included
  `Procfile`. Most platforms inject `PORT` automatically; if yours
  doesn't, set it explicitly.
- `APP_ENV=production` disables uvicorn's auto-reload, requires
  `APP_USERNAME`/`APP_PASSWORD_HASH`/`APP_SECRET_KEY` to be set,
  and marks the session cookie as `Secure` (so it only travels over
  HTTPS).
- The SQLite database lives at the project root by default. On
  platforms with ephemeral filesystems you must mount a persistent
  volume at the project root or override the database path.
- Never commit `credentials/credentials.json`, `credentials/token.json`,
  or your `.env` file. They are listed in `.gitignore` for that
  reason.
- HTTPS must be terminated by the platform or a reverse proxy. The
  app sets `Strict-Transport-Security` in production but does not
  speak TLS itself.
