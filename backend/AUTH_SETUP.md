# ESGIntel — Login & Authentication Setup

This document explains the login backend that was added to ESGIntel and how to
take it from **dev mode** (works instantly, no secrets) to **live** (real
Google/X sign-in and real verification emails).

## What was built

A self-contained auth system in **`backend/auth.py`**, mounted on the existing
FastAPI app. No Firebase or third-party auth service required.

| Feature | Endpoint | Notes |
|---|---|---|
| Email + password sign-up | `POST /api/auth/signup` | Creates an unverified user, emails a 6-digit code |
| Email + password sign-in | `POST /api/auth/login` | Returns a JWT; if email isn't verified, re-sends a code |
| Send verification code | `POST /api/auth/send-code` | Used by "Resend code" and password recovery |
| Confirm code | `POST /api/auth/verify-code` | Validates the code, marks email verified, returns a JWT |
| Current user | `GET /api/auth/me` | Restores the session from the `Bearer` token |
| Sign out | `POST /api/auth/logout` | Stateless — client discards the token |
| **Continue with Google** | `GET /api/auth/google/login` → `/google/callback` | Google OAuth 2.0 (authorization-code) |
| **Continue with X** | `GET /api/auth/x/login` → `/x/callback` | X/Twitter OAuth 2.0 (PKCE); also sets `x_verified` |
| Provider status | `GET /api/auth/config` | Tells the UI which providers are live vs dev |

**Sessions** are stateless JWTs (HS256), stored by the browser in
`localStorage` under `esgIntel_token` and re-validated against `/api/auth/me` on
every page load.

**Security**: passwords are hashed with PBKDF2-HMAC-SHA256 (200k iterations,
per-user salt); codes are stored hashed, expire after 10 minutes, and lock after
5 wrong attempts.

## How to run

```bash
cd backend
source venv/bin/activate          # use your existing venv
uvicorn app:app --reload --port 8000
```

Then open **http://localhost:8000/app** in your browser.
> Important: open it via `http://localhost:8000/app`, **not** by double-clicking
> the HTML file. The frontend calls the API at a relative path (`/api/auth/...`),
> which only works when the page is served by the backend.

## Dev mode (default — nothing to configure)

With no credentials set, everything still works so you can demo the full flow:

- **Email codes**: instead of sending an email, the 6-digit code is printed in
  the server console **and** shown on the verification screen (orange box).
- **Google / X buttons**: skip the real provider and sign you in as a demo user
  (`demo@example.com`), so you can see the post-login redirect end-to-end.

## Going live

Edit `backend/.env` (already scaffolded with blank placeholders) and restart.

### 1. Session secret (do this first)

```bash
JWT_SECRET=<paste output of: openssl rand -hex 32>
```

### 2. Real verification emails (Gmail)

1. Enable 2-Step Verification on the Gmail account.
2. Create an **App Password**: Google Account → Security → App passwords.
3. Fill in `.env`:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USER=yourname@gmail.com
SMTP_PASS=the-16-char-app-password
SMTP_FROM=yourname@gmail.com
SMTP_FROM_NAME=ESGIntel
```

Once `SMTP_USER`/`SMTP_PASS` are set, codes are emailed and no longer shown
on screen.

### 3. Google sign-in

1. Go to <https://console.cloud.google.com> → APIs & Services → Credentials.
2. Configure the OAuth consent screen (External, add your email as a test user).
3. Create an **OAuth client ID** → type **Web application**.
4. Add an **Authorized redirect URI**:
   `http://localhost:8000/api/auth/google/callback`
5. Fill in `.env`:

```env
GOOGLE_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=...
```

### 4. X (Twitter) sign-in

1. Go to <https://developer.x.com> → your Project → **User authentication settings**.
2. App permissions: *Read*; Type of App: **Web App** (confidential client).
3. Set the **Callback URI**: `http://localhost:8000/api/auth/x/callback`
4. Copy the **OAuth 2.0 Client ID and Client Secret** into `.env`:

```env
X_CLIENT_ID=...
X_CLIENT_SECRET=...
```

### 5. Deploying somewhere other than localhost

Set `APP_BASE_URL` to your real origin (e.g. `https://app.esgintel.io`) and add
the matching `/api/auth/google/callback` and `/api/auth/x/callback` URIs in the
Google and X consoles.

## Notes

- The old Firebase code in the HTML is now dormant (the config placeholders are
  never filled, so it never initialises). All auth flows go through this backend.
- X does not reliably expose a user's email, so X accounts are stored with a
  stable internal identifier and flagged `x_verified = 1`.
- User records live in `backend/esg_intel.db` (tables `users`, `email_codes`).
  The account whose email matches the `ADMIN_EMAIL` environment variable
  (see `.env`) is auto-flagged as admin on login.
