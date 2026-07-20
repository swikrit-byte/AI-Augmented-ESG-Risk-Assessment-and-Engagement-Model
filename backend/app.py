"""
ESGIntel Backend — FastAPI + SQLite + Claude API
Run: uvicorn app:app --reload --port 8000
"""

import os, json, uuid, re, io, sqlite3, time
from pathlib import Path
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response
from dotenv import load_dotenv
import anthropic
import pdfplumber
from pdf_pipeline import (
    run_pdf_pipeline, enrich_analysis, discover_and_get_pdf_texts,
    build_validation_rows, _call_opus_extract,
)
from benchmark_data import compute_benchmarking
from climate_scenarios import compute_climate_scenarios

load_dotenv()

# ─────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────
app = FastAPI(title="ESGIntel API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = Path(__file__).parent / "esg_intel.db"
HTML_PATH = Path(__file__).parent.parent / "ESGIntel_Platform.html"

# ─────────────────────────────────────────────
# Progress log system — live step streaming
# ─────────────────────────────────────────────
PROGRESS_LOGS: dict[str, list] = {}   # analysis_id -> list of log entries
_ANALYSIS_START: dict[str, float] = {}  # analysis_id -> start timestamp

def _log(analysis_id: str, msg: str, done: bool = False):
    """Append a progress log entry for an analysis."""
    elapsed = round(time.time() - _ANALYSIS_START.get(analysis_id, time.time()), 1)
    if analysis_id not in PROGRESS_LOGS:
        PROGRESS_LOGS[analysis_id] = []
    PROGRESS_LOGS[analysis_id].append({
        "msg": msg,
        "done": done,
        "elapsed": elapsed,
    })

# ─── Authentication (Google + X OAuth, email verification, JWT sessions) ───
from auth import auth_router, init_auth_db
app.include_router(auth_router)
init_auth_db()

# ─── Document generation (reports .docx/.pdf, decks .pptx, one-pagers .pdf,
#     policies .docx, templates .xlsx) ───
from documents_api import documents_router
app.include_router(documents_router)

# ─── Admin panel (user management, platform stats, CSV export) ───
from admin_api import admin_router, init_admin_db
app.include_router(admin_router)
init_admin_db()

# ─── Account / settings (profile, API keys, team invites) ───
from account_api import account_router, init_account_db
app.include_router(account_router)
init_account_db()

@app.get("/app")
async def serve_frontend():
    # No-cache headers ensure fresh load every time — fixes "need to refresh" on first open
    resp = FileResponse(HTML_PATH, media_type="text/html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


# ─────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            id           TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'pending',
            created_at   TEXT NOT NULL,
            error        TEXT,
            result       TEXT,
            mode         TEXT DEFAULT 'document'
        )
    """)
    # Add mode column if upgrading from older schema
    try:
        conn.execute("ALTER TABLE analyses ADD COLUMN mode TEXT DEFAULT 'document'")
    except Exception:
        pass
    conn.commit()
    conn.close()

init_db()

# ─────────────────────────────────────────────
# PDF / text extraction
# ─────────────────────────────────────────────
def extract_text(content: bytes, filename: str) -> str:
    if filename.lower().endswith(".pdf"):
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                pages = pdf.pages[:50]
                return "\n\n".join(p.extract_text() or "" for p in pages)
        except Exception as e:
            return f"[PDF extraction failed: {e}]"
    else:
        return content.decode("utf-8", errors="ignore")

# ─────────────────────────────────────────────
# Web scraping — for low-data mode
# ─────────────────────────────────────────────

# Pages to look for on the company website
TARGET_PATHS = [
    "/sustainability", "/esg", "/corporate-responsibility", "/csr",
    "/environment", "/climate", "/governance", "/ethics", "/compliance",
    "/about", "/about-us", "/who-we-are",
    "/investors", "/investor-relations",
    "/policies", "/code-of-conduct", "/human-rights",
    "/supply-chain", "/procurement", "/suppliers",
    "/newsroom", "/news", "/press", "/press-releases",
    "/careers", "/jobs", "/people",
    "/data-privacy", "/privacy-policy",
    "/health-and-safety", "/safety",
]

def clean_html(html: str) -> str:
    """Strip HTML tags and compress whitespace."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


# Common direct URL patterns for sustainability / annual reports (multi-language)
REPORT_PATHS = [
    "/sustainability-report", "/annual-report", "/esg-report",
    "/sustainability-report-2024.pdf", "/sustainability-report-2023.pdf",
    "/annual-report-2024.pdf", "/annual-report-2023.pdf",
    "/rapport-de-durabilite", "/baerekraftsrapport",   # French / Norwegian
    "/arsrapport", "/aarsrapport",                       # Norwegian annual report
    "/investor-relations/reports", "/investors/annual-reports",
    "/reports", "/publications", "/downloads",
]

# Keywords that mark a link/URL as a likely ESG or annual report
PDF_KEYWORDS = [
    "sustainability", "annual", "report", "esg", "csr", "baerekraft",
    "arsrapport", "rapport", "integrated", "climate", "tcfd",
]


async def find_and_download_pdfs(base_url: str, html_content: str, client) -> list[dict]:
    """
    Concurrently discover and download ESG/sustainability PDF reports.
    Sub-page fetching (to find PDFs) and PDF downloads all run in parallel.
    Returns list of {"url": ..., "text": ...}, most relevant first.
    """
    import asyncio

    found_pdfs: set[str] = set()

    def _abs(href: str) -> str:
        href = href.strip()
        if href.startswith("http"):
            return href
        return base_url.rstrip("/") + "/" + href.lstrip("/")

    soup = BeautifulSoup(html_content or "", "html.parser")

    # Collect direct PDF links and sub-pages to fetch concurrently
    direct_pdfs: set[str] = set()
    sub_page_urls: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        text = a.get_text().lower().strip()
        if not href:
            continue
        if href.lower().endswith(".pdf"):
            if any(kw in href.lower() or kw in text for kw in PDF_KEYWORDS):
                direct_pdfs.add(_abs(href))
        elif any(kw in href.lower() for kw in ["report", "download", "publication", "investor"]):
            sub_page_urls.add(_abs(href))

    found_pdfs.update(direct_pdfs)

    # Add common report paths (direct PDFs go straight in, HTML paths fetched concurrently)
    report_html_paths: set[str] = set()
    for path in REPORT_PATHS:
        candidate = base_url.rstrip("/") + path
        if candidate.lower().endswith(".pdf"):
            found_pdfs.add(candidate)
        else:
            report_html_paths.add(candidate)

    # Fetch all sub-pages and report-path HTML pages CONCURRENTLY to harvest PDF links
    async def _harvest_pdfs_from_page(page_url: str) -> set[str]:
        result: set[str] = set()
        try:
            r = await client.get(page_url, timeout=8)
            if r.status_code == 200:
                ps = BeautifulSoup(r.text, "html.parser")
                for sub_a in ps.find_all("a", href=True):
                    sub_href = sub_a.get("href", "").strip()
                    if sub_href.lower().endswith(".pdf") and any(
                        kw in sub_href.lower() or kw in sub_a.get_text().lower() for kw in PDF_KEYWORDS
                    ):
                        result.add(_abs(sub_href))
        except Exception:
            pass
        return result

    pages_to_check = (sub_page_urls | report_html_paths) - {base_url}
    if pages_to_check:
        gathered = await asyncio.gather(*[_harvest_pdfs_from_page(u) for u in list(pages_to_check)[:12]])
        for s in gathered:
            found_pdfs.update(s)

    # Download up to 6 candidate PDFs CONCURRENTLY, keep best 3 by text length
    async def _download_pdf(pdf_url: str) -> dict | None:
        try:
            r = await client.get(pdf_url, timeout=25, follow_redirects=True)
            if r.status_code == 200 and len(r.content) > 10_000:
                text = extract_text(r.content, "report.pdf")
                if len(text) > 500:
                    return {"url": pdf_url, "text": text[:40_000], "_len": len(text)}
        except Exception:
            pass
        return None

    if found_pdfs:
        dl_results = await asyncio.gather(*[_download_pdf(u) for u in list(found_pdfs)[:6]])
        pdf_results = [r for r in dl_results if r]
        # Sort by text length (longer = more content), keep top 3
        pdf_results.sort(key=lambda x: x["_len"], reverse=True)
        for r in pdf_results:
            r.pop("_len", None)
        return pdf_results[:3]

    return []


async def scrape_website(url: str, max_pages: int = 12, char_cap: int = 100_000) -> dict:
    """
    Concurrently fetch homepage + targeted sub-pages + PDF reports.
    All page fetches run in parallel — dramatically faster than sequential.
    Returns {"pages_scraped": [...], "combined_text": "...", "char_count": n}
    """
    import asyncio

    if not url.startswith("http"):
        url = "https://" + url

    base_url = url.rstrip("/")

    scraped: dict[str, str] = {}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; ESGIntelBot/1.0; "
            "+https://esgintel.io/bot)"
        )
    }

    priority_keywords = [
        "sustain", "esg", "environment", "climate", "governance",
        "ethics", "compliance", "policy", "responsib", "supply",
        "human-right", "diversity", "carbon", "emission",
    ]

    def score_url(u: str) -> int:
        u_lower = u.lower()
        return sum(1 for kw in priority_keywords if kw in u_lower)

    async with httpx.AsyncClient(
        timeout=10,
        follow_redirects=True,
        headers=headers,
        verify=False,
    ) as client:
        # Step 1: Fetch homepage (always needed first to discover links)
        homepage_html = ""
        try:
            resp = await client.get(base_url)
            if resp.status_code == 200:
                homepage_html = resp.text
                scraped[base_url] = clean_html(resp.text)[:10_000]
        except Exception:
            pass

        # Step 2: Build candidate URL list from homepage links + known TARGET_PATHS
        candidate_urls: set[str] = set()
        if homepage_html:
            soup = BeautifulSoup(homepage_html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith("/"):
                    candidate_urls.add(base_url + href.split("?")[0].split("#")[0])
                elif href.startswith(base_url):
                    candidate_urls.add(href.split("?")[0].split("#")[0])

        for path in TARGET_PATHS:
            candidate_urls.add(base_url + path)

        # Rank and take top N candidates
        ranked = sorted(candidate_urls - {base_url}, key=score_url, reverse=True)[:max_pages - 1]

        # Step 3: Fetch all sub-pages CONCURRENTLY
        async def _fetch_page(page_url: str) -> tuple[str, str] | None:
            try:
                r = await client.get(page_url)
                if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
                    t = clean_html(r.text)
                    if len(t) > 200:
                        return (page_url, t[:8_000])
            except Exception:
                pass
            return None

        page_results = await asyncio.gather(*[_fetch_page(u) for u in ranked])
        for result in page_results:
            if result:
                scraped[result[0]] = result[1]

        # Step 4: Find and download PDFs CONCURRENTLY (runs at the same time as sub-pages above)
        pdf_reports: list[dict] = []
        try:
            pdf_reports = await find_and_download_pdfs(base_url, homepage_html, client)
        except Exception:
            pdf_reports = []

    pages_scraped = list(scraped.keys())

    report_block = "\n\n---\n\n".join(
        f"[REPORT PDF: {p['url']}]\n{p['text']}" for p in pdf_reports
    )
    html_block = "\n\n---\n\n".join(
        f"[PAGE: {u}]\n{t}" for u, t in scraped.items()
    )

    # Reports are more authoritative — put them FIRST in the combined text.
    parts = [b for b in (report_block, html_block) if b]
    combined = "\n\n===\n\n".join(parts)[:char_cap]

    return {
        "pages_scraped": pages_scraped + [p["url"] for p in pdf_reports],
        "pdf_reports": [p["url"] for p in pdf_reports],
        "combined_text": combined,
        "char_count": len(combined),
    }

def is_low_data(texts: list[str]) -> bool:
    """
    Returns True when we're in low-data mode — no real documents uploaded,
    or content is just the stub query.
    """
    combined = "\n".join(texts)
    # Stub text is ~80 chars; real docs are much larger
    if len(combined) < 400:
        return True
    # Only the stub placeholder text
    if "Please analyse ESG risk based on publicly available information" in combined:
        return True
    return False

# ─────────────────────────────────────────────
# Claude prompts
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are a senior ESG analyst. Analyse sustainability and annual report text
and return ONLY a valid JSON object — no markdown fences, no explanation, just JSON.

CRITICAL: Only cite documents that were explicitly provided in the text below. Never fabricate document names, page numbers, URLs, or report titles. If a document does not exist in the provided text, state 'No document found' rather than inventing a citation."""

LOW_DATA_SYSTEM_PROMPT = """You are a senior ESG analyst conducting a desk-based due diligence review.
You have limited primary documents. You must derive your assessment from publicly observable information only.

CRITICAL RULES:
1. The absence of ESG disclosures is NOT evidence of good performance — identify disclosure gaps explicitly.
2. Never assume positive OR negative performance without observable evidence.
3. Every finding must carry a confidence level: "high", "medium", or "low".
4. Apply dynamic evidence weighting:
   - Direct sustainability report → Very High weight
   - Official published policy → High weight
   - Annual report disclosure → High weight
   - Company website statement → Medium weight
   - Executive interview / press release → Medium weight
   - Third-party news article → Medium-Low weight
   - Industry sector assumption → Low weight
   - Inference / no evidence → Very Low weight
5. Assess policy maturity using observable indicators on a 5-level scale:
   Level 1 = No evidence, Level 2 = Informal commitments, Level 3 = Partial systems,
   Level 4 = Formal documented approach, Level 5 = Integrated management system
6. Identify every missing disclosure as a potential ESG management weakness.
7. Return ONLY valid JSON — no markdown, no preamble.
8. CRITICAL: Only cite documents that were explicitly provided in the text below. Never fabricate document names, page numbers, URLs, or report titles. If a document does not exist in the provided text, state 'No document found' rather than inventing a citation."""

USER_PROMPT_TEMPLATE = """Analyse the following corporate document(s) for company "{company_name}"
and return a JSON object matching this exact schema. Use null for any field you cannot find
evidence for. Higher risk scores (0-100) mean greater ESG risk.

ASSESSMENT CONTEXT (use this to tailor material topics, risks and sector exposure to THIS company):
- NACE sector: {nace_code}
- Country: {country}
- Employee range: {employees}
- Revenue range: {revenue}

{{
  "company": {{
    "name": "string",
    "sector": "string",
    "nace_code": "string (e.g. C24)",
    "country": "string (HQ country)",
    "employees": "string (e.g. '8,400')",
    "revenue": "string (e.g. '€1.2bn')",
    "founded": "string"
  }},
  "esg_scores": {{
    "overall": <0-100 risk>,
    "environmental": <0-100>,
    "social": <0-100>,
    "governance": <0-100>,
    "confidence": <0-100, your confidence in these scores>
  }},
  "overview": {{
    "business_summary": "2-3 sentences describing what the company does",
    "esg_summary": "2-3 sentences overall ESG risk assessment",
    "key_strengths": ["string", "string"],
    "key_gaps": ["string", "string"]
  }},
  "signals": [
    {{
      "label": "short signal name (max 6 words)",
      "type": "positive|negative|neutral",
      "framework": "e.g. ESRS E1 / ISO 14001",
      "description": "1 sentence"
    }}
  ],
  "material_topics": [
    {{
      "topic": "topic name",
      "impact_score": <1-5>,
      "financial_score": <1-5>,
      "category": "environmental|social|governance",
      "trend": "increasing|stable|decreasing",
      "confidence": "high|medium|low",
      "rationale": "1 sentence"
    }}
  ],
  "risks": [
    {{
      "name": "risk name",
      "score": <0-100>,
      "severity": "Critical|High|Medium|Low",
      "category": "environmental|social|governance|climate",
      "framework": "e.g. ESRS E1, SASB IF-ST",
      "detail": "2-3 sentence risk description and top recommendation",
      "key_driver": "short phrase naming the primary underlying cause",
      "horizon": "Short-term|Medium-term|Long-term",
      "financial_impact": "estimated exposure band, e.g. '€2-5M' or a qualitative band 'Low'/'Moderate'/'High'"
    }}
  ],
  "climate": {{
    "physical_risks": [
      {{
        "name": "risk name",
        "score": <0-100>,
        "scenario": "RCP 4.5|RCP 8.5|Both",
        "detail": "2-3 sentences"
      }}
    ],
    "transition_risks": [
      {{
        "name": "risk name",
        "score": <0-100>,
        "horizon": "e.g. 2026-2030",
        "detail": "2-3 sentences"
      }}
    ]
  }},
  "geographic_exposure": [
    {{
      "country": "country name (real, specific to THIS company's value chain)",
      "iso_a3": "ISO 3166-1 alpha-3 code, uppercase (e.g. NPL, IND, CHN, USA)",
      "lat": <approximate country-centroid latitude, decimal degrees>,
      "lng": <approximate country-centroid longitude, decimal degrees>,
      "role": "HQ|Sourcing|Manufacturing|Processing|Logistics|Fulfilment|Sales market|Customer base|Cloud/Data",
      "risk_level": "high|medium|low",
      "climate_risk": "high|medium|low",
      "share": "approx share of operations/revenue/supply if known, else null",
      "rationale": "1 sentence: why this country is in the value chain AND what drives its ESG risk level",
      "regulations": [
        {{ "law": "a specific law/regulation applicable in THIS country", "scope": "1 sentence on how it applies to this company" }}
      ]
    }}
  ],
  "data_coverage": {{
    "documents_analyzed": <number>,
    "reporting_year": "string",
    "frameworks_referenced": ["ESRS", "GRI", ...],
    "assurance": "Limited|Reasonable|None|Unknown",
    "scope3_disclosed": true|false,
    "sbti_committed": true|false
  }}
}}

Provide 4-6 signals, 6-8 material topics, 6-10 risks, 2-4 physical risks, 2-3 transition risks.

MATERIALITY TOPICS — CRITICAL: Material topics MUST be tailored to the specific NACE sector ({nace_code}), business model, and value chain of THIS company. Do NOT default to a generic ESG checklist. For example: a cosmetics company's most material topics include ingredient sourcing safety, animal testing, packaging waste, and consumer product safety — NOT heavy industry topics like blast furnace emissions or mining tailings. A logistics company's topics include fleet emissions and driver welfare — not biodiversity or water stress unless specifically relevant. Every topic must be justified by THIS company's sector and operating model.

GEOGRAPHIC EXPOSURE — be rigorous and company-specific:
- Map the company's ACTUAL value chain: where it is headquartered, where it sources/procures goods, where products are manufactured or processed, the logistics/fulfilment routes, and the markets/customers it sells to.
- Only list countries with a genuine dependency. NEVER pad the list with unrelated countries. If a country has no real link to this company, leave it out.
- Classify each country's risk_level from THIS company's perspective (regulatory pressure, labour/human-rights, governance, supply concentration) and climate_risk (physical climate hazard for that geography).
- Provide 1-6 countries. For a small, domestic, single-country business, it is correct to return just 1-2 countries (e.g. its home country plus a key import source). Do not fabricate global operations.

DOCUMENT TEXT (may be truncated):
{text}"""

LOW_DATA_USER_PROMPT_TEMPLATE = """Conduct a full ESG due diligence assessment for "{company_name}".

You are operating in PUBLIC INTELLIGENCE MODE — limited or no primary ESG documents are available.
Your assessment is based on publicly observable information from the company website and public sources.

Apply the full ESGIntel low-data methodology:
- Identify all observable ESG indicators from the website content below
- Identify ALL disclosure gaps (missing policies, missing KPIs, missing governance disclosures)
- Assess potential risk exposure based on sector, geography, and business model
- Assign confidence levels per finding based on evidence strength
- Never assume positive performance where disclosures are absent

Return a JSON object matching this exact schema. Higher risk scores (0-100) = greater ESG risk.

{{
  "assessment_mode": "public_intelligence",
  "company": {{
    "name": "string",
    "sector": "string — inferred from website content and NACE code",
    "nace_code": "string",
    "country": "string",
    "employees": "string or null",
    "revenue": "string or null",
    "founded": "string or null"
  }},
  "esg_scores": {{
    "overall": <0-100 risk score>,
    "environmental": <0-100>,
    "social": <0-100>,
    "governance": <0-100>,
    "confidence": <0-100 — lower when evidence is sparse>
  }},
  "overview": {{
    "business_summary": "2-3 sentences describing what the company does, inferred from website",
    "esg_summary": "2-3 sentences ESG risk overview — note evidence limitations",
    "key_strengths": ["observable strength with evidence", "..."],
    "key_gaps": ["disclosure gap or weakness with explanation", "..."],
    "assessment_note": "1 sentence explaining data limitations and what the assessment is based on"
  }},
  "signals": [
    {{
      "label": "short signal name (max 6 words)",
      "type": "positive|negative|neutral",
      "framework": "e.g. ESRS E1",
      "description": "1 sentence — cite evidence source (website page, public statement)",
      "evidence_weight": "Very High|High|Medium|Medium-Low|Low|Very Low",
      "confidence": "high|medium|low"
    }}
  ],
  "material_topics": [
    {{
      "topic": "topic name",
      "impact_score": <1-5>,
      "financial_score": <1-5>,
      "category": "environmental|social|governance",
      "trend": "increasing|stable|decreasing|unknown",
      "confidence": "high|medium|low",
      "rationale": "1 sentence — explain why material for this sector/geography",
      "evidence": "what observable evidence exists, or 'No disclosure found'"
    }}
  ],
  "risks": [
    {{
      "name": "risk name",
      "score": <0-100>,
      "severity": "Critical|High|Medium|Low",
      "category": "environmental|social|governance|climate",
      "framework": "e.g. ESRS E1, SASB",
      "detail": "2-3 sentences — risk description, sector exposure rationale, and top recommendation",
      "key_driver": "short phrase naming the primary underlying cause",
      "horizon": "Short-term|Medium-term|Long-term",
      "financial_impact": "estimated exposure band, e.g. '€2-5M' or a qualitative band 'Low'/'Moderate'/'High'",
      "confidence": "high|medium|low",
      "evidence": "observable evidence or 'No disclosure — risk inferred from sector/geography'"
    }}
  ],
  "climate": {{
    "physical_risks": [
      {{
        "name": "risk name",
        "score": <0-100>,
        "scenario": "RCP 4.5|RCP 8.5|Both",
        "detail": "2-3 sentences",
        "confidence": "high|medium|low"
      }}
    ],
    "transition_risks": [
      {{
        "name": "risk name",
        "score": <0-100>,
        "horizon": "e.g. 2026-2030",
        "detail": "2-3 sentences",
        "confidence": "high|medium|low"
      }}
    ]
  }},
  "policy_maturity": [
    {{
      "policy_area": "e.g. Environmental Management",
      "level": <1-5>,
      "level_label": "e.g. Level 2 — Informal commitments",
      "observable_evidence": "what was found, or 'No evidence found'",
      "gap": "what is missing"
    }}
  ],
  "disclosure_gaps": [
    {{
      "area": "e.g. GHG Emissions Reporting",
      "type": "Missing Policy|Missing KPI|Missing Framework|Missing Governance",
      "severity": "Critical|High|Medium|Low",
      "explanation": "1 sentence explaining why this gap matters",
      "recommendation": "1 sentence recommended action"
    }}
  ],
  "geographic_exposure": [
    {{
      "country": "country name (real, specific to THIS company's value chain)",
      "iso_a3": "ISO 3166-1 alpha-3 code, uppercase (e.g. NPL, IND, CHN, USA)",
      "lat": <approximate country-centroid latitude, decimal degrees>,
      "lng": <approximate country-centroid longitude, decimal degrees>,
      "role": "HQ|Sourcing|Manufacturing|Processing|Logistics|Fulfilment|Sales market|Customer base|Cloud/Data",
      "risk_level": "high|medium|low",
      "climate_risk": "high|medium|low",
      "share": "approx share of operations/revenue/supply if known, else null",
      "rationale": "1 sentence: why this country is in the value chain AND what drives its ESG risk level",
      "confidence": "high|medium|low",
      "regulations": [
        {{ "law": "a specific law/regulation applicable in THIS country", "scope": "1 sentence on how it applies to this company" }}
      ]
    }}
  ],
  "data_coverage": {{
    "documents_analyzed": 0,
    "web_pages_scraped": <number>,
    "reporting_year": "null — no formal report found",
    "frameworks_referenced": [],
    "assurance": "None",
    "scope3_disclosed": false,
    "sbti_committed": false,
    "evidence_quality": "Low — assessment based on public website and observable indicators only"
  }}
}}

Provide: 4-5 signals, 5-7 material topics, 5-8 risks, 2-3 physical risks, 2-3 transition risks,
4-6 policy maturity assessments, 4-7 disclosure gaps. Be concise in detail fields (1-2 sentences max).

MATERIALITY TOPICS — CRITICAL: Material topics MUST be tailored to the specific NACE sector ({nace_code}), business model, and value chain of THIS company. Do NOT default to a generic ESG checklist. For example: a cosmetics company's most material topics include ingredient sourcing safety, animal testing, packaging waste, and consumer product safety — NOT heavy industry topics like blast furnace emissions or mining tailings. A logistics company's topics include fleet emissions and driver welfare — not biodiversity or water stress unless specifically relevant. Every topic must be justified by THIS company's sector and operating model.

GEOGRAPHIC EXPOSURE — be rigorous and company-specific (this is critical):
- Infer the company's ACTUAL value chain from the website and public knowledge: HQ/operating country, where it sources or imports goods from, where products are manufactured/processed, logistics and fulfilment, and the markets/customers it serves.
- Only list countries with a genuine, defensible dependency. NEVER include unrelated countries to pad the list. A small domestic online retailer may legitimately have just its home country plus 1-2 key import/sourcing countries — that is the correct answer, not a global footprint.
- Example of the reasoning style (do NOT copy verbatim): a Nepal-based online bookseller is headquartered and fulfils orders domestically in Nepal (its home market) and imports a large share of its books from publishers/printers in India and possibly China — so its real exposure is Nepal, India, and perhaps China, NOT European countries.
- Classify each country's risk_level from THIS company's perspective and climate_risk (physical hazard for that geography), each with a confidence level.
- Provide 1-5 countries. Set confidence to "low" where the value-chain link is inferred rather than stated.

PUBLICLY AVAILABLE CONTENT (scraped from company website and public sources):
{text}

ADDITIONAL CONTEXT:
- NACE sector: {nace_code}
- Country: {country}
- Employee range: {employees}
- Revenue range: {revenue}
"""

# ─────────────────────────────────────────────
# Two-call architecture: shared rules + schemas
# ─────────────────────────────────────────────
SHARED_CITATION_RULES = """CRITICAL CITATION & EVIDENCE RULES (apply to every field):
- ONLY cite documents that appear in the provided text. Never fabricate document names, page numbers, report titles, or URLs.
- If a KPI value is not found in the provided text, set its value to null and available to false.
- Every evidence source must be one of: (a) a specific document excerpt from the provided text, (b) the company website URL, (c) "AI sector inference — [framework]", or (d) "No evidence found".
- Material topics MUST be specific to the NACE sector and business model of THIS company. Cosmetics ≠ steel ≠ logistics ≠ software. Never default to a generic ESG checklist.
- Return ONLY a valid JSON object — no markdown fences, no preamble, no commentary."""

PROFILE_SYSTEM_PROMPT = """You are a senior ESG analyst producing a company profile and ESG scores.
""" + SHARED_CITATION_RULES

DEEP_SYSTEM_PROMPT = """You are a senior ESG analyst producing deep, evidence-backed ESG analysis.
You are given a COMPANY PROFILE CONTEXT (already computed) and the source text. Build a rigorous,
sector-specific risk, materiality, climate and benchmarking analysis that is fully consistent with the
provided profile and scores.
""" + SHARED_CITATION_RULES

PROFILE_USER_PROMPT = """{mode_intro}

Company: "{company_name}"

ASSESSMENT CONTEXT (use this to tailor sector exposure, scores and signals to THIS company):
- NACE sector: {nace_code}
- Country: {country}
- Employee range: {employees}
- Revenue range: {revenue}

Return a JSON object matching EXACTLY this schema (use null where no evidence exists; risk scores 0-100 where higher = greater ESG risk):

{{
  "company": {{ "name": "string", "sector": "string", "nace_code": "string", "country": "string", "employees": "string or null", "revenue": "string or null", "founded": "string or null" }},
  "esg_scores": {{ "overall": <0-100>, "environmental": <0-100>, "social": <0-100>, "governance": <0-100>, "confidence": <0-100> }},
  "overview": {{ "business_summary": "2-3 sentences", "esg_summary": "2-3 sentences", "key_strengths": ["string"], "key_gaps": ["string"], "assessment_note": "1 sentence on data basis/limitations" }},
  "signals": [{{ "label": "max 6 words", "type": "positive|negative|neutral", "framework": "e.g. ESRS E1", "description": "1 sentence", "confidence": "high|medium|low", "evidence_weight": "Very High|High|Medium|Medium-Low|Low|Very Low" }}],
  "geographic_exposure": [{{ "country": "real value-chain country", "iso_a3": "UPPERCASE alpha-3", "lat": <decimal>, "lng": <decimal>, "role": "HQ|Sourcing|Manufacturing|Processing|Logistics|Fulfilment|Sales market|Customer base|Cloud/Data", "risk_level": "high|medium|low", "climate_risk": "high|medium|low", "share": "string or null", "rationale": "1 sentence: why in value chain AND what drives ESG risk", "confidence": "high|medium|low", "regulations": [{{ "law": "specific law", "scope": "1 sentence" }}] }}],
  "policy_maturity": [{{ "policy_area": "e.g. Environmental Management", "level": <1-5>, "level_label": "e.g. Level 2 — Informal commitments", "observable_evidence": "what was found or 'No evidence found'", "gap": "what is missing" }}],
  "data_coverage": {{ "documents_analyzed": <number>, "reporting_year": "string or null", "frameworks_referenced": ["string"], "assurance": "Limited|Reasonable|None|Unknown", "scope3_disclosed": true|false, "sbti_committed": true|false }}
}}

Provide 4-6 signals, 4-6 policy maturity areas, 1-6 geographic exposure countries (only genuine value-chain dependencies — never pad with unrelated countries; a small domestic business may correctly have just 1-2).

GEOGRAPHIC EXPOSURE — map the ACTUAL value chain (HQ, sourcing, manufacturing, logistics, sales markets). Classify each country's risk_level from THIS company's perspective and climate_risk (physical hazard for that geography).

SOURCE TEXT (may be truncated):
{text}"""

DEEP_USER_PROMPT = """You are deepening an ESG assessment for "{company_name}".

ASSESSMENT CONTEXT:
- NACE sector: {nace_code}
- Country: {country}
- Employee range: {employees}
- Revenue range: {revenue}

COMPANY PROFILE CONTEXT (already computed — stay fully consistent with this):
{profile_context}

Using the profile context above AND the source text below, return a JSON object matching EXACTLY this schema (risk scores 0-100 where higher = greater ESG risk):

{{
  "risks": [{{
    "name": "risk name", "score": <0-100>, "severity": "Critical|High|Medium|Low",
    "category": "environmental|social|governance|climate", "framework": "e.g. ESRS E1, SASB IF-ST",
    "detail": "2-3 sentence risk description",
    "key_driver": "short phrase (max ~8 words) naming the primary underlying cause of this risk",
    "horizon": "Short-term|Medium-term|Long-term",
    "financial_impact": "estimated financial exposure band as a string, e.g. '€2-5M', '€10-25M', or a qualitative band like 'Low' / 'Moderate' / 'High' if a figure would be false precision",
    "recommendation": "specific actionable recommendation",
    "evidence": [{{ "source": "doc name / page / URL / AI inference", "text": "what was found", "confidence": "high|medium|low", "type": "quantitative|qualitative|inferred" }}],
    "kpis": [{{ "metric": "string", "value": "string or null", "unit": "string", "benchmark": "string or null", "percentile": "string or null", "year": "string or null", "source": "string or null" }}]
  }}],
  "material_topics": [{{
    "topic": "topic name", "impact_score": <1-5>, "financial_score": <1-5>,
    "category": "environmental|social|governance", "trend": "increasing|stable|decreasing|unknown",
    "confidence": "high|medium|low", "rationale": "1 sentence",
    "financial_rationale": "why financially material for this sector",
    "impact_rationale": "why impact material for this sector",
    "evidence": "observable evidence or 'No disclosure found'",
    "frameworks": ["ESRS E1", "GRI 305", "SASB ..."]
  }}],
  "climate": {{
    "physical_risks": [{{ "name": "string", "score": <0-100>, "scenario": "RCP 4.5|RCP 8.5|Both", "detail": "2-3 sentences", "confidence": "high|medium|low" }}],
    "transition_risks": [{{ "name": "string", "score": <0-100>, "horizon": "e.g. 2026-2030", "detail": "2-3 sentences", "confidence": "high|medium|low" }}]
  }},
  "kpis": [{{
    "category": "environmental|social|governance", "metric": "metric name",
    "value": "value or null", "unit": "unit", "year": "year or null",
    "source": "exact source or null — ONLY cite real documents from the provided text",
    "benchmark": "sector benchmark value if known", "percentile": "P## vs sector peers if estimable",
    "available": true|false
  }}],
  "benchmarking": {{
    "environmental": {{ "narrative": "2-3 sentence interpretation of E score vs peers", "peer_group": "description", "z_score": null, "percentile": null }},
    "social": {{ "narrative": "...", "peer_group": "...", "z_score": null, "percentile": null }},
    "governance": {{ "narrative": "...", "peer_group": "...", "z_score": null, "percentile": null }}
  }}
}}

Provide 6-10 risks (each with 1-3 evidence items and 0-3 kpis), 6-8 material topics, 2-4 physical risks, 2-3 transition risks, and a benchmarking narrative for each pillar. List environmental/social/governance KPIs in the top-level "kpis" array — output environmental KPIs FIRST (GHG emissions, energy, water, waste), then social, then governance; set available=false and value=null for any KPI not evidenced in the text.

MATERIALITY — every topic must be justified by THIS company's NACE sector ({nace_code}) and operating model.

SOURCE TEXT (may be truncated):
{text}"""


def _truncate_text(text: str, mode: str) -> str:
    cap = 80_000 if mode == "public_intelligence" else 120_000
    truncated = text[:cap]
    if len(text) > cap:
        truncated += f"\n\n[Content truncated — first {cap:,} characters used]"
    return truncated


def _claude_json(client, system: str, prompt: str, max_tokens: int = 8000) -> dict:
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = _extract_json_span(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(_repair_json(raw))


def call_claude_profile(
    text: str,
    company_name: str,
    mode: str = "document",
    nace_code: str = "",
    country: str = "",
    employees: str = "",
    revenue: str = "",
) -> dict:
    """Call 1 — Company Profile + Scores (lighter, faster)."""
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        raise ValueError("CLAUDE_API_KEY not set in .env")
    client = anthropic.Anthropic(api_key=api_key)

    if mode == "public_intelligence":
        mode_intro = (
            "You are operating in PUBLIC INTELLIGENCE MODE — limited or no primary ESG documents "
            "are available. Base the profile on publicly observable website/public-source content. "
            "Absence of disclosure is NOT evidence of good performance — flag gaps explicitly and lower confidence."
        )
    else:
        mode_intro = "Analyse the provided corporate sustainability / annual report document(s) to build the company profile and ESG scores."

    prompt = PROFILE_USER_PROMPT.format(
        mode_intro=mode_intro,
        company_name=company_name,
        text=_truncate_text(text, mode),
        nace_code=nace_code or "Not specified",
        country=country or "Not specified",
        employees=employees or "Not specified",
        revenue=revenue or "Not specified",
    )
    return _claude_json(client, PROFILE_SYSTEM_PROMPT, prompt, max_tokens=8000)


def call_claude_deep(
    text: str,
    company_name: str,
    profile_context: dict,
    mode: str = "document",
    nace_code: str = "",
    country: str = "",
    employees: str = "",
    revenue: str = "",
) -> dict:
    """Call 2 — Deep Analysis (risks, materiality, climate, KPIs, benchmarking)."""
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        raise ValueError("CLAUDE_API_KEY not set in .env")
    client = anthropic.Anthropic(api_key=api_key)

    prompt = DEEP_USER_PROMPT.format(
        company_name=company_name,
        profile_context=json.dumps(profile_context, ensure_ascii=False),
        text=_truncate_text(text, mode),
        nace_code=nace_code or "Not specified",
        country=country or "Not specified",
        employees=employees or "Not specified",
        revenue=revenue or "Not specified",
    )
    return _claude_json(client, DEEP_SYSTEM_PROMPT, prompt, max_tokens=12000)


def _build_profile_context(profile: dict) -> dict:
    """Compact JSON summary of Call 1 passed as context to Call 2."""
    company = profile.get("company") or {}
    scores = profile.get("esg_scores") or {}
    overview = profile.get("overview") or {}
    return {
        "company": {
            "name": company.get("name"),
            "sector": company.get("sector"),
            "nace_code": company.get("nace_code"),
            "country": company.get("country"),
        },
        "esg_scores": scores,
        "esg_summary": overview.get("esg_summary"),
        "key_strengths": overview.get("key_strengths"),
        "key_gaps": overview.get("key_gaps"),
        "geographic_exposure": [
            {"country": g.get("country"), "role": g.get("role"), "risk_level": g.get("risk_level")}
            for g in (profile.get("geographic_exposure") or [])
        ],
        "policy_maturity": [
            {"policy_area": p.get("policy_area"), "level": p.get("level")}
            for p in (profile.get("policy_maturity") or [])
        ],
    }


# ─────────────────────────────────────────────
# Claude API call (legacy single-call, retained for compatibility)
# ─────────────────────────────────────────────
def call_claude(
    text: str,
    company_name: str,
    mode: str = "document",
    nace_code: str = "",
    country: str = "",
    employees: str = "",
    revenue: str = "",
) -> dict:
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        raise ValueError("CLAUDE_API_KEY not set in .env")

    client = anthropic.Anthropic(api_key=api_key)

    if mode == "public_intelligence":
        system = LOW_DATA_SYSTEM_PROMPT
        # Cap at 80K chars — website content is less dense than PDF reports
        truncated = text[:80_000]
        if len(text) > 80_000:
            truncated += "\n\n[Content truncated — first 80,000 characters used]"
        prompt = LOW_DATA_USER_PROMPT_TEMPLATE.format(
            company_name=company_name,
            text=truncated,
            nace_code=nace_code or "Not specified",
            country=country or "Not specified",
            employees=employees or "Not specified",
            revenue=revenue or "Not specified",
        )
    else:
        system = SYSTEM_PROMPT
        truncated = text[:120_000]
        if len(text) > 120_000:
            truncated += "\n\n[Document truncated — first 120,000 characters used]"
        prompt = USER_PROMPT_TEMPLATE.format(
            company_name=company_name,
            text=truncated,
            nace_code=nace_code or "Not specified",
            country=country or "Not specified",
            employees=employees or "Not specified",
            revenue=revenue or "Not specified",
        )

    max_tokens = 16000 if mode == "public_intelligence" else 8192

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    # Isolate the JSON object/array: drop any prose before the first brace and
    # any trailing commentary after the matching close ("Extra data" errors).
    raw = _extract_json_span(raw)

    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Attempt to repair truncated JSON by closing open structures
        repaired = _repair_json(raw)
        return json.loads(repaired)


def _extract_json_span(raw: str) -> str:
    """
    Return the substring spanning the first complete top-level JSON value.

    Strips any leading prose before the first '{' or '[' and any trailing text
    after its matching close bracket, which causes json's "Extra data" errors.
    If no matching close is found (truncated output), returns from the opener to
    the end so _repair_json can finish the job.
    """
    start = None
    for i, ch in enumerate(raw):
        if ch in "{[":
            start = i
            break
    if start is None:
        return raw

    opener = raw[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(raw)):
        ch = raw[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            if in_string:
                escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return raw[start : i + 1]

    # Never returned to depth 0 -> truncated; hand the tail to the repairer
    return raw[start:]


def _repair_json(raw: str) -> str:
    """
    Best-effort JSON repair for truncated responses.

    Walks the string once to track the open bracket/brace stack and whether we
    end inside a string literal. Then closes an unterminated string, drops any
    dangling trailing comma or key-without-value, and closes all open
    structures so json.loads can succeed on a partial-but-coherent payload.
    """
    in_string = False
    escape_next = False
    stack = []  # holds the matching closer for each open structure

    for ch in raw:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            if in_string:
                escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if stack:
                stack.pop()

    repaired = raw
    # Close an unterminated string literal
    if in_string:
        repaired += '"'
    repaired = repaired.rstrip()
    # Drop a dangling "key": with no value (truncated right after a colon)
    repaired = re.sub(r',?\s*"[^"]*"\s*:\s*$', "", repaired)
    # Drop a trailing comma
    repaired = re.sub(r",\s*$", "", repaired)
    # Close any structures still open, innermost first
    while stack:
        repaired += stack.pop()
    return repaired

# ─────────────────────────────────────────────
# Background analysis task
# ─────────────────────────────────────────────
def run_analysis(
    analysis_id: str,
    company_name: str,
    texts: list[str],
    website_url: str = "",
    nace_code: str = "",
    country: str = "",
    employees: str = "",
    revenue: str = "",
):
    import asyncio

    # ── Init progress log ──
    _ANALYSIS_START[analysis_id] = time.time()
    PROGRESS_LOGS[analysis_id] = []
    log = lambda msg, done=False: _log(analysis_id, msg, done=done)

    conn = get_db()
    try:
        combined_text = "\n\n---\n\n".join(texts)
        mode = "document"

        # ══════════════════════════════════════════════════════════════
        # PHASE 1 — PDF REPORT DISCOVERY (always runs when website given)
        # Runs BEFORE the AI analysis so the AI sees actual report content
        # (emission intensities, LTIFR, board diversity, etc.)
        # ══════════════════════════════════════════════════════════════
        early_pdfs: list[dict] = []
        if website_url:
            log("Phase 1: searching for annual & sustainability reports…")
            try:
                loop0 = asyncio.new_event_loop()
                asyncio.set_event_loop(loop0)
                early_pdfs = loop0.run_until_complete(
                    discover_and_get_pdf_texts(company_name, website_url, log_fn=log)
                )
                loop0.close()
            except Exception as e:
                log(f"Phase 1 discovery error: {str(e)[:60]} — proceeding without reports", done=True)
                early_pdfs = []

            if early_pdfs:
                # Build a rich text block from the reports to prepend to the AI context
                report_blocks = []
                for p in early_pdfs:
                    fname = p.get("filename", "report.pdf")
                    url   = p.get("url", "")
                    text  = (p.get("text") or "")[:80_000]  # cap per-PDF to manage context size
                    report_blocks.append(
                        f"[SUSTAINABILITY/ANNUAL REPORT: {fname}]\n"
                        f"[Source URL: {url}]\n"
                        f"{text}"
                    )
                pdf_text_block = "\n\n===\n\n".join(report_blocks)
                # Report text comes FIRST — most authoritative source of quantitative data
                combined_text = pdf_text_block + "\n\n===\n\n" + combined_text
                log(
                    f"Phase 1 complete — {len(early_pdfs)} report(s) injected into AI context "
                    f"({len(pdf_text_block):,} chars of report data)",
                    done=True,
                )

        if is_low_data(texts) and not early_pdfs:
            # True low-data: no uploaded docs AND no reports found — scrape website
            mode = "public_intelligence"
            scrape_result = {"pages_scraped": [], "combined_text": "", "char_count": 0}

            if website_url:
                domain = website_url.replace("https://", "").replace("http://", "").split("/")[0]
                log(f"Scraping public intelligence from {domain}…")
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    scrape_result = loop.run_until_complete(scrape_website(website_url))
                    loop.close()
                    pages_scraped = len(scrape_result.get("pages_scraped", []))
                    log(f"Scraped {pages_scraped} pages · {scrape_result.get('char_count', 0):,} chars of public data", done=True)
                except Exception as e:
                    scrape_result["combined_text"] = f"[Web scraping failed: {e}]"
                    log(f"Web scraping failed — using sector context only", done=True)
            else:
                log("No website provided — using sector/country context only", done=True)

            if scrape_result["combined_text"]:
                combined_text = scrape_result["combined_text"]
            else:
                combined_text = (
                    f"Company: {company_name}\n"
                    f"Website: {website_url or 'Not provided'}\n"
                    f"No documents or website content available. "
                    f"Please conduct a sector-based ESG risk assessment."
                )
        elif is_low_data(texts) and early_pdfs:
            # Low-data stub but we found real reports — treat as document mode
            mode = "document"
        elif not is_low_data(texts):
            # User uploaded real documents — already in combined_text with reports prepended
            mode = "document"
            log(f"Processing {len(texts)} uploaded document(s) + {len(early_pdfs)} report(s)…")

        pages_count = 0
        if mode == "public_intelligence":
            pages_count = len(scrape_result.get("pages_scraped", []))  # type: ignore[name-defined]

        # ══════════════════════════════════════════════════════════════
        # AI ANALYSIS — now sees full report content from Phase 1
        # ══════════════════════════════════════════════════════════════
        log("Building ESG profile and scoring — AI call 1 of 2…")
        profile = call_claude_profile(
            combined_text, company_name, mode=mode,
            nace_code=nace_code, country=country,
            employees=employees, revenue=revenue,
        )
        scores = profile.get("esg_scores", {})
        e_score = scores.get("environmental", "—")
        s_score = scores.get("social", "—")
        g_score = scores.get("governance", "—")
        log(f"Profile complete — E:{e_score} · S:{s_score} · G:{g_score}", done=True)

        log("Deep risk, materiality & climate analysis — AI call 2 of 2…")
        deep = call_claude_deep(
            combined_text, company_name,
            _build_profile_context(profile), mode=mode,
            nace_code=nace_code, country=country,
            employees=employees, revenue=revenue,
        )
        risk_count  = len(deep.get("risks", []))
        topic_count = len(deep.get("material_topics", []))
        log(f"Deep analysis complete — {risk_count} risks · {topic_count} material topics", done=True)
        result = {**profile, **deep}

        if mode == "public_intelligence" and "data_coverage" in result:
            result["data_coverage"]["web_pages_scraped"] = pages_count

        result["_mode"] = mode

        # ══════════════════════════════════════════════════════════════
        # PHASE 2 — OPUS STRUCTURED EXTRACTION
        # Extracts structured KPIs from the same PDFs (no re-download)
        # and merges them into result["kpis"] + pdf_intelligence block
        # ══════════════════════════════════════════════════════════════
        if website_url:
            log("Phase 2: Claude Opus structured KPI extraction from reports…")
            try:
                loop2 = asyncio.new_event_loop()
                asyncio.set_event_loop(loop2)
                pdf_intel = loop2.run_until_complete(
                    run_pdf_pipeline(
                        company_name, website_url, log_fn=log,
                        pre_discovered_pdfs=early_pdfs if early_pdfs else None,
                    )
                )
                loop2.close()
                result = enrich_analysis(result, pdf_intel)
                kpi_count    = len((pdf_intel or {}).get("kpis", []))
                target_count = len((pdf_intel or {}).get("climate_targets", []))
                if kpi_count or target_count:
                    log(f"Phase 2 complete — {kpi_count} KPIs · {target_count} climate targets extracted", done=True)
                else:
                    log("Phase 2 complete — qualitative data extracted (no quantitative KPIs found)", done=True)
            except Exception as pdf_err:
                result["pdf_intelligence"] = {"error": str(pdf_err)}
                log(f"Phase 2 error: {str(pdf_err)[:60]}", done=True)

        # ══════════════════════════════════════════════════════════════
        # PHASE 3 — DETERMINISTIC ANALYTICS (no LLM, no network)
        # Real sector benchmarking (z-score/percentile/quartile) + NGFS
        # climate scenario financials + stranded-asset / resilience scoring.
        # Pure Python — always runs, cannot fail the analysis.
        # ══════════════════════════════════════════════════════════════
        try:
            sector_code = nace_code or (result.get("company") or {}).get("nace_code") or ""

            # ── Benchmarking: fill previously-null z_score/percentile and add
            #    sector_avg + quartile per pillar, PRESERVING Claude's narratives.
            computed_bm = compute_benchmarking(result.get("esg_scores") or {}, sector_code)
            bm = result.get("benchmarking") or {}
            for pillar in ("overall", "environmental", "social", "governance"):
                stats = computed_bm.get(pillar)
                if not stats:
                    continue
                block = bm.get(pillar) or {}
                block.update(stats)   # z_score, percentile, sector_avg, quartile
                bm[pillar] = block
            bm["sector_reference"] = computed_bm.get("sector_reference")
            result["benchmarking"] = bm

            # ── Climate scenarios + stranded-asset / resilience scoring.
            climate = result.get("climate") or {}
            scen = compute_climate_scenarios(
                climate,
                nace_code=sector_code,
                revenue=revenue,
                employees=employees,
                policy_maturity=result.get("policy_maturity"),
            )
            climate.update(scen)      # scenarios, stranded_asset_score, resilience_*
            result["climate"] = climate

            log("Benchmarking & climate scenarios computed", done=True)
        except Exception as calc_err:
            log(f"Analytics computation error: {str(calc_err)[:60]}", done=True)

        log(f"Assessment ready ✓", done=True)

        conn.execute(
            "UPDATE analyses SET status='complete', result=?, mode=? WHERE id=?",
            (json.dumps(result), mode, analysis_id),
        )
        conn.commit()

    except Exception as e:
        log(f"Error: {str(e)[:80]}", done=True)
        conn.execute(
            "UPDATE analyses SET status='error', error=? WHERE id=?",
            (str(e), analysis_id),
        )
        conn.commit()
    finally:
        conn.close()

# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@app.get("/")
def health():
    return {"status": "ok", "service": "ESGIntel API"}


@app.post("/api/analyze", status_code=202)
async def analyze_company(
    background_tasks: BackgroundTasks,
    company_name: str = Form(...),
    documents: list[UploadFile] = File(...),
    website_url: Optional[str] = Form(None),
    nace_code: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
    employees: Optional[str] = Form(None),
    revenue: Optional[str] = Form(None),
):
    """
    Upload 1+ documents (PDF or TXT) and kick off ESG analysis.
    If no real documents are present, switches to public intelligence mode
    and scrapes the company website.
    Returns immediately with an analysis_id; poll /api/analyses/{id}/status.
    """
    analysis_id = str(uuid.uuid4())

    texts = []
    for doc in documents:
        content = await doc.read()
        texts.append(extract_text(content, doc.filename))

    conn = get_db()
    conn.execute(
        "INSERT INTO analyses (id, company_name, status, created_at, mode) VALUES (?, ?, 'processing', ?, ?)",
        (analysis_id, company_name, datetime.utcnow().isoformat(), "pending"),
    )
    conn.commit()
    conn.close()

    background_tasks.add_task(
        run_analysis,
        analysis_id,
        company_name,
        texts,
        website_url or "",
        nace_code or "",
        country or "",
        employees or "",
        revenue or "",
    )

    return {"id": analysis_id, "status": "processing"}


# ─────────────────────────────────────────────
# Data Validation — lightweight pre-run KPI review
# ─────────────────────────────────────────────
def _run_validation(company_name: str, docs: list, website_url: str):
    """Lightweight pre-run extraction (blocking — runs in a threadpool).

    Runs ONLY the KPI extraction step (Opus per-document) — NOT the full
    two-call Claude analysis pipeline. `docs` is a list of (filename, text).
    Reuses discover_and_get_pdf_texts / _call_opus_extract / build_validation_rows
    from pdf_pipeline. Creates its own event loop for the async discovery step,
    mirroring run_analysis().
    Returns (rows, documents_parsed).
    """
    import asyncio
    extracted_docs = []

    # ── Uploaded documents ──
    for filename, text in docs:
        if not text or len(text) < 500:
            continue
        try:
            doc_data = _call_opus_extract(text, company_name, filename)
            doc_data["_source_url"] = ""
            doc_data["_filename"] = filename
            extracted_docs.append(doc_data)
        except Exception:
            pass

    # ── Website report discovery (Phase-1 discovery only — no full pipeline) ──
    if website_url:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            pdfs = loop.run_until_complete(
                discover_and_get_pdf_texts(company_name, website_url)
            )
            loop.close()
        except Exception:
            pdfs = []
        for pdf in (pdfs or []):
            text = pdf.get("text", "")
            if not text or len(text) < 500:
                continue
            fname = pdf.get("filename", "report.pdf")
            try:
                doc_data = _call_opus_extract(text, company_name, fname)
                doc_data["_source_url"] = pdf.get("url", "")
                doc_data["_filename"] = fname
                extracted_docs.append(doc_data)
            except Exception:
                pass

    return build_validation_rows(extracted_docs), len(extracted_docs)


@app.post("/api/validate")
async def validate_inputs(
    company_name: str = Form(...),
    documents: Optional[list[UploadFile]] = File(None),
    website_url: Optional[str] = Form(None),
):
    """
    Data Validation pre-run endpoint.

    Accepts the same inputs as the start of /api/analyze (uploaded documents
    and/or a website URL) but runs ONLY the lightweight parsing/KPI-extraction
    step — NOT the expensive multi-call Claude analysis. Returns parsed KPI rows
    so the frontend can show a review screen before committing to a full run.

    Each row: {metric, value, unit, year, source, confidence, flagged, flag_reason}.
    """
    docs = []
    for doc in (documents or []):
        content = await doc.read()
        docs.append((doc.filename, extract_text(content, doc.filename)))

    if not docs and not website_url:
        raise HTTPException(400, "Provide at least one document or a website_url")

    import asyncio
    rows, n_docs = await asyncio.get_event_loop().run_in_executor(
        None, _run_validation, company_name, docs, website_url or ""
    )

    flagged = sum(1 for r in rows if r.get("flagged"))
    return {
        "company_name": company_name,
        "documents_parsed": n_docs,
        "kpi_count": len(rows),
        "flagged_count": flagged,
        "rows": rows,
    }


@app.get("/api/analyses")
def list_analyses():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, company_name, status, created_at, mode FROM analyses ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM analyses WHERE id=?", (analysis_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Analysis not found")
    data = dict(row)
    if data.get("result"):
        data["result"] = json.loads(data["result"])
    return data


@app.delete("/api/analyses/{analysis_id}")
def delete_analysis(analysis_id: str):
    conn = get_db()
    conn.execute("DELETE FROM analyses WHERE id=?", (analysis_id,))
    conn.commit()
    conn.close()
    return {"deleted": True}


@app.get("/api/analyses/{analysis_id}/status")
def get_status(analysis_id: str):
    conn = get_db()
    row = conn.execute(
        "SELECT status, error, mode FROM analyses WHERE id=?", (analysis_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Analysis not found")
    result = dict(row)
    result["logs"] = PROGRESS_LOGS.get(analysis_id, [])
    return result
