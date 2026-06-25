"""
ESGIntel — Documents API
========================
Streams fully-developed, McKinsey-style deliverables generated on demand:
  • /api/documents/report      → ESG reports (.docx / .pdf)
  • /api/documents/engagement  → engagement pack files (.pptx/.pdf/.docx/.xlsx)
  • /api/documents/manifest    → list of available engagement files (for the UI)

Each generator lives in backend/documents/ and writes a real Office/PDF file
to a temp dir; we return it with the correct media type and filename.
"""

import os
import sys
import json
import sqlite3
import tempfile
import uuid
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Make the generator package importable (its modules do `import company_data`)
_DOCS_DIR = str(Path(__file__).parent / "documents")
if _DOCS_DIR not in sys.path:
    sys.path.insert(0, _DOCS_DIR)

import company_data as cd          # noqa: E402
import reports                     # noqa: E402
import decks                       # noqa: E402
import onepagers                   # noqa: E402
import policies                    # noqa: E402
import spreadsheets                # noqa: E402

# ─────────────────────────────────────────────
# Load latest assessment and patch company_data
# ─────────────────────────────────────────────
_DB_PATH = str(Path(__file__).parent / "esgintel.db")

def _load_latest_assessment() -> dict | None:
    """Return the most recent completed assessment result from SQLite, or None."""
    try:
        conn = sqlite3.connect(_DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT result FROM analyses WHERE status='complete' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return json.loads(row["result"]) if row and row["result"] else None
    except Exception:
        return None

def _patch_company_data(r: dict):
    """Temporarily update company_data with real assessment values so generators use them."""
    if not r:
        return
    co = r.get("company", {})
    scores = r.get("esg_scores", {})
    if co.get("name"):
        cd.COMPANY["name"]  = co["name"]
        cd.COMPANY["short"] = co.get("short_name") or co["name"].split()[0]
    if co.get("sector"):
        cd.COMPANY["sector"] = co["sector"]
    if co.get("country"):
        cd.COMPANY["domicile"] = co["country"]
    if co.get("employees"):
        try:
            cd.COMPANY["employees"] = int(str(co["employees"]).replace(",","").split("-")[0].strip())
        except Exception:
            pass
    if co.get("revenue"):
        cd.COMPANY["revenue_eur_bn"] = co["revenue"]
    # Patch scores
    if scores:
        for k in ("overall", "environmental", "social", "governance", "confidence"):
            if scores.get(k) is not None:
                if k == "overall":
                    cd.SCORES["overall"] = scores[k]
                elif k in cd.SCORES.get("pillars", {}):
                    cd.SCORES["pillars"][k.capitalize()]["score"] = scores[k]
    # Patch risks if available
    risks = r.get("risks")
    if risks and isinstance(risks, list):
        cd.RISKS = risks  # type: ignore[attr-defined]

router = APIRouter(prefix="/api/documents", tags=["documents"])
documents_router = router

MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf":  "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _serve(path: str, download_name: str | None = None) -> FileResponse:
    ext = path.rsplit(".", 1)[-1].lower()
    name = download_name or os.path.basename(path)
    return FileResponse(path, media_type=MEDIA.get(ext, "application/octet-stream"),
                        filename=name)


# ─────────────────────────────────────────────
# Report tab
# ─────────────────────────────────────────────
@router.get("/report")
async def get_report(
    type: str = Query("full"),
    fmt: str = Query("docx"),
):
    rtype = type if type in cd.REPORT_TYPES else "full"
    fmt = fmt.lower()
    if fmt not in ("docx", "pdf"):
        raise HTTPException(400, "Report format must be 'docx' or 'pdf'.")
    _patch_company_data(_load_latest_assessment())  # inject real company data
    out = tempfile.mkdtemp(prefix="esgintel_rep_")
    try:
        path = reports.build_report(rtype, fmt, out)
    except Exception as e:
        raise HTTPException(500, f"Report generation failed: {e}")
    return _serve(path)


# ─────────────────────────────────────────────
# Engagement pack
# ─────────────────────────────────────────────
def _build_engagement(kind: str, key: str, out_dir: str) -> str:
    if kind == "deck":
        return decks.build_deck(key, out_dir)
    if kind == "onepager":
        return onepagers.build_onepager(key, out_dir)
    if kind == "policy":
        return policies.build_policy(key, out_dir)
    if kind == "spreadsheet":
        return spreadsheets.build_spreadsheet(key, out_dir)
    raise HTTPException(404, f"Unknown document kind: {kind}")


@router.get("/engagement")
async def get_engagement(file: str = Query(...)):
    mapping = cd.ENGAGEMENT_FILES.get(file)
    if not mapping:
        raise HTTPException(404, f"Unknown engagement file: {file}")
    kind, key = mapping
    _patch_company_data(_load_latest_assessment())  # inject real company data
    out = tempfile.mkdtemp(prefix="esgintel_eng_")
    try:
        path = _build_engagement(kind, key, out)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Document generation failed: {e}")
    # Preserve the UI's intended filename (with the real extension).
    real_ext = path.rsplit(".", 1)[-1].lower()
    base = file.rsplit(".", 1)[0]
    return _serve(path, download_name=f"{base}.{real_ext}")


@router.get("/manifest")
async def manifest():
    """Filenames the UI can download (used to keep the front-end in sync)."""
    return {"files": list(cd.ENGAGEMENT_FILES.keys()),
            "reportTypes": cd.REPORT_TYPES}


# ─────────────────────────────────────────────
# Canva generation job queue
# ─────────────────────────────────────────────
# Schema: canva_jobs(id TEXT PK, type TEXT, company TEXT, status TEXT,
#                    canva_url TEXT, export_url TEXT, assessment_json TEXT,
#                    created_at TEXT, updated_at TEXT)

def _ensure_canva_table():
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS canva_jobs (
            id          TEXT PRIMARY KEY,
            type        TEXT NOT NULL,
            company     TEXT,
            status      TEXT DEFAULT 'pending',
            canva_url   TEXT,
            export_url  TEXT,
            assessment_json TEXT,
            created_at  TEXT,
            updated_at  TEXT
        )
    """)
    conn.commit()
    conn.close()


def _build_canva_prompt(job_type: str, r: dict) -> str:
    """Build a structured Canva generation prompt from assessment data."""
    co = r.get("company", {})
    scores = r.get("esg_scores", {})
    risks = r.get("risks", [])[:5]
    topics = r.get("material_topics", [])[:5]
    climate = r.get("climate", {})

    top_risks = "; ".join(
        f"{rk.get('title','?')} (score {rk.get('score','?')})"
        for rk in risks
    )
    top_topics = "; ".join(t.get("name", "?") for t in topics)

    phys = "; ".join(
        p.get("name", "?") for p in climate.get("physical_risks", [])[:3]
    )
    trans = "; ".join(
        t.get("name", "?") for t in climate.get("transition_risks", [])[:3]
    )

    deck_type_label = {
        "board_deck": "Board ESG Engagement Deck (15 slides)",
        "investor_deck": "Investor ESG Presentation (8 slides)",
    }.get(job_type, "ESG Presentation")

    return f"""ESGIntel Canva Generation Request
======================================
Deck type: {deck_type_label}

Company: {co.get('name','Unknown')}
Sector:  {co.get('sector','Unknown')}
Country: {co.get('country','Unknown')}
Revenue: {co.get('revenue','N/A')}
Employees: {co.get('employees','N/A')}

ESG Scores
  Overall:       {scores.get('overall','N/A')} / 100
  Environmental: {scores.get('environmental','N/A')}
  Social:        {scores.get('social','N/A')}
  Governance:    {scores.get('governance','N/A')}
  Confidence:    {scores.get('confidence','N/A')}%

Top 5 ESG Risks: {top_risks or 'see assessment'}
Material Topics: {top_topics or 'see assessment'}
Physical Climate Risks: {phys or 'N/A'}
Transition Climate Risks: {trans or 'N/A'}

Design requirements:
- Dark navy (#0D1B2A) background slides with teal (#00C4B4) accent
- Numbered section dividers (large teal numerals, navy bg)
- ESGIntel branding, professional McKinsey-style layout
- Company name and ESG scores on the cover slide
- Score scorecard slide (E/S/G gauge or bar)
- Top risks table slide
- Climate scenario slide
- Engagement asks / recommendations slide

Generate a visually polished Canva presentation for this assessment.
"""


@router.post("/canva/request")
async def canva_request(type: str = Query("board_deck")):
    """
    Create a Canva generation job for the latest assessment.
    Returns job_id, status='pending', and a formatted generation prompt.
    """
    _ensure_canva_table()
    r = _load_latest_assessment()
    company = (r or {}).get("company", {}).get("name", "Unknown") if r else "Unknown"
    job_id = str(uuid.uuid4())[:8]
    prompt = _build_canva_prompt(type, r) if r else f"No assessment found. Generate a template {type}."
    now = datetime.utcnow().isoformat()

    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        "INSERT INTO canva_jobs (id,type,company,status,assessment_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
        (job_id, type, company, "pending", json.dumps(r) if r else None, now, now)
    )
    conn.commit()
    conn.close()

    return {
        "job_id": job_id,
        "type": type,
        "company": company,
        "status": "pending",
        "prompt": prompt,
    }


@router.get("/canva/status/{job_id}")
async def canva_status(job_id: str):
    """Poll job status. Returns status + canva_url once complete."""
    _ensure_canva_table()
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id,type,company,status,canva_url,export_url,updated_at FROM canva_jobs WHERE id=?",
        (job_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")
    return dict(row)


class CanvaCompleteBody(BaseModel):
    canva_url: str
    export_url: str | None = None


@router.put("/canva/complete/{job_id}")
async def canva_complete(job_id: str, body: CanvaCompleteBody):
    """
    Called by Claude (via Canva MCP) once a design has been generated.
    Stores the Canva URL so the frontend can display it.
    """
    _ensure_canva_table()
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(_DB_PATH)
    updated = conn.execute(
        "UPDATE canva_jobs SET status='complete', canva_url=?, export_url=?, updated_at=? WHERE id=?",
        (body.canva_url, body.export_url, now, job_id)
    ).rowcount
    conn.commit()
    conn.close()
    if not updated:
        raise HTTPException(404, f"Job {job_id} not found")
    return {"ok": True, "job_id": job_id, "canva_url": body.canva_url}


@router.get("/canva/latest")
async def canva_latest(type: str = Query("board_deck")):
    """
    Return the most recent completed Canva job for a given deck type.
    Falls back to the saved baseline template design if no assessment-specific job exists.
    """
    # Baseline Canva designs (generated 2026-06-24, VerdaSteelCo S.p.A. demo content)
    # Board deck: 15-slide ESG engagement deck with full ESG scores, risks, peer benchmarks, engagement asks
    # Investor deck: 8-slide investor assessment with financial exposures, climate scenarios, recommendations
    BASELINE_DESIGNS = {
        "board_deck": {
            "canva_url": "https://www.canva.com/d/C6emEIoYQWcJQLY",
            "company": "VerdaSteelCo S.p.A.",
            "status": "complete",
            "id": "baseline-board",
            "type": "board_deck",
            "updated_at": "2026-06-24T00:00:00",
        },
        "investor_deck": {
            "canva_url": "https://www.canva.com/d/PUYee6CFATWO6oa",
            "company": "VerdaSteelCo S.p.A.",
            "status": "complete",
            "id": "baseline-investor",
            "type": "investor_deck",
            "updated_at": "2026-06-24T00:00:00",
        },
    }

    _ensure_canva_table()
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id,type,company,status,canva_url,export_url,updated_at FROM canva_jobs "
        "WHERE type=? AND status='complete' ORDER BY updated_at DESC LIMIT 1",
        (type,)
    ).fetchone()
    conn.close()

    if row:
        return dict(row)

    # Fall back to baseline template
    baseline = BASELINE_DESIGNS.get(type)
    if baseline:
        return baseline
    return {"status": "none"}
