"""
ESGIntel — Admin API
====================
A small admin-panel API mounted onto the main FastAPI app via
`app.include_router(admin_router)`. It reuses the SAME SQLite database and JWT
verification as auth.py (no new DB, no re-implemented crypto).

Endpoints (all require an authenticated ADMIN caller — see `require_admin`):
  • GET    /api/admin/users            — list users (+ optional ?search= email filter)
  • PATCH  /api/admin/users/{id}/plan  — change a user's plan/tier
  • GET    /api/admin/stats            — platform statistics
  • GET    /api/admin/users/export     — download the user list as CSV

──────────────────────────────────────────────────────────────────────────────
ADMIN PROMOTION MECHANISM
──────────────────────────────────────────────────────────────────────────────
Admin access is gated on an `is_admin` INTEGER column (default 0) that this
module adds to the existing `users` table. Nobody is admin by default. Two ways
a user becomes admin:

  1. Seed email: on startup `init_admin_db()` sets is_admin=1 for the account
     whose email equals auth.ADMIN_EMAIL (set via the ADMIN_EMAIL environment
     variable — see backend/.env). This is the same email auth.py already
     treats as the platform admin. If ADMIN_EMAIL is unset, no seed promotion
     happens and admin must be granted manually (see below).
  2. Manual promotion: run once against backend/esg_intel.db —
        UPDATE users SET is_admin = 1 WHERE email = 'you@example.com';
     (e.g. to promote the first registered account).

`require_admin` accepts a caller if their row has is_admin=1 OR their email
matches auth.ADMIN_EMAIL. It never grants admin to anyone else.
"""

import csv
import io
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Reuse auth.py's DB path, JWT-backed user resolution and admin seed email.
# Do NOT reimplement JWT logic or open a second database.
import auth
from auth import ADMIN_EMAIL, DB_PATH, current_user

router = APIRouter(prefix="/api/admin", tags=["admin"])
admin_router = router  # exported name (matches auth_router / documents_router style)


# ─────────────────────────────────────────────
# Database helpers (same file as auth.py)
# ─────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    return column in cols


def init_admin_db():
    """Idempotently add the columns the admin panel needs and seed the admin.

    SQLite has no `ADD COLUMN IF NOT EXISTS`, so each ALTER is guarded by a
    PRAGMA check AND a try/except, making startup safe on an existing DB.
    """
    conn = get_db()
    # is_admin flag — default 0 so no existing user is silently promoted.
    if not _column_exists(conn, "users", "is_admin"):
        try:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
        except Exception:
            pass
    # `plan` already exists in auth.py's schema; guard defensively for old DBs.
    if not _column_exists(conn, "users", "plan"):
        try:
            conn.execute("ALTER TABLE users ADD COLUMN plan TEXT DEFAULT 'free'")
        except Exception:
            pass
    # Seed: the known platform admin email is promoted automatically.
    try:
        conn.execute("UPDATE users SET is_admin = 1 WHERE email = ?", (ADMIN_EMAIL,))
    except Exception:
        pass
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# Admin authorization dependency
# ─────────────────────────────────────────────
def require_admin(authorization: Optional[str] = Header(default=None)) -> sqlite3.Row:
    """Resolve the caller via auth.py's JWT verification, then require admin.

    `current_user` decodes the existing HS256 JWT and raises 401 on a bad/expired
    token. We only add the is_admin authorization check on top.
    """
    row = current_user(authorization)  # raises 401 if unauthenticated
    try:
        is_admin = bool(row["is_admin"])
    except (IndexError, KeyError):
        is_admin = False
    if not is_admin and (row["email"] or "").lower() != ADMIN_EMAIL.lower():
        raise HTTPException(403, "Admin privileges required.")
    return row


# ─────────────────────────────────────────────
# Timestamp parsing (best-effort across the two formats in use)
# ─────────────────────────────────────────────
def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    """Parse ISO timestamps. analyses use naive UTC (datetime.utcnow), users use
    aware UTC (datetime.now(timezone.utc)). Normalize everything to aware UTC."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ─────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────
class PlanUpdate(BaseModel):
    plan: str


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────
# NOTE: the `analyses` table has no user_id/owner column, so analyses cannot be
# attributed to individual users. Per-user `analysisCount` is therefore reported
# as null; platform-wide analysis totals live in GET /api/admin/stats.
def _user_row_to_dict(row: sqlite3.Row) -> dict:
    def _get(key, default=None):
        try:
            return row[key]
        except (IndexError, KeyError):
            return default
    return {
        "id": _get("id"),
        "email": _get("email"),
        "displayName": _get("display_name"),
        "company": _get("company"),
        "plan": _get("plan", "free"),
        "isAdmin": bool(_get("is_admin", 0)) or (_get("email", "") or "").lower() == ADMIN_EMAIL.lower(),
        "provider": _get("provider"),
        "createdAt": _get("created_at"),
        "lastLogin": _get("last_login"),
        "analysisCount": None,  # no owner column on analyses — not attributable
    }


@router.get("/users")
def list_users(
    search: Optional[str] = Query(None, description="Filter by email substring"),
    admin: sqlite3.Row = Depends(require_admin),
):
    conn = get_db()
    sql = ("SELECT id, email, display_name, company, plan, is_admin, provider, "
           "created_at, last_login FROM users")
    params: list = []
    if search:
        sql += " WHERE email LIKE ?"
        params.append(f"%{search}%")
    sql += " ORDER BY created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return {"users": [_user_row_to_dict(r) for r in rows], "count": len(rows)}


@router.patch("/users/{user_id}/plan")
def update_user_plan(
    user_id: str,
    body: PlanUpdate,
    admin: sqlite3.Row = Depends(require_admin),
):
    plan = (body.plan or "").strip()
    if not plan:
        raise HTTPException(400, "A plan value is required.")
    conn = get_db()
    exists = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not exists:
        conn.close()
        raise HTTPException(404, "User not found.")
    conn.execute("UPDATE users SET plan = ? WHERE id = ?", (plan, user_id))
    conn.commit()
    row = conn.execute(
        "SELECT id, email, display_name, company, plan, is_admin, provider, "
        "created_at, last_login FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return {"ok": True, "user": _user_row_to_dict(row)}


@router.get("/stats")
def platform_stats(admin: sqlite3.Row = Depends(require_admin)):
    conn = get_db()
    total_users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]

    total_analyses = 0
    analyses_7d = 0
    analyses_30d = 0
    try:
        analyses_rows = conn.execute("SELECT created_at FROM analyses").fetchall()
        total_analyses = len(analyses_rows)
        now = datetime.now(timezone.utc)
        for r in analyses_rows:
            dt = _parse_ts(r["created_at"])
            if not dt:
                continue
            age_days = (now - dt).total_seconds() / 86400
            if age_days <= 7:
                analyses_7d += 1
            if age_days <= 30:
                analyses_30d += 1
    except sqlite3.OperationalError:
        # analyses table not present yet — best-effort zeros
        pass

    active_users_30d = 0
    now = datetime.now(timezone.utc)
    for r in conn.execute("SELECT last_login FROM users").fetchall():
        dt = _parse_ts(r["last_login"])
        if dt and (now - dt).total_seconds() / 86400 <= 30:
            active_users_30d += 1
    conn.close()

    return {
        "totalUsers": total_users,
        "totalAnalyses": total_analyses,
        "analysesLast7Days": analyses_7d,
        "analysesLast30Days": analyses_30d,
        "activeUsersLast30Days": active_users_30d,
    }


@router.get("/users/export")
def export_users_csv(admin: sqlite3.Row = Depends(require_admin)):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, email, display_name, company, plan, is_admin, provider, "
        "created_at, last_login FROM users ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["id", "email", "display_name", "company", "plan", "is_admin",
         "provider", "created_at", "last_login"]
    )
    for r in rows:
        d = _user_row_to_dict(r)
        writer.writerow([
            d["id"], d["email"], d["displayName"], d["company"], d["plan"],
            1 if d["isAdmin"] else 0, d["provider"], d["createdAt"], d["lastLogin"],
        ])
    buf.seek(0)

    filename = f"esgintel_users_{datetime.now(timezone.utc):%Y%m%d}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Ensure the schema is ready as soon as the module is imported, so that
# `require_admin` can safely read the is_admin column even before app startup.
init_admin_db()
