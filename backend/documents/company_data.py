"""
ESGIntel — Canonical company dataset (single source of truth)
=============================================================
Every document generator (reports .docx, decks .pptx, one-pagers .pdf,
policies .docx, spreadsheets .xlsx) imports figures from THIS module so all
deliverables stay internally consistent. All numbers below are the demo
subject's figures as surfaced throughout the ESGIntel platform UI.

Subject: VerdaSteelCo S.p.A.  (illustrative demo company)
"""

# ─────────────────────────────────────────────
# Brand / house style (McKinsey-style: restrained, decision-useful)
# ─────────────────────────────────────────────
BRAND = {
    "platform": "ESGIntel",
    "tagline": "AI-Assisted ESG Due Diligence Platform",
    "confidential": "CONFIDENTIAL — Prepared for internal investment use",
    # Core palette — warm, modern, Canva-esque (hex, no leading #)
    "ink":        "1B2B4B",   # deep navy (primary headings)
    "accent":     "2D7D6F",   # teal-green (primary accent — ESG/sustainability)
    "accent_lt":  "E3EFEC",   # pale teal fill / card tint
    "coral":      "E8825A",   # warm coral/orange (secondary accent, callouts)
    "coral_lt":   "FBE9E1",   # pale coral fill
    "slate":      "2E3A4F",   # body text (dark gray-navy)
    "muted":      "6B7280",   # secondary text
    "rule":       "E3DED4",   # hairline rules / warm table borders
    "red":        "C0392B",   # critical / high risk
    "amber":      "C77D11",   # medium risk (accessible amber)
    "green":      "2D7D6F",   # low risk / positive (teal, on-brand)
    "page_bg":    "FFFFFF",   # cards / surfaces stay white
    "band_bg":    "FAF8F5",   # warm off-white section band / page background
    "cream":      "F5F0E8",   # warm cream (cover / accent panels)
    "row_alt":    "F7F4EF",   # alternating warm-gray table rows
    # Font families (fall back gracefully if unavailable)
    "font_head":  "Calibri",  # clean sans-serif headings
    "font_body":  "Calibri",
}

# RGB tuples (for matplotlib / reportlab convenience)
def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def hex_rgb01(h):
    return tuple(c / 255 for c in hex_rgb(h))


COMPANY = {
    "name": "VerdaSteelCo S.p.A.",
    "short": "VerdaSteelCo",
    "sector": "Steel manufacturing (NACE C24 — Basic Metals)",
    "domicile": "Italy (EU27)",
    "ownership": "Founder family + private equity co-investor",
    "employees": 8400,
    "revenue_eur_bn": 1.20,
    "report_period": "FY2023",
    "as_of": "June 2024",
    "sites": [
        {"name": "Taranto", "country": "Italy", "note": "Largest, most carbon-intensive; partial 100-yr floodplain"},
        {"name": "Brescia", "country": "Italy", "note": "Oldest plant (1978); EAF + rolling"},
        {"name": "Genoa",   "country": "Italy", "note": "Finishing & logistics hub"},
        {"name": "Bilbao",  "country": "Spain", "note": "High water-stress basin (WRI 3.8/5)"},
    ],
    "process": "100% BF-BOF primary route + partial EAF scrap recycling",
}

# ─────────────────────────────────────────────
# Headline ESG scores  (0–100, higher = greater risk)
# ─────────────────────────────────────────────
SCORES = {
    "overall": 38,                 # composite (note: UI shows 38/100, bottom quartile)
    "overall_label": "High Risk",
    "overall_percentile": 19,      # P19 vs NACE C24 peers (bottom quartile)
    "confidence": 72,              # % overall confidence
    "pillars": {
        # pillar: (risk_score_0_100, weight, label)
        "Environmental": {"score": 64, "weight": 0.40, "label": "High",   "percentile": 81},
        "Social":        {"score": 57, "weight": 0.30, "label": "Medium", "percentile": 63},
        "Governance":    {"score": 49, "weight": 0.30, "label": "Medium", "percentile": 58},
    },
    "formula": "ESG Risk = (E×0.40) + (S×0.30) + (G×0.30); each pillar = Policy Maturity 40% + KPI Percentile 40% + Regulatory Exposure 20%",
}

# ─────────────────────────────────────────────
# Risk register  (the decision-useful core)
# severity from score: Critical>=75, High 55-74, Medium 35-54, Low <35
# ─────────────────────────────────────────────
def severity(score):
    if score >= 75: return "Critical"
    if score >= 55: return "High"
    if score >= 35: return "Medium"
    return "Low"

RISKS = [
    {"id": "ENV-01", "pillar": "E", "title": "EU ETS carbon cost escalation", "score": 89,
     "horizon": "2026–2030", "financial": "€68M/yr net by 2030",
     "summary": "Scope 1 of 842 ktCO2e against a rising ETS price and shrinking free allocation (≈40%→10% by 2030). Single largest quantifiable climate risk. No hedging policy or internal carbon price disclosed.",
     "action": "Stand up ETS management + hedging; set internal carbon price €75–100/t; build DRI/EAF business case."},
    {"id": "ENV-02", "pillar": "E", "title": "CBAM exposure on exports", "score": 84,
     "horizon": "Full phase-in 2026", "financial": "€18–28M/yr by 2027",
     "summary": "≈€280M non-EU revenue at ~0.85 tCO2e/t embedded carbon. Certificate cost scales directly with carbon intensity; only decarbonisation reduces liability.",
     "action": "Appoint CBAM compliance officer; register in EU CBAM portal; publish embedded-carbon reduction roadmap."},
    {"id": "ENV-03", "pillar": "E", "title": "Green-steel technology / asset stranding", "score": 76,
     "horizon": "2028–2035", "financial": "€200–350M impairment risk; €400–600M transition capex",
     "summary": "100% BF-BOF (~1.8–2.1 tCO2e/t) vs accelerating DRI-EAF hydrogen route at peers. Residual asset life risks stranding by 2032–2035.",
     "action": "Commission DRI/EAF feasibility for Taranto; evaluate hydrogen PPA; phased transition plan by 2032."},
    {"id": "ENV-04", "pillar": "E", "title": "Water scarcity at Bilbao & Taranto", "score": 74,
     "horizon": "RCP8.5 / 2050; permits under review", "financial": "≈€18M revenue + €4M cost at 30% cut",
     "summary": "High water-stress basins; 4.2 Mm³ withdrawal at only 12% recycling vs 45–60% best practice. Mandated reduction flagged for Bilbao by 2027.",
     "action": "Invest €12–18M in closed-loop recycling; target 40% withdrawal reduction by 2030."},
    {"id": "GOV-01", "pillar": "G", "title": "No whistleblower mechanism", "score": 72,
     "horizon": "Non-compliant since Dec 2021", "financial": "Regulatory + reputational",
     "summary": "No channel despite EU Directive 2019/1937 / D.Lgs. 24/2023. An outlier vs peers; an immediate, low-cost remediation.",
     "action": "Deploy confidential reporting channel + policy within 60 days."},
    {"id": "SOC-01", "pillar": "S", "title": "No Human Rights Policy / HRDD", "score": 70,
     "horizon": "CSDDD 2027", "financial": "Fines up to 5% turnover (≈€60M)",
     "summary": "No UNGP-aligned HRDD, Supplier Code of Conduct, or grievance mechanism despite high-risk sourcing (Brazil iron ore, DRC minerals).",
     "action": "Adopt UNGP-aligned Human Rights Policy; roll out supplier SAQ; launch grievance hotline (12-month plan, €250–500k)."},
    {"id": "POL-01", "pillar": "G", "title": "CSRD/ESRS readiness gap", "score": 71,
     "horizon": "First report FY2025 (Q1 2026)", "financial": "Programme €3–8M over 2 yrs",
     "summary": "Large PIE in scope from FY2025; double-materiality assessment immature and ESRS E1 transition plan absent. <18 months to first limited-assurance report.",
     "action": "Appoint CSRD programme manager; complete DMA; gap-analyse vs ESRS E1; engage assurance early."},
    {"id": "SOC-02", "pillar": "S", "title": "Occupational H&S — elevated LTIFR", "score": 66,
     "horizon": "Ongoing", "financial": "€8–15M per fatality; €12M/wk stoppage",
     "summary": "LTIFR 2.8 vs sector median 2.1 (33% above) with a FY2022 fatality. ISO 45001 at only 60% of sites.",
     "action": "Target LTIFR ≤1.5 by FY2026; extend ISO 45001 to 100%; add H&S KPI to executive LTIP."},
    {"id": "ENV-05", "pillar": "E", "title": "Supply-chain climate disruption", "score": 61,
     "horizon": "Acute + chronic", "financial": "≈€24M per 2-wk port closure",
     "summary": "34% iron ore via a single Brazilian supplier; cyclone-exposed ports; Turkey scrap exposed to water stress and logistics shocks.",
     "action": "Top-5 supplier climate assessment; 45-day ore buffer; develop Australian ore alternative."},
    {"id": "SOC-03", "pillar": "S", "title": "No SBTi target / market access", "score": 68,
     "horizon": "2025–2028", "financial": "≈€456M (38% revenue) automotive at risk",
     "summary": "Absent SBTi target blocks automotive Scope 3 supplier requirements (VW/Stellantis/BMW) and green-bond eligibility.",
     "action": "Commit to SBTi steel pathway and publish a validated target within 12 months."},
]

# ─────────────────────────────────────────────
# Key performance indicators vs NACE C24 peers (n=47)
# direction: "lower_better" or "higher_better"
# ─────────────────────────────────────────────
KPIS = [
    {"group": "Climate (E1)", "metric": "Scope 1 GHG", "value": "842,000 tCO2e", "peer": "—", "pctl": 89, "dir": "lower_better"},
    {"group": "Climate (E1)", "metric": "Scope 2 (location)", "value": "156,000 tCO2e", "peer": "—", "pctl": 70, "dir": "lower_better"},
    {"group": "Climate (E1)", "metric": "GHG intensity", "value": "0.73 tCO2e/€k", "peer": "0.61", "pctl": 58, "dir": "lower_better"},
    {"group": "Climate (E1)", "metric": "Renewable electricity", "value": "Not disclosed", "peer": "—", "pctl": None, "dir": "higher_better"},
    {"group": "Water (E3)",   "metric": "Water withdrawal", "value": "4.2 Mm³", "peer": "—", "pctl": 79, "dir": "lower_better"},
    {"group": "Water (E3)",   "metric": "Water recycling rate", "value": "12%", "peer": "45–60%", "pctl": 12, "dir": "higher_better"},
    {"group": "Circular (E5)","metric": "EAF scrap recycling", "value": "71%", "peer": "62%", "pctl": 44, "dir": "higher_better"},
    {"group": "Workforce (S1)","metric": "LTIFR", "value": "2.8 /M hrs", "peer": "2.1", "pctl": 89, "dir": "lower_better"},
    {"group": "Workforce (S1)","metric": "Fatalities (3-yr avg)", "value": "0.33 /yr", "peer": "0", "pctl": 95, "dir": "lower_better"},
    {"group": "Workforce (S1)","metric": "Female workforce", "value": "22%", "peer": "28%", "pctl": 42, "dir": "higher_better"},
    {"group": "Workforce (S1)","metric": "Training hours", "value": "24 hrs/yr", "peer": "21", "pctl": 58, "dir": "higher_better"},
    {"group": "Workforce (S1)","metric": "Employee turnover", "value": "9.2%", "peer": "11.4%", "pctl": 60, "dir": "lower_better"},
    {"group": "Workforce (S1)","metric": "Union density", "value": "87%", "peer": "72%", "pctl": 72, "dir": "higher_better"},
    {"group": "Governance (G1)","metric": "Board independence", "value": "78% (7/9)", "peer": "67%", "pctl": 75, "dir": "higher_better"},
    {"group": "Governance (G1)","metric": "Whistleblower mechanism", "value": "Absent", "peer": "Present (most)", "pctl": 5, "dir": "higher_better"},
    {"group": "Governance (G1)","metric": "ESG in executive pay", "value": "Absent", "peer": "78% have it", "pctl": 20, "dir": "higher_better"},
]

# ─────────────────────────────────────────────
# Financial exposure bridge (decision-useful €m)
# ─────────────────────────────────────────────
FINANCIAL_EXPOSURE = [
    {"driver": "EU ETS carbon cost (2030, net)", "amount_eur_m": 68, "type": "Recurring cost", "rating": "Critical"},
    {"driver": "CBAM certificates (2027)", "amount_eur_m": 24, "type": "Recurring cost", "rating": "Critical"},
    {"driver": "CSDDD non-compliance (max fine)", "amount_eur_m": 60, "type": "Contingent", "rating": "High"},
    {"driver": "Water restriction (revenue+cost)", "amount_eur_m": 22, "type": "Scenario", "rating": "High"},
    {"driver": "DRI/EAF transition capex", "amount_eur_m": 500, "type": "Capex (phased)", "rating": "Strategic"},
    {"driver": "Asset stranding (impairment risk)", "amount_eur_m": 275, "type": "Contingent", "rating": "High"},
]

# ─────────────────────────────────────────────
# Green-finance upside (the one clear opportunity)
# ─────────────────────────────────────────────
OPPORTUNITIES = [
    {"lever": "EU Green Bond (EuGBS)", "size": "€200–300M", "benefit": "30–50bp coupon saving (€0.6–1.5M/yr)", "precondition": "SBTi target + ESRS E1 plan"},
    {"lever": "Sustainability-Linked Loan", "size": "€200–250M", "benefit": "25–35bp margin saving", "precondition": "KPI targets (LTIFR, GHG, CSRD)"},
    {"lever": "EU Innovation Fund grant", "size": "€50–120M", "benefit": "Non-dilutive DRI/EAF funding", "precondition": "FY2025 call submission"},
]

# ─────────────────────────────────────────────
# Regulatory timeline
# ─────────────────────────────────────────────
REG_TIMELINE = [
    {"year": "2024", "item": "EU ETS Phase 4 free-allocation taper accelerates", "status": "Active"},
    {"year": "2025", "item": "CSRD/ESRS first reporting year (report Q1 2026)", "status": "In scope"},
    {"year": "2026", "item": "CBAM full financial phase-in begins", "status": "Imminent"},
    {"year": "2026", "item": "EU Pay Transparency Directive effects", "status": "Upcoming"},
    {"year": "2027", "item": "CSDDD human-rights & environmental due diligence", "status": "Non-compliant today"},
]

# ─────────────────────────────────────────────
# CSRD / ESRS readiness (RAG status) for the snapshot one-pager
# status: "red" | "amber" | "green"
# ─────────────────────────────────────────────
CSRD_READINESS = [
    {"std": "ESRS 2 — General disclosures", "status": "amber", "note": "Governance described; targets/processes incomplete"},
    {"std": "ESRS E1 — Climate change", "status": "red", "note": "No transition plan; no SBTi target; ETS/CBAM not quantified in report"},
    {"std": "ESRS E2 — Pollution", "status": "amber", "note": "Permits held; NOx/SOx data gaps"},
    {"std": "ESRS E3 — Water & marine", "status": "amber", "note": "Withdrawal known; no recycling target disclosed"},
    {"std": "ESRS E5 — Circular economy", "status": "green", "note": "EAF scrap 71% above sector median"},
    {"std": "ESRS S1 — Own workforce", "status": "amber", "note": "LTIFR + fatality require root-cause narrative"},
    {"std": "ESRS S2 — Value-chain workers", "status": "red", "note": "No HRDD, no supplier CoC, no grievance mechanism"},
    {"std": "ESRS G1 — Business conduct", "status": "red", "note": "No whistleblower channel; no ESG pay link"},
]

# ─────────────────────────────────────────────
# Climate scenario P&L (NGFS-style) for climate flash one-pager / climate report
# ─────────────────────────────────────────────
CLIMATE_SCENARIOS = [
    {"scenario": "Orderly (Net Zero 2050)", "carbon_2030": "€90/t", "pnl_2030_eur_m": -68, "note": "High near-term carbon cost; transition capex rewarded"},
    {"scenario": "Disorderly (Delayed)", "carbon_2030": "€120/t", "pnl_2030_eur_m": -96, "note": "Sharp late repricing; stranding risk elevated"},
    {"scenario": "Hot House (NDCs)", "carbon_2030": "€45/t", "pnl_2030_eur_m": -34, "note": "Lower carbon cost; higher physical (water/flood) damage"},
]

PHYSICAL_RISKS = [
    {"hazard": "Water scarcity", "score": 74, "sites": "Bilbao, Taranto"},
    {"hazard": "Chronic heat", "score": 58, "sites": "Taranto, Genoa"},
    {"hazard": "Coastal/river flood", "score": 52, "sites": "Taranto"},
    {"hazard": "Supply-chain disruption", "score": 61, "sites": "Brazil ports, Turkey"},
    {"hazard": "Extreme wind", "score": 28, "sites": "Brescia"},
    {"hazard": "Biodiversity/land use", "score": 24, "sites": "All (brownfield)"},
]
TRANSITION_RISKS = [
    {"driver": "EU ETS carbon cost", "score": 89},
    {"driver": "CBAM", "score": 84},
    {"driver": "Green-steel technology", "score": 76},
    {"driver": "Policy & regulation", "score": 71},
    {"driver": "Reputation / market access", "score": 68},
    {"driver": "Green-finance (opportunity)", "score": 22},
]

# ─────────────────────────────────────────────
# Engagement asks (what the investor wants the company to do)
# ─────────────────────────────────────────────
ENGAGEMENT_ASKS = [
    {"ask": "Commit to an SBTi-validated steel decarbonisation target", "owner": "Board / CEO", "by": "12 months", "priority": "Critical"},
    {"ask": "Publish an ESRS E1 climate transition plan (DRI/EAF roadmap)", "owner": "CSO", "by": "FY2025 report", "priority": "Critical"},
    {"ask": "Implement whistleblower mechanism (EU Dir. 2019/1937)", "owner": "General Counsel", "by": "60 days", "priority": "Immediate"},
    {"ask": "Adopt UNGP Human Rights Policy + supplier SAQ + grievance line", "owner": "CSO / Procurement", "by": "12 months", "priority": "High"},
    {"ask": "Add ESG KPIs to executive remuneration (LTIFR, GHG intensity)", "owner": "RemCo", "by": "Next AGM", "priority": "High"},
    {"ask": "Stand up CSRD programme + double-materiality assessment", "owner": "CFO / CSO", "by": "Immediate", "priority": "High"},
]

# ─────────────────────────────────────────────
# Filenames used by the UI  → logical document keys (for the router)
# ─────────────────────────────────────────────
ENGAGEMENT_FILES = {
    "ESG Risk Summary One-Pager.pdf":        ("onepager", "risk_summary"),
    "Climate Risk Flash Summary.pdf":        ("onepager", "climate_flash"),
    "CSRD Readiness Snapshot.pdf":           ("onepager", "csrd_readiness"),
    "ESG Engagement Deck Board.pptx":        ("deck", "board"),
    "Investor Presentation ESG.pptx":        ("deck", "investor"),
    "Human Rights Policy Template.docx":     ("policy", "human_rights"),
    "Whistleblower Policy Template.docx":    ("policy", "whistleblower"),
    "ESRS KPI Data Collection Template.xlsx":("spreadsheet", "esrs_kpi"),
    "Supplier ESG Self-Assessment SAQ.xlsx": ("spreadsheet", "supplier_saq"),
    "VerdaSteelCo_Climate_Risk_Report.pdf":  ("onepager", "climate_flash"),
    "VerdaSteelCo_ESG_Risk_Register.xlsx":   ("spreadsheet", "risk_register"),
}

# Report tab: report_type → human title
REPORT_TYPES = {
    "full":         "Full ESG Due Diligence Report",
    "exec":         "Executive Summary",
    "climate":      "Climate Risk Report (TCFD)",
    "engagement":   "ESG Engagement Letter",
    "riskregister": "Risk Register Export",
}


def slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
