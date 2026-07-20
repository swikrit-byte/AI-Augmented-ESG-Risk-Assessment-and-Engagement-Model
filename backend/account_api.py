"""
ESGIntel — Account / Settings API
=================================
Per-user account settings, API keys and lightweight team invites. Mounted onto
the main FastAPI app via `app.include_router(account_router)`.

Reuses the SAME SQLite database file and JWT verification as auth.py — it opens
a new connection to auth.DB_PATH (backend/esg_intel.db) and identifies the
caller with auth.current_user (the existing HS256 token verifier). No second
database, no re-implemented JWT logic.

Endpoints (all scoped to the current authenticated user):
  • GET  /api/account/profile              — read display_name, company, prefs
  • PUT  /api/account/profile              — update the above
  • GET  /api/account/api-keys             — list non-revoked keys (never the key)
  • POST /api/account/api-keys             — create a key; returns plaintext ONCE
  • DEL  /api/account/api-keys/{id}        — revoke (soft delete)
  • GET  /api/account/team                 — list invites the user sent
  • POST /api/account/team/invite          — invite {email, role}
  • DEL  /api/account/team/invite/{id}     — cancel an invite the user sent
"""

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

# Reuse auth.py's DB path and JWT-backed user resolution.
import auth
from auth import DB_PATH, current_user

router = APIRouter(prefix="/api/account", tags=["account"])
account_router = router  # exported name (matches auth_router / documents_router style)


# ─────────────────────────────────────────────
# Database helpers (same file as auth.py)
# ─────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_account_db():
    """Create the account-related tables if they don't already exist."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_profile (
            user_id            TEXT PRIMARY KEY,
            display_name       TEXT,
            company            TEXT,
            notification_prefs_json TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id           TEXT PRIMARY KEY,
            user_id      TEXT NOT NULL,
            key_hash     TEXT NOT NULL,
            label        TEXT,
            created_at   TEXT NOT NULL,
            last_used_at TEXT,
            revoked      INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS team_invites (
            id              TEXT PRIMARY KEY,
            inviter_user_id TEXT NOT NULL,
            invitee_email   TEXT NOT NULL,
            role            TEXT,
            status          TEXT DEFAULT 'pending',
            created_at      TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# Auth dependency — identify the current user
# ─────────────────────────────────────────────
def get_current_user(authorization: Optional[str] = Header(default=None)) -> sqlite3.Row:
    """Thin wrapper over auth.current_user so routes can use Depends()."""
    return current_user(authorization)  # raises 401 if unauthenticated


# ─────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────
class ProfileUpdate(BaseModel):
    displayName: Optional[str] = None
    company: Optional[str] = None
    notificationPrefs: Optional[dict] = None


class ApiKeyCreate(BaseModel):
    label: str = ""


class TeamInvite(BaseModel):
    email: str
    role: str = "member"


# ─────────────────────────────────────────────
# Profile
# ─────────────────────────────────────────────
@router.get("/profile")
def get_profile(user: sqlite3.Row = Depends(get_current_user)):
    conn = get_db()
    row = conn.execute(
        "SELECT display_name, company, notification_prefs_json FROM user_profile WHERE user_id = ?",
        (user["id"],),
    ).fetchone()
    conn.close()

    if row:
        display_name = row["display_name"]
        company = row["company"]
        prefs_raw = row["notification_prefs_json"]
    else:
        # Fall back to the values already stored on the users table.
        display_name = user["display_name"]
        company = user["company"]
        prefs_raw = None

    try:
        prefs = json.loads(prefs_raw) if prefs_raw else {}
    except Exception:
        prefs = {}

    return {
        "userId": user["id"],
        "email": user["email"],
        "displayName": display_name,
        "company": company,
        "notificationPrefs": prefs,
    }


@router.put("/profile")
def update_profile(body: ProfileUpdate, user: sqlite3.Row = Depends(get_current_user)):
    conn = get_db()
    existing = conn.execute(
        "SELECT user_id, display_name, company, notification_prefs_json FROM user_profile WHERE user_id = ?",
        (user["id"],),
    ).fetchone()

    # Resolve final values, keeping current ones when a field is omitted (None).
    display_name = body.displayName if body.displayName is not None else (
        existing["display_name"] if existing else user["display_name"])
    company = body.company if body.company is not None else (
        existing["company"] if existing else user["company"])
    if body.notificationPrefs is not None:
        prefs_json = json.dumps(body.notificationPrefs)
    else:
        prefs_json = existing["notification_prefs_json"] if existing else None

    if existing:
        conn.execute(
            "UPDATE user_profile SET display_name = ?, company = ?, notification_prefs_json = ? WHERE user_id = ?",
            (display_name, company, prefs_json, user["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO user_profile (user_id, display_name, company, notification_prefs_json) VALUES (?,?,?,?)",
            (user["id"], display_name, company, prefs_json),
        )
    conn.commit()
    conn.close()

    try:
        prefs = json.loads(prefs_json) if prefs_json else {}
    except Exception:
        prefs = {}
    return {
        "ok": True,
        "userId": user["id"],
        "displayName": display_name,
        "company": company,
        "notificationPrefs": prefs,
    }


# ─────────────────────────────────────────────
# API keys
# ─────────────────────────────────────────────
@router.get("/api-keys")
def list_api_keys(user: sqlite3.Row = Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, label, created_at, last_used_at FROM api_keys "
        "WHERE user_id = ? AND revoked = 0 ORDER BY created_at DESC",
        (user["id"],),
    ).fetchall()
    conn.close()
    return {
        "keys": [
            {
                "id": r["id"],
                "label": r["label"],
                "createdAt": r["created_at"],
                "lastUsedAt": r["last_used_at"],
            }
            for r in rows
        ]
    }


@router.post("/api-keys")
def create_api_key(body: ApiKeyCreate, user: sqlite3.Row = Depends(get_current_user)):
    # Generate a strong key, store ONLY its SHA-256 hash, return plaintext once.
    plaintext = "esgk_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    key_id = "key_" + secrets.token_hex(8)
    label = (body.label or "").strip() or "API key"

    conn = get_db()
    conn.execute(
        "INSERT INTO api_keys (id, user_id, key_hash, label, created_at, revoked) "
        "VALUES (?,?,?,?,?,0)",
        (key_id, user["id"], key_hash, label, _now()),
    )
    conn.commit()
    conn.close()

    return {
        "id": key_id,
        "label": label,
        "key": plaintext,  # shown exactly once — cannot be retrieved again
        "message": "Store this key now. It cannot be shown again.",
    }


@router.delete("/api-keys/{key_id}")
def revoke_api_key(key_id: str, user: sqlite3.Row = Depends(get_current_user)):
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM api_keys WHERE id = ? AND user_id = ?",
        (key_id, user["id"]),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "API key not found.")
    conn.execute("UPDATE api_keys SET revoked = 1 WHERE id = ?", (key_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "id": key_id, "revoked": True}


# ─────────────────────────────────────────────
# Team invites
# ─────────────────────────────────────────────
@router.get("/team")
def list_team(user: sqlite3.Row = Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, invitee_email, role, status, created_at FROM team_invites "
        "WHERE inviter_user_id = ? ORDER BY created_at DESC",
        (user["id"],),
    ).fetchall()
    conn.close()
    return {
        "invites": [
            {
                "id": r["id"],
                "email": r["invitee_email"],
                "role": r["role"],
                "status": r["status"],
                "createdAt": r["created_at"],
            }
            for r in rows
        ]
    }


@router.post("/team/invite")
def invite_teammate(body: TeamInvite, user: sqlite3.Row = Depends(get_current_user)):
    email = (body.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "A valid email address is required.")
    role = (body.role or "member").strip() or "member"
    invite_id = "inv_" + secrets.token_hex(8)

    conn = get_db()
    conn.execute(
        "INSERT INTO team_invites (id, inviter_user_id, invitee_email, role, status, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (invite_id, user["id"], email, role, "pending", _now()),
    )
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "invite": {
            "id": invite_id,
            "email": email,
            "role": role,
            "status": "pending",
        },
    }


@router.delete("/team/invite/{invite_id}")
def cancel_invite(invite_id: str, user: sqlite3.Row = Depends(get_current_user)):
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM team_invites WHERE id = ? AND inviter_user_id = ?",
        (invite_id, user["id"]),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Invite not found.")
    conn.execute("DELETE FROM team_invites WHERE id = ?", (invite_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "id": invite_id, "cancelled": True}


# Create the account tables as soon as the module is imported.
init_account_db()
