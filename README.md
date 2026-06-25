# ESGIntel — AI-Assisted ESG Due Diligence Platform

> **v2 Update** — ESGIntel has been significantly expanded. v2 adds a document generation engine, custom authentication system, and a hardened low-data intelligence pipeline. See changelog below.

---

## What is ESGIntel?

ESGIntel is an AI-powered ESG (Environmental, Social, and Governance) due diligence platform designed for ESG analysts, investors, lenders, and sustainability consultants. It replicates the workflow of a senior analyst conducting a pre-investment ESG assessment — taking raw company information as input and transforming it into a structured, evidence-based risk report.

The platform is built around a core philosophy: **AI handles qualitative interpretation; Python handles all quantitative calculations.** This separation ensures that numerical outputs are reproducible and auditable, while narrative analysis is grounded in evidence with explicit confidence levels.

---

## What's New in v2

- **Document Generation Engine** — export assessments to PDF, Word (.docx), PowerPoint (.pptx), and Excel (.xlsx) directly from the platform
- **Authentication System** — custom FastAPI auth with Google OAuth, X/Twitter OAuth, email magic-link codes, and JWT sessions (replaces demo bypass)
- **Low-Data Intelligence Pipeline** — hardened public intelligence mode with evidence-weighted confidence scoring and explicit disclosure gap analysis
- **Security** — `.env` scrubbed from git history; secrets are now loaded via `.env.example` template only

---

## Key Features

### Two Assessment Modes

**Document Mode**
Upload company documents (sustainability reports, annual reports, policies, TCFD disclosures, etc.) and the platform extracts structured ESG data, scores risks across Environmental, Social, and Governance dimensions, and generates a full due diligence assessment.

**Public Intelligence Mode**
When no primary documents are available, the platform automatically switches to a web-scraping workflow. It crawls the company's website — prioritising sustainability, governance, and policy pages — and conducts a desk-based assessment from publicly observable information only. Crucially, the absence of disclosures is never assumed to be positive performance; every disclosure gap is flagged explicitly.

### ESG Risk Assessment
- **Scored risk topics** across Environmental, Social, Governance, and Climate dimensions (0–100 risk scale)
- **Seven-factor severity framework** for each identified risk
- **Policy maturity scoring** on a five-level scale (from no evidence → integrated management system)
- **Dynamic weighting**: Python automatically adjusts the quantitative/qualitative split based on available data (data-rich = up to 80% quant weighting; no data = 100% qualitative, flagged accordingly)

### Dual Materiality Assessment
Maps topics against both financial materiality and impact materiality, drawing on SASB sector standards, ESRS (European Sustainability Reporting Standards), and GRI 3. Material topics are filtered dynamically by NACE sector, business model, and geography — not from a static generic checklist.

### Climate Risk Analysis
Separate from general environmental risk. Covers physical risks (under RCP 4.5 and RCP 8.5 scenarios) and transition risks, aligned with IFRS S2 and the TCFD framework. Three scenario pathways: Conservative, Moderate, and Leading.

### ESG Signal Feed
A live feed of positive, negative, and neutral ESG signals extracted from the company's documents or website, each tagged with a relevant framework (e.g. ESRS E1, ISO 14001, SASB).

### Methodology Transparency
Every score, finding, and result includes a **View Methodology** panel that shows the objective, frameworks applied, exact Python formulas (where applicable), AI reasoning process, actual data sources used, scoring logic, confidence methodology, and limitations. Nothing is a black box.

### Evidence Weighting (Public Intelligence Mode)
Findings are weighted by evidence quality:
| Source | Weight |
|---|---|
| Direct sustainability report | Very High |
| Official published policy | High |
| Annual report disclosure | High |
| Company website statement | Medium |
| Executive interview / press release | Medium |
| Third-party news article | Medium-Low |
| Industry sector assumption | Low |
| Inference / no evidence | Very Low |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python · FastAPI · SQLite |
| AI Model | Claude Haiku (Anthropic API) |
| Document Parsing | pdfplumber |
| Web Scraping | httpx · BeautifulSoup4 |
| Frontend | Vanilla HTML / CSS / JavaScript (single file) |
| Dev Environment | uvicorn |

---

## Project Structure

```
ESGIntel/
├── backend/
│   ├── app.py                        # FastAPI backend — all API routes and analysis logic
│   ├── auth.py                       # Authentication: Google/X OAuth, email codes, JWT
│   ├── documents_api.py              # Document generation API router
│   ├── pdf_pipeline.py               # PDF parsing and extraction pipeline
│   ├── documents/
│   │   ├── reports.py                # ESG assessment report generator (.docx/.pdf)
│   │   ├── decks.py                  # PowerPoint deck generator (.pptx)
│   │   ├── onepagers.py              # One-page summary generator (.pdf)
│   │   ├── policies.py               # Policy template generator (.docx)
│   │   ├── spreadsheets.py           # Data export generator (.xlsx)
│   │   └── company_data.py           # Shared company data helpers
│   ├── .env.example                  # Environment variable template (never commit .env)
│   ├── AUTH_SETUP.md                 # Step-by-step auth configuration guide
│   ├── requirements.txt              # Python dependencies
│   ├── start.sh                      # Start script
│   └── Launch ESGIntel Backend.command  # macOS double-click launcher
├── ESGIntel_Platform.html            # Frontend (single-file)
└── ESGIntel.Rproj                    # R project file (for supplementary analysis)
```

---

## Getting Started

### Prerequisites
- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com/)

### Setup

```bash
# 1. Clone the repo
git clone https://github.com/swikrit-byte/AI-Augmented-ESG-Risk-Assessment-and-Engagement-Model.git
cd AI-Augmented-ESG-Risk-Assessment-and-Engagement-Model

# 2. Create and activate virtual environment
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set your API key
cp .env.example .env
# Edit .env and add: CLAUDE_API_KEY=your_key_here

# 5. Start the backend
uvicorn app:app --reload --port 8000
```

Then open `http://localhost:8000/app` in your browser.

On macOS, you can also double-click **Launch ESGIntel Backend.command** to start the server.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/analyze` | Submit a company for ESG analysis |
| `GET` | `/api/analyses` | List all past analyses |
| `GET` | `/api/analyses/{id}` | Retrieve a completed analysis |
| `GET` | `/api/analyses/{id}/status` | Poll analysis status |
| `DELETE` | `/api/analyses/{id}` | Delete an analysis |

The `/api/analyze` endpoint accepts `multipart/form-data` with:
- `company_name` (required)
- `documents` — one or more PDF/TXT files (optional; triggers public intelligence mode if absent)
- `website_url`, `nace_code`, `country`, `employees`, `revenue` (optional context)

---

## Roadmap / What's Coming

- [ ] Quantitative ESG data extraction and Python-calculated KPIs (emissions intensity, LTIFR, turnover rate, diversity ratios)
- [ ] Benchmarking against sector peers using Z-scores and percentile ranking
- [ ] ESG Engagement module — auto-generates engagement letters, questions, and action plans from assessment findings
- [ ] Dynamic topic filtering by NACE sector and value chain position
- [ ] User validation step for AI-extracted quantitative data
- [ ] Expanded framework coverage: CSRD, GRI, CDP, SASB full sector library
- [ ] Streamlined UI with full navigation sidebar (Dashboard, Company Profile, Materiality, ESG Risk subtabs, Climate Risk)

---

## Design Principles

1. **AI/Python split is non-negotiable.** AI interprets; Python calculates. AI never generates numerical results.
2. **No static ESG checklists.** Topics are always filtered dynamically by sector, geography, and business model.
3. **Transparency by default.** Every output includes its methodology.
4. **Absence of disclosure ≠ good performance.** Missing disclosures are flagged as potential management weaknesses, not ignored.

---

## About

ESGIntel is a portfolio project built to demonstrate practitioner-level ESG domain knowledge combined with AI engineering fluency. It is not affiliated with any commercial ESG data provider.

---

*Built by Swikrit · [GitHub](https://github.com/swikrit-byte)*
