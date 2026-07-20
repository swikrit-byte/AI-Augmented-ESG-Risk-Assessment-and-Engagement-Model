"""
ESGIntel — Authentication backend
==================================
A self-contained auth system for the ESGIntel platform. No third-party auth
service required. Provides:

  • Email + password sign-up / sign-in
  • Email verification via a 6-digit code (SMTP, with a dev fallback)
  • "Continue with Google"  — Google OAuth 2.0 (authorization-code flow)
  • "Continue with X"       — X / Twitter OAuth 2.0 (PKCE flow), also used as
                              an account-verification signal (x_verified)
  • Stateless sessions via signed JWTs (HS256, hand-rolled, stdlib only)

Everything degrades gracefully: if SMTP / Google / X credentials are not set
in the environment, the relevant flow runs in DEV MODE so the whole login
experience is testable end-to-end without any secrets. See AUTH_SETUP.md.

Mounted onto the main FastAPI app via `app.include_router(auth_router)`.
"""

import os
import re
import json
import hmac
import time
import base64
import hashlib
import secrets
import sqlite3
import smtplib
import logging
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

log = logging.getLogger("esgintel.auth")
logging.basicConfig(level=logging.INFO)

# ─────────────────────────────────────────────
# Configuration (all via environment / .env)
# ─────────────────────────────────────────────
DB_PATH        = Path(__file__).parent / "esg_intel.db"
APP_BASE_URL   = os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/")
FRONTEND_PATH  = "/app"                              # where the SPA is served
JWT_SECRET     = os.getenv("JWT_SECRET", "dev-insecure-change-me")
JWT_TTL_SECONDS = int(os.getenv("JWT_TTL_SECONDS", str(60 * 60 * 24 * 7)))  # 7 days
CODE_TTL_SECONDS = 10 * 60                            # verification code lifetime
CODE_MAX_ATTEMPTS = 5
ADMIN_EMAIL    = os.getenv("ADMIN_EMAIL", "")

# SMTP (email delivery)
SMTP_HOST      = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT      = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER      = os.getenv("SMTP_USER", "")
SMTP_PASS      = os.getenv("SMTP_PASS", "")
SMTP_FROM      = os.getenv("SMTP_FROM", SMTP_USER)
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "ESGIntel")
EMAIL_LIVE     = bool(SMTP_USER and SMTP_PASS)

# Google OAuth
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_LIVE          = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)
GOOGLE_REDIRECT      = f"{APP_BASE_URL}/api/auth/google/callback"

# X / Twitter OAuth 2.0
X_CLIENT_ID     = os.getenv("X_CLIENT_ID", "")
X_CLIENT_SECRET = os.getenv("X_CLIENT_SECRET", "")
X_LIVE          = bool(X_CLIENT_ID and X_CLIENT_SECRET)
X_REDIRECT      = f"{APP_BASE_URL}/api/auth/x/callback"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

router = APIRouter(prefix="/api/auth", tags=["auth"])
auth_router = router  # exported name

# In-memory store for OAuth state / PKCE verifiers (fine for single-process dev)
_oauth_state: dict[str, dict] = {}


# ─────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id             TEXT PRIMARY KEY,
            email          TEXT UNIQUE NOT NULL,
            first_name     TEXT,
            last_name      TEXT,
            display_name   TEXT,
            company        TEXT,
            role           TEXT,
            plan           TEXT    DEFAULT 'free',
            password_hash  TEXT,
            provider       TEXT    DEFAULT 'email',
            photo_url      TEXT,
            email_verified INTEGER DEFAULT 0,
            x_verified     INTEGER DEFAULT 0,
            x_handle       TEXT,
            onboarding_done INTEGER DEFAULT 0,
            created_at     TEXT NOT NULL,
            last_login     TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_codes (
            email      TEXT NOT NULL,
            code_hash  TEXT NOT NULL,
            purpose    TEXT DEFAULT 'verify',
            expires_at REAL NOT NULL,
            attempts   INTEGER DEFAULT 0,
            created_at REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# Password hashing (PBKDF2-HMAC-SHA256, stdlib)
# ─────────────────────────────────────────────
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 200_000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ─────────────────────────────────────────────
# JWT (HS256) — hand-rolled, no external deps
# ─────────────────────────────────────────────
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(seg: str) -> bytes:
    pad = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad)


def make_jwt(payload: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    body = {**payload, "iat": now, "exp": now + JWT_TTL_SECONDS}
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(body, separators=(",", ":")).encode())
    signing_input = f"{h}.{p}".encode()
    sig = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url(sig)}"


def decode_jwt(token: str) -> Optional[dict]:
    try:
        h, p, s = token.split(".")
        signing_input = f"{h}.{p}".encode()
        expected = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url(expected), s):
            return None
        payload = json.loads(_b64url_decode(p))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


# ─────────────────────────────────────────────
# Verification codes
# ─────────────────────────────────────────────
def _hash_code(email: str, code: str) -> str:
    return hashlib.sha256(f"{email}:{code}:{JWT_SECRET}".encode()).hexdigest()


def create_and_send_code(email: str, purpose: str = "verify") -> Optional[str]:
    """Generate a 6-digit code, persist its hash, email it. Returns the plain
    code only in dev mode (no SMTP configured) so the flow stays testable."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    conn = get_db()
    conn.execute("DELETE FROM email_codes WHERE email = ? AND purpose = ?", (email, purpose))
    conn.execute(
        "INSERT INTO email_codes (email, code_hash, purpose, expires_at, attempts, created_at) "
        "VALUES (?,?,?,?,0,?)",
        (email, _hash_code(email, code), purpose, time.time() + CODE_TTL_SECONDS, time.time()),
    )
    conn.commit()
    conn.close()

    sent = send_code_email(email, code, purpose)
    if not sent:
        log.info("📧 [DEV MODE] Verification code for %s = %s", email, code)
        return code  # surface to client for dev convenience
    return None


def verify_code(email: str, code: str, purpose: str = "verify") -> bool:
    conn = get_db()
    row = conn.execute(
        "SELECT rowid, code_hash, expires_at, attempts FROM email_codes "
        "WHERE email = ? AND purpose = ? ORDER BY created_at DESC LIMIT 1",
        (email, purpose),
    ).fetchone()
    if not row:
        conn.close()
        return False
    if row["attempts"] >= CODE_MAX_ATTEMPTS or row["expires_at"] < time.time():
        conn.execute("DELETE FROM email_codes WHERE rowid = ?", (row["rowid"],))
        conn.commit()
        conn.close()
        return False
    ok = hmac.compare_digest(row["code_hash"], _hash_code(email, code))
    if ok:
        conn.execute("DELETE FROM email_codes WHERE email = ? AND purpose = ?", (email, purpose))
    else:
        conn.execute("UPDATE email_codes SET attempts = attempts + 1 WHERE rowid = ?", (row["rowid"],))
    conn.commit()
    conn.close()
    return ok


def send_code_email(email: str, code: str, purpose: str) -> bool:
    if not EMAIL_LIVE:
        return False
    subject = "Your ESGIntel verification code"
    if purpose == "reset":
        subject = "Reset your ESGIntel password"
    html = f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:480px;margin:auto;padding:32px;border:1px solid #e5e7eb;border-radius:12px">
  <h2 style="color:#16453a;margin:0 0 4px">ESGIntel</h2>
  <p style="color:#6b7280;margin:0 0 24px;font-size:13px">AI-Assisted ESG Due Diligence Platform</p>
  <p style="font-size:15px;color:#111">Your verification code is:</p>
  <div style="font-size:34px;font-weight:800;letter-spacing:10px;color:#16453a;background:#f1f5f4;border-radius:10px;padding:18px;text-align:center;margin:12px 0">{code}</div>
  <p style="font-size:13px;color:#6b7280">This code expires in 10 minutes. If you didn't request it, you can safely ignore this email.</p>
</div>"""
    msg = MIMEText(html, "html")
    msg["Subject"] = subject
    msg["From"] = formataddr((SMTP_FROM_NAME, SMTP_FROM))
    msg["To"] = email
    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as s:
                s.login(SMTP_USER, SMTP_PASS)
                s.sendmail(SMTP_FROM, [email], msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
                s.sendmail(SMTP_FROM, [email], msg.as_string())
        log.info("📧 Verification code emailed to %s", email)
        return True
    except Exception as e:
        log.error("SMTP send failed for %s: %s", email, e)
        return False


# ─────────────────────────────────────────────
# User helpers
# ─────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def user_public(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "firstName": row["first_name"],
        "lastName": row["last_name"],
        "displayName": row["display_name"],
        "company": row["company"],
        "role": row["role"],
        "plan": row["plan"],
        "provider": row["provider"],
        "photoURL": row["photo_url"],
        "emailVerified": bool(row["email_verified"]),
        "xVerified": bool(row["x_verified"]),
        "xHandle": row["x_handle"],
        "onboardingDone": bool(row["onboarding_done"]),
        "isAdmin": row["email"] == ADMIN_EMAIL,
    }


def get_user_by_email(email: str) -> Optional[sqlite3.Row]:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
    conn.close()
    return row


def get_user_by_id(uid: str) -> Optional[sqlite3.Row]:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()
    return row


def touch_login(uid: str):
    conn = get_db()
    conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (_now(), uid))
    conn.commit()
    conn.close()


def upsert_oauth_user(email: str, name: str, provider: str,
                      photo_url: str = "", x_handle: str = "") -> sqlite3.Row:
    """Create or update a user signing in via an OAuth provider."""
    email = email.lower()
    existing = get_user_by_email(email)
    parts = (name or email.split("@")[0]).split(" ", 1)
    first = parts[0]
    last = parts[1] if len(parts) > 1 else ""
    conn = get_db()
    if existing:
        conn.execute(
            "UPDATE users SET last_login=?, photo_url=COALESCE(NULLIF(?,''),photo_url), "
            "email_verified=1, x_verified=CASE WHEN ?='x' THEN 1 ELSE x_verified END, "
            "x_handle=COALESCE(NULLIF(?,''),x_handle) WHERE email=?",
            (_now(), photo_url, provider, x_handle, email),
        )
    else:
        uid = "usr_" + secrets.token_hex(12)
        conn.execute(
            "INSERT INTO users (id,email,first_name,last_name,display_name,plan,provider,"
            "photo_url,email_verified,x_verified,x_handle,created_at,last_login) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uid, email, first, last, name or first, "free", provider, photo_url,
             1, 1 if provider == "x" else 0, x_handle, _now(), _now()),
        )
    conn.commit()
    conn.close()
    return get_user_by_email(email)


def current_user(authorization: Optional[str]) -> sqlite3.Row:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    payload = decode_jwt(authorization.split(" ", 1)[1])
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    row = get_user_by_id(payload.get("sub", ""))
    if not row:
        raise HTTPException(401, "User not found")
    return row


# ─────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────
class SignupReq(BaseModel):
    firstName: str
    lastName: str = ""
    email: str
    password: str
    company: str = ""
    role: str = ""


class LoginReq(BaseModel):
    email: str
    password: str


class CodeReq(BaseModel):
    email: str
    purpose: str = "verify"


class VerifyReq(BaseModel):
    email: str
    code: str
    purpose: str = "verify"


# ─────────────────────────────────────────────
# Routes — config / status
# ─────────────────────────────────────────────
@router.get("/config")
async def auth_config():
    """Lets the frontend show which providers are live vs dev-mock."""
    return {
        "googleLive": GOOGLE_LIVE,
        "xLive": X_LIVE,
        "emailLive": EMAIL_LIVE,
        "appBaseUrl": APP_BASE_URL,
    }


# ─────────────────────────────────────────────
# Routes — email + password
# ─────────────────────────────────────────────
@router.post("/signup")
async def signup(req: SignupReq):
    email = req.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    if len(req.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    if not req.firstName.strip():
        raise HTTPException(400, "First name is required.")
    if get_user_by_email(email):
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")

    uid = "usr_" + secrets.token_hex(12)
    display = f"{req.firstName} {req.lastName}".strip()
    conn = get_db()
    conn.execute(
        "INSERT INTO users (id,email,first_name,last_name,display_name,company,role,plan,"
        "password_hash,provider,email_verified,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid, email, req.firstName.strip(), req.lastName.strip(), display,
         req.company.strip(), req.role.strip(), "free",
         hash_password(req.password), "email", 0, _now()),
    )
    conn.commit()
    conn.close()

    dev_code = create_and_send_code(email, "verify")
    return {
        "needsVerification": True,
        "email": email,
        "message": "Account created. We've sent a 6-digit verification code to your email.",
        "devCode": dev_code,           # null when SMTP is live
        "emailLive": EMAIL_LIVE,
    }


@router.post("/login")
async def login(req: LoginReq):
    email = req.email.strip().lower()
    row = get_user_by_email(email)
    if not row or not row["password_hash"] or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(401, "Incorrect email or password.")

    if not row["email_verified"]:
        dev_code = create_and_send_code(email, "verify")
        return {
            "needsVerification": True,
            "email": email,
            "message": "Please verify your email. We've sent you a new code.",
            "devCode": dev_code,
            "emailLive": EMAIL_LIVE,
        }

    touch_login(row["id"])
    token = make_jwt({"sub": row["id"], "email": email})
    return {"token": token, "user": user_public(row)}


@router.post("/send-code")
async def send_code(req: CodeReq):
    email = req.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    # For password reset, only send if the account exists (but don't reveal it).
    if req.purpose == "reset" and not get_user_by_email(email):
        return {"sent": True, "message": "If that account exists, a code has been sent."}
    dev_code = create_and_send_code(email, req.purpose)
    return {"sent": True, "devCode": dev_code, "emailLive": EMAIL_LIVE,
            "message": f"Verification code sent to {email}."}


@router.post("/verify-code")
async def verify_code_route(req: VerifyReq):
    email = req.email.strip().lower()
    code = req.code.strip()
    if not verify_code(email, code, req.purpose):
        raise HTTPException(400, "Invalid or expired code. Please try again.")

    row = get_user_by_email(email)
    if not row:
        raise HTTPException(404, "Account not found.")

    conn = get_db()
    conn.execute("UPDATE users SET email_verified = 1, last_login = ? WHERE id = ?",
                 (_now(), row["id"]))
    conn.commit()
    conn.close()
    row = get_user_by_email(email)
    token = make_jwt({"sub": row["id"], "email": email})
    return {"token": token, "user": user_public(row), "verified": True}


@router.get("/me")
async def me(authorization: Optional[str] = Header(default=None)):
    row = current_user(authorization)
    return {"user": user_public(row)}


@router.post("/logout")
async def logout():
    # Stateless JWT — client discards the token. Endpoint exists for symmetry.
    return {"ok": True}


# ─────────────────────────────────────────────
# Routes — Google OAuth 2.0
# ─────────────────────────────────────────────
@router.get("/google/login")
async def google_login():
    state = secrets.token_urlsafe(24)
    _oauth_state[state] = {"provider": "google", "ts": time.time()}

    if not GOOGLE_LIVE:
        # DEV MODE: skip Google, simulate a returning Google user.
        return RedirectResponse(f"{APP_BASE_URL}/api/auth/google/callback?state={state}&mock=1")

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    }
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


@router.get("/google/callback")
async def google_callback(request: Request):
    qp = request.query_params
    state = qp.get("state", "")
    if state not in _oauth_state:
        return _redirect_error("Invalid OAuth state. Please try again.")
    _oauth_state.pop(state, None)

    if qp.get("mock") == "1" or not GOOGLE_LIVE:
        row = upsert_oauth_user("demo@example.com", "Demo User",
                                "google", photo_url="")
        return _redirect_success(row, "google")

    code = qp.get("code")
    if not code:
        return _redirect_error(qp.get("error", "Google sign-in was cancelled."))
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            tok = await client.post("https://oauth2.googleapis.com/token", data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT,
                "grant_type": "authorization_code",
            })
            tok.raise_for_status()
            access = tok.json()["access_token"]
            ui = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access}"},
            )
            ui.raise_for_status()
            info = ui.json()
        row = upsert_oauth_user(info["email"], info.get("name", ""),
                                "google", photo_url=info.get("picture", ""))
        return _redirect_success(row, "google")
    except Exception as e:
        log.error("Google OAuth error: %s", e)
        return _redirect_error("Google sign-in failed. Please try again.")


# ─────────────────────────────────────────────
# Routes — X / Twitter OAuth 2.0 (PKCE)
# ─────────────────────────────────────────────
def _pkce_pair():
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


@router.get("/x/login")
async def x_login():
    state = secrets.token_urlsafe(24)
    verifier, challenge = _pkce_pair()
    _oauth_state[state] = {"provider": "x", "verifier": verifier, "ts": time.time()}

    if not X_LIVE:
        return RedirectResponse(f"{APP_BASE_URL}/api/auth/x/callback?state={state}&mock=1")

    params = {
        "response_type": "code",
        "client_id": X_CLIENT_ID,
        "redirect_uri": X_REDIRECT,
        "scope": "users.read tweet.read offline.access",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return RedirectResponse("https://twitter.com/i/oauth2/authorize?" + urlencode(params))


@router.get("/x/callback")
async def x_callback(request: Request):
    qp = request.query_params
    state = qp.get("state", "")
    saved = _oauth_state.pop(state, None)
    if not saved:
        return _redirect_error("Invalid OAuth state. Please try again.")

    if qp.get("mock") == "1" or not X_LIVE:
        row = upsert_oauth_user("demo@example.com", "Demo User",
                                "x", x_handle="@demo_user")
        return _redirect_success(row, "x")

    code = qp.get("code")
    if not code:
        return _redirect_error(qp.get("error", "X sign-in was cancelled."))
    try:
        basic = base64.b64encode(f"{X_CLIENT_ID}:{X_CLIENT_SECRET}".encode()).decode()
        async with httpx.AsyncClient(timeout=20) as client:
            tok = await client.post(
                "https://api.twitter.com/2/oauth2/token",
                headers={"Authorization": f"Basic {basic}",
                         "Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": X_REDIRECT,
                    "code_verifier": saved["verifier"],
                    "client_id": X_CLIENT_ID,
                },
            )
            tok.raise_for_status()
            access = tok.json()["access_token"]
            ui = await client.get(
                "https://api.twitter.com/2/users/me",
                params={"user.fields": "profile_image_url,username,name"},
                headers={"Authorization": f"Bearer {access}"},
            )
            ui.raise_for_status()
            data = ui.json()["data"]
        # X does not reliably expose email; synthesise a stable identifier.
        handle = data.get("username", data["id"])
        email = f"{handle}@x.esgintel.local"
        row = upsert_oauth_user(email, data.get("name", handle), "x",
                                photo_url=data.get("profile_image_url", ""),
                                x_handle="@" + handle)
        return _redirect_success(row, "x")
    except Exception as e:
        log.error("X OAuth error: %s", e)
        return _redirect_error("X sign-in failed. Please try again.")


# ─────────────────────────────────────────────
# OAuth redirect helpers
# ─────────────────────────────────────────────
def _redirect_success(row: sqlite3.Row, provider: str) -> RedirectResponse:
    touch_login(row["id"])
    token = make_jwt({"sub": row["id"], "email": row["email"]})
    q = urlencode({"auth_token": token, "provider": provider})
    return RedirectResponse(f"{APP_BASE_URL}{FRONTEND_PATH}?{q}")


def _redirect_error(msg: str) -> RedirectResponse:
    q = urlencode({"auth_error": msg})
    return RedirectResponse(f"{APP_BASE_URL}{FRONTEND_PATH}?{q}")
