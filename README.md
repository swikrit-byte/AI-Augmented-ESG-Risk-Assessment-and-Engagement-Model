# ESGIntel — AI-Assisted Risk Assessment and Stakeholer Engagement Platform

> **v3** — The platform's envisioned product UI is now a live, backend-wired application. This release connects the full design to the real analysis engine, adds real benchmarking and climate-scenario modelling, hardens the document-discovery pipeline for JS-gated corporate sites, and ships as an honest demo build. 

ESGIntel is an AI-powered ESG (Environmental, Social, and Governance) risk assessment platform that replicates the workflow of a senior ESG analyst: it takes raw company information — uploaded reports or just a website — and turns it into a structured, evidence-based risk assessment across the E, S, G, and Climate dimensions.

It is built as a **portfolio project** to demonstrate practitioner-level ESG domain knowledge (ESRS, IFRS S1/S2, GRI, SASB, TCFD, NGFS, CSRD, CSDDD, EU Taxonomy, CBAM) alongside applied AI engineering.

**Core design philosophy:** *AI handles qualitative interpretation; Python handles all quantitative calculation.* Numerical outputs are reproducible and auditable; narrative analysis is grounded in evidence with explicit confidence levels and disclosure-gap flags.

---

## What's New in v3

- **Design-complete product UI, now real.** The full envisioned interface (`ESGIntel_Platform.html`, served at `/app`) is wired end-to-end to the FastAPI backend — assessment loop, dashboard, materiality matrix, geographic risk map, pillar pages, risk register, climate, and engagement views all render live assessment data.
- **Real analytics engines** replacing static placeholders:
  - **Benchmarking** — sector percentiles, z-scores, and quartiles computed in Python (`benchmark_data.py`).
  - **Climate scenarios** — NGFS-style Orderly / Disorderly / Hot-House financial impact, plus stranded-asset and resilience scoring, from a documented, auditable formula (`climate_scenarios.py`).
- **Hardened document-discovery pipeline** for real-world corporate sites:
  - `pypdf` fallback extraction for large/complex bank & annual reports, 40 MB / 60 s limits, and per-report diagnostics that surface exactly why a report was or wasn't used.
  - **Two new discovery tracks for JS-gated report portals** — sitemap parsing and a raw-HTML deep scan that recovers PDF URLs embedded in inline JS/JSON state (e.g. Next.js `__NEXT_DATA__`) — with **no headless browser and no additional API cost**.
- **Authentication, Admin & Account** backed by real endpoints (JWT sessions; Google/X OAuth; email codes; admin user management; account/API-key/team persistence).
- **Data integrity** — all placeholder demo content removed or sanitised so every view reflects the assessed company, never a fabricated sample.
- **Honest demo build** — document/report *exports* are intentionally disabled (see [Demo Build Notes](#demo-build-notes)) so the platform never ships a templated placeholder file.

---

## Architecture

ESGIntel is a shared-backend, dual-frontend application:

```
                    ┌──────────────────────────────┐
   Frontend A  ───► │                              │
   /app (HTML UI)   │      FastAPI backend         │ ──► Anthropic Claude API
                    │  (analysis engine + APIs)    │      (Haiku + Opus)
   Frontend B  ───► │                              │ ──► SQLite (analyses, users)
   Streamlit :8501  └──────────────────────────────┘
```

- **Backend (`backend/`)** — FastAPI. Runs the analysis pipeline, serves the HTML UI at `/app`, and exposes the REST API (`/api/analyze`, `/api/analyses`, `/api/documents/*`, `/api/auth/*`, `/api/admin/*`, `/api/account/*`).
- **Frontend A — `ESGIntel_Platform.html`** (served at `http://localhost:8000/app`). The primary, design-rich single-page UI. Interactive materiality matrix, Leaflet geographic risk map, drill-down panels, live streamed analysis log.
- **Frontend B — `frontend/app.py`** (Streamlit, port 8501). A functional reference build of the same backend, useful for quick iteration.

Both frontends call the same backend and render the same real assessment result.

---

## Key Features

### Two Assessment Modes
- **Document Mode** — upload sustainability/annual reports, policies, TCFD disclosures, etc. The platform extracts structured KPIs and produces a full assessment.
- **Public Intelligence Mode** — with only a website URL, the platform discovers and parses the company's published reports and scrapes its site. Absence of disclosure is never treated as good performance; every gap is flagged.

### Analysis Modules
- **Dashboard** — analyst snapshot, ESG/climate/data-completeness KPIs, top material risks, benchmarking panel, and a live materiality-matrix preview.
- **Company Profile** — sector/geography context, ESG maturity, an interactive geographic risk map, and applicable regulations by country.
- **Dual Materiality** — interactive impact × financial materiality matrix, per-topic rationale, and session-level score overrides.
- **ESG Risk Overview + E/S/G pillar pages** — each pillar with six sub-views: Risk Register, Quantitative Metrics, Qualitative Findings, Benchmarking, Evidence & Sources, and Recommended Actions.
- **Risk Register** — full cross-pillar register with filtering, sorting, and drill-down to root cause / financial exposure / mitigation / source.
- **Climate Risk** — physical & transition risks, NGFS scenario financials, and a resilience assessment.
- **ESG Engagement** — engagement asks, questions, and priorities generated from the assessment.
- **Report Generator** — live report preview driven by the real assessment.
- **Admin & Account** — user management, plan control, profile, API keys, and team invites.

### Scoring Methodology
- Risk topics scored on a 0–100 scale with a multi-factor severity framework.
- Policy-maturity scoring on a five-level scale (no evidence → integrated management system).
- Dynamic quantitative/qualitative weighting based on available data completeness.
- Benchmarking against sector reference distributions; climate financials from documented scenario formulas.

---

## The Intelligence Pipeline

For each assessment with a website URL, the backend runs a multi-track document-discovery and extraction pipeline:

1. **Discovery** (parallel tracks): Claude web search · static site crawler · **sitemap parsing** · **raw-HTML deep scan** (JS-gated pages) · AI URL generation.
2. **Extraction**: PDFs are downloaded and parsed (`pdfplumber` with a `pypdf` fallback) with per-report diagnostics.
3. **Analysis** (AI): profile & scoring, then deep risk/materiality/climate analysis — with the real report text in context.
4. **Structured KPI extraction** (Claude Opus): emissions (Scope 1/2/3, intensity, energy, water, waste), social (LTIFR, turnover, training, diversity, pay gap), and governance (board independence, whistleblower, CEO pay ratio) metrics, mapped to the E/S/G pillars.

---

## Tech Stack

- **Backend:** Python, FastAPI, Uvicorn, SQLite
- **AI:** Anthropic Claude API (`claude-haiku-4-5`, `claude-opus-4-8`)
- **Documents/parsing:** pdfplumber, pypdf, httpx, BeautifulSoup, python-docx, python-pptx, reportlab, openpyxl, matplotlib
- **Frontend A:** single-file HTML/CSS/JS (Leaflet for maps)
- **Frontend B:** Streamlit, Plotly, pandas

---

## Getting Started

### Prerequisites
- Python 3.11+
- An **Anthropic API key** with available credit (each assessment makes real API calls — see [Cost](#cost)).

### 1. Configure the backend
```bash
cd backend
cp .env.example .env
# edit .env and set at minimum:
#   CLAUDE_API_KEY=sk-ant-...
#   ADMIN_EMAIL=you@example.com   (auto-promoted to admin on login)
```

### 2. Run the backend (serves the API + the main UI)
```bash
cd backend
bash start.sh          # creates a venv, installs deps, runs uvicorn on :8000
```
Then open **http://localhost:8000/app**.

- API docs: `http://localhost:8000/docs`
- On the login screen, use **"Continue without login (dev mode)"** for local testing, or create an account (email verification code is shown on-screen in dev mode).

### 3. (Optional) Run the Streamlit reference UI
```bash
cd frontend
bash start_frontend.sh   # Streamlit on :8501 — needs the backend running
```

### Running from VS Code
The repo includes a one-click task: **Terminal → Run Task → "Start ESGIntel (Backend + Frontend)"** launches both servers together.

---

## Configuration

All configuration is via `backend/.env` (never committed). Provider blocks left blank run in **dev mode** so the whole flow is testable without secrets:

| Variable | Purpose |
|---|---|
| `CLAUDE_API_KEY` | Anthropic API key (required for real assessments) |
| `ADMIN_EMAIL` | Account auto-promoted to platform admin on login |
| `JWT_SECRET`, `JWT_TTL_SECONDS` | Session signing |
| `SMTP_*` | Email delivery for verification codes (blank = code shown on-screen) |
| `GOOGLE_CLIENT_ID/SECRET`, `X_CLIENT_ID/SECRET` | OAuth sign-in (blank = dev-mode simulated login) |

---

## Cost

Only **running a new assessment** costs money — that's when the platform calls the Claude API (profile, deep analysis, and structured KPI extraction). Everything else, including **re-opening past analyses** and browsing the UI, is free (results are cached in local SQLite and re-render without any API calls).

---

## Demo Build Notes

This is a demonstration build:
- **Document & report exports are disabled.** The on-screen analysis is fully real, but the downloadable report/document generators still produce templated content, so exports are turned off rather than shipping placeholder files. The generators remain in the codebase (`backend/documents/`) for the planned company-tailored export engine.
- **Benchmarking uses a reference/demonstration sector dataset** (`benchmark_data.py`), structured to be swapped for a licensed peer database without code changes.
- **Climate scenario financials** are modelled estimates from a documented formula — not audited financial guidance.

---

## Project Structure

```
screening/
├── ESGIntel_Platform.html      # Primary UI (served at /app)
├── backend/
│   ├── app.py                  # FastAPI app + analysis pipeline
│   ├── pdf_pipeline.py         # Document discovery + extraction + KPI structuring
│   ├── benchmark_data.py       # Sector benchmarking engine
│   ├── climate_scenarios.py    # NGFS climate scenario modelling
│   ├── auth.py                 # JWT / OAuth / email-code auth
│   ├── admin_api.py            # Admin endpoints
│   ├── account_api.py          # Account / API-key / team endpoints
│   ├── documents_api.py        # Document/report generation routes
│   └── documents/              # Report, deck, one-pager, policy, spreadsheet generators
├── frontend/
│   └── app.py                  # Streamlit reference UI
└── start.sh / start_frontend.sh
```

---

## Disclaimer

ESGIntel is a portfolio demonstration and a first-pass screening tool — not a substitute for full ESG due diligence or professional financial/legal advice. AI-generated qualitative analysis should be validated against source documents before use in any decision.
