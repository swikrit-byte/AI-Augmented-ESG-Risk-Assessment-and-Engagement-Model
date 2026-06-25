"""
ESGIntel — AI-Assisted ESG Due Diligence Platform
Streamlit frontend — calls FastAPI backend at localhost:8000
Run: streamlit run frontend/app.py
"""

import time
import requests
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ESGIntel — AI-Assisted ESG Due Diligence",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = "http://localhost:8000"

# ──────────────────────────────────────────────────────────────────────────────
# Custom CSS — Bloomberg/MSCI aesthetic
# ──────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Tokens ── */
:root {
  --accent:       #3154ff;
  --accent-light: #e8f0ff;
  --red:          #e24141;
  --red-light:    #fff2f2;
  --amber:        #d17f1e;
  --amber-light:  #fff4de;
  --green:        #2f855a;
  --green-light:  #e9f7ee;
  --blue:         #2563eb;
  --blue-light:   #e7f0ff;
  --text-primary: #102a43;
  --text-muted:   #627d98;
  --border:       rgba(145,158,171,0.18);
  --surface:      #ffffff;
  --surface-2:    #f6f8ff;
  --bg:           #f4f7fb;
  --radius:       14px;
}

/* Main bg */
.stApp { background: #f4f7fb; }

/* Hide default Streamlit header/footer */
#MainMenu, footer, header { visibility: hidden; }

/* Sidebar styling */
[data-testid="stSidebar"] {
  background: rgba(255,255,255,0.97);
  border-right: 1px solid rgba(145,158,171,0.14);
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
  font-size: 13px;
  color: #627d98;
}

/* Metric cards */
[data-testid="stMetric"] {
  background: white;
  border: 1px solid rgba(145,158,171,0.14);
  border-radius: 14px;
  padding: 16px 18px;
  box-shadow: 0 4px 16px rgba(15,25,35,0.06);
}
[data-testid="stMetricLabel"] { font-size: 12px !important; color: #627d98 !important; font-weight: 600 !important; text-transform: uppercase; letter-spacing: 0.5px; }
[data-testid="stMetricValue"] { font-size: 28px !important; font-weight: 800 !important; color: #102a43 !important; }

/* Expander */
[data-testid="stExpander"] {
  background: white;
  border: 1px solid rgba(145,158,171,0.14);
  border-radius: 10px;
  margin-bottom: 6px;
}

/* Tabs */
[data-testid="stTabs"] [role="tab"] {
  font-size: 13px;
  font-weight: 600;
  padding: 8px 16px;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  color: #3154ff;
  border-bottom: 2px solid #3154ff;
}

/* Buttons */
.stButton > button {
  border-radius: 999px;
  font-weight: 700;
  font-size: 14px;
  transition: all 0.15s;
}

/* DataFrames */
[data-testid="stDataFrame"] {
  border-radius: 10px;
  overflow: hidden;
}

/* Form inputs */
[data-testid="stTextInput"] input,
[data-testid="stSelectbox"] select,
[data-testid="stTextArea"] textarea {
  border-radius: 8px;
  border: 1px solid rgba(145,158,171,0.3);
  font-size: 14px;
}
</style>

<style>
/* ── Utility classes ── */
.badge-red   { display:inline-block; padding:3px 10px; border-radius:999px; font-size:11px; font-weight:700; background:#fff2f2; color:#e24141; }
.badge-amber { display:inline-block; padding:3px 10px; border-radius:999px; font-size:11px; font-weight:700; background:#fff4de; color:#d17f1e; }
.badge-green { display:inline-block; padding:3px 10px; border-radius:999px; font-size:11px; font-weight:700; background:#e9f7ee; color:#2f855a; }
.badge-blue  { display:inline-block; padding:3px 10px; border-radius:999px; font-size:11px; font-weight:700; background:#e7f0ff; color:#2563eb; }
.badge-gray  { display:inline-block; padding:3px 10px; border-radius:999px; font-size:11px; font-weight:700; background:#f1f5f9; color:#627d98; }

.card-box {
  background: white;
  border: 1px solid rgba(145,158,171,0.14);
  border-radius: 14px;
  padding: 16px 20px;
  box-shadow: 0 4px 16px rgba(15,25,35,0.06);
  margin-bottom: 12px;
}

.kpi-card {
  background: white;
  border-radius: 14px;
  padding: 18px 20px;
  border: 1px solid rgba(145,158,171,0.14);
  box-shadow: 0 4px 16px rgba(15,25,35,0.06);
  text-align: center;
}
.kpi-label { font-size: 11px; font-weight: 700; color: #627d98; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }
.kpi-value { font-size: 32px; font-weight: 800; color: #102a43; line-height: 1; }
.kpi-sub   { font-size: 12px; color: #627d98; margin-top: 4px; }

.signal-positive { border-left: 3px solid #2f855a; background: #e9f7ee; padding: 8px 12px; border-radius: 0 8px 8px 0; margin-bottom: 6px; }
.signal-negative { border-left: 3px solid #e24141; background: #fff2f2; padding: 8px 12px; border-radius: 0 8px 8px 0; margin-bottom: 6px; }
.signal-neutral  { border-left: 3px solid #2563eb; background: #e7f0ff; padding: 8px 12px; border-radius: 0 8px 8px 0; margin-bottom: 6px; }
.signal-label { font-size: 13px; font-weight: 700; color: #102a43; }
.signal-desc  { font-size: 12px; color: #627d98; margin-top: 2px; }

.evidence-box { background: #f6f8ff; border: 1px solid rgba(145,158,171,0.2); border-radius: 8px; padding: 10px 12px; margin-top: 8px; font-size: 12px; }
.evidence-source { font-weight: 700; color: #2563eb; margin-bottom: 3px; }
.evidence-text { color: #334e68; line-height: 1.5; }
.evidence-conf { color: #627d98; margin-top: 3px; font-style: italic; }

.risk-row { background: white; border: 1px solid rgba(145,158,171,0.14); border-radius: 10px; padding: 12px 16px; margin-bottom: 6px; cursor: pointer; }
.risk-name { font-size: 14px; font-weight: 700; color: #102a43; }
.risk-meta { font-size: 12px; color: #627d98; margin-top: 2px; }

.progress-step { display: flex; align-items: center; gap: 10px; padding: 6px 0; font-size: 13px; color: #334e68; }
.progress-done { color: #2f855a; font-weight: 600; }

.page-title { font-size: 26px; font-weight: 800; color: #102a43; letter-spacing: -0.4px; margin-bottom: 4px; }
.page-sub { font-size: 14px; color: #627d98; margin-bottom: 20px; }
</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# Session state initialisation
# ──────────────────────────────────────────────────────────────────────────────
def _init_state():
    defaults = {
        "page":        "input",
        "analysis_id": None,
        "result":      None,
        "company_name": "",
        "nace_code":   "C24",
        "website_url": "",
        "country":     "Italy",
        "employees":   "1,000 – 4,999",
        "revenue":     "€1B – €5B",
        "step":        1,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ──────────────────────────────────────────────────────────────────────────────
# API client
# ──────────────────────────────────────────────────────────────────────────────
def api_submit(company_name, website_url, nace_code, country, employees, revenue, files):
    data = {
        "company_name": company_name,
        "website_url":  website_url or "",
        "nace_code":    nace_code,
        "country":      country,
        "employees":    employees,
        "revenue":      revenue,
    }
    file_list = []
    if files:
        for f in files:
            file_list.append(("documents", (f.name, f.read(), f.type or "application/octet-stream")))
    else:
        # Send a stub file so the endpoint accepts it
        stub = b"Please analyse ESG risk based on publicly available information only."
        file_list.append(("documents", ("stub.txt", stub, "text/plain")))

    resp = requests.post(f"{API_BASE}/api/analyze", data=data, files=file_list, timeout=30)
    resp.raise_for_status()
    return resp.json()

def api_status(analysis_id):
    resp = requests.get(f"{API_BASE}/api/analyses/{analysis_id}/status", timeout=10)
    resp.raise_for_status()
    return resp.json()

def api_result(analysis_id):
    resp = requests.get(f"{API_BASE}/api/analyses/{analysis_id}", timeout=10)
    resp.raise_for_status()
    return resp.json()

def api_list():
    resp = requests.get(f"{API_BASE}/api/analyses", timeout=10)
    resp.raise_for_status()
    return resp.json()

def api_delete(analysis_id):
    resp = requests.delete(f"{API_BASE}/api/analyses/{analysis_id}", timeout=10)
    resp.raise_for_status()
    return resp.json()

def backend_ok():
    try:
        r = requests.get(f"{API_BASE}/", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
NACE_OPTIONS = [
    "A01 — Crop and Animal Production", "A02 — Forestry and Logging",
    "B05 — Mining of Hard Coal", "B06 — Extraction of Crude Petroleum and Natural Gas",
    "C10 — Manufacture of Food Products", "C13 — Manufacture of Textiles",
    "C20 — Manufacture of Chemicals and Chemical Products",
    "C21 — Manufacture of Pharmaceutical Products",
    "C22 — Manufacture of Rubber and Plastic Products",
    "C24 — Manufacture of Basic Metals",
    "C25 — Manufacture of Fabricated Metal Products",
    "C26 — Manufacture of Computer and Electronic Products",
    "C27 — Manufacture of Electrical Equipment",
    "C28 — Manufacture of Machinery and Equipment",
    "C29 — Manufacture of Motor Vehicles",
    "D35 — Electricity, Gas, Steam and Air Conditioning Supply",
    "E36 — Water Collection, Treatment and Supply",
    "E38 — Waste Collection, Treatment and Disposal",
    "F41 — Construction of Buildings", "F42 — Civil Engineering",
    "G46 — Wholesale Trade", "G47 — Retail Trade",
    "H49 — Land Transport and Transport via Pipelines",
    "H50 — Water Transport", "H51 — Air Transport",
    "I55 — Accommodation", "I56 — Food and Beverage Service Activities",
    "J62 — Computer Programming and Consultancy",
    "J63 — Information Service Activities",
    "K64 — Financial Service Activities",
    "K65 — Insurance and Pension Funding",
    "L68 — Real Estate Activities",
    "M69 — Legal and Accounting Activities",
    "M70 — Management Consultancy",
    "M71 — Architectural and Engineering Activities",
    "M72 — Scientific Research and Development",
    "N77 — Rental and Leasing Activities",
    "P85 — Education", "Q86 — Human Health Activities",
]

COUNTRIES = [
    "Austria", "Belgium", "Brazil", "Canada", "China", "Denmark", "Finland",
    "France", "Germany", "India", "Indonesia", "Italy", "Japan", "Mexico",
    "Netherlands", "Norway", "Poland", "Portugal", "South Africa",
    "South Korea", "Spain", "Sweden", "Switzerland", "Turkey",
    "United Kingdom", "United States", "Other",
]

EMPLOYEE_RANGES = ["1 – 49", "50 – 249", "250 – 999", "1,000 – 4,999",
                   "5,000 – 9,999", "10,000 – 49,999", "50,000+"]

REVENUE_RANGES  = ["Under €10M", "€10M – €50M", "€50M – €250M",
                   "€250M – €1B", "€1B – €5B", "€5B – €20B", "Over €20B"]

def score_color(score):
    """Return hex color for a 0-100 risk score."""
    if score is None:
        return "#627d98"
    if score >= 70:
        return "#e24141"
    if score >= 40:
        return "#d17f1e"
    return "#2f855a"

def score_badge_class(score):
    if score is None:
        return "badge-gray"
    if score >= 70:
        return "badge-red"
    if score >= 40:
        return "badge-amber"
    return "badge-green"

def severity_badge(sev):
    m = {"Critical": "badge-red", "High": "badge-red",
         "Medium": "badge-amber", "Low": "badge-green"}
    cls = m.get(sev, "badge-gray")
    return f'<span class="{cls}">{sev}</span>'

def confidence_badge(conf):
    m = {"high": "badge-green", "medium": "badge-amber", "low": "badge-red"}
    cls = m.get((conf or "").lower(), "badge-gray")
    return f'<span class="{cls}">{(conf or "").title()}</span>'

def gauge_chart(value, title, max_val=100):
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        title={"text": title, "font": {"size": 13, "color": "#627d98"}},
        number={"font": {"size": 28, "color": score_color(value), "family": "Inter"}},
        gauge={
            "axis": {"range": [0, max_val], "tickwidth": 1},
            "bar": {"color": score_color(value)},
            "bgcolor": "white",
            "borderwidth": 0,
            "steps": [
                {"range": [0, 40],  "color": "#e9f7ee"},
                {"range": [40, 70], "color": "#fff4de"},
                {"range": [70, 100],"color": "#fff2f2"},
            ],
        },
    ))
    fig.update_layout(
        height=180, margin=dict(l=20, r=20, t=30, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif"),
    )
    return fig

def radar_chart(data: dict):
    cats  = list(data.keys())
    vals  = list(data.values())
    vals += [vals[0]]
    cats += [cats[0]]
    fig = go.Figure(go.Scatterpolar(
        r=vals, theta=cats, fill="toself",
        fillcolor="rgba(49,84,255,0.12)", line=dict(color="#3154ff", width=2),
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=False,
        height=300,
        margin=dict(l=20, r=20, t=20, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig

def materiality_matrix(topics: list):
    if not topics:
        return None
    df = pd.DataFrame(topics)
    df["financial_score"] = pd.to_numeric(df.get("financial_score"), errors="coerce").fillna(3)
    df["impact_score"]    = pd.to_numeric(df.get("impact_score"),    errors="coerce").fillna(3)
    color_map = {"environmental": "#2f855a", "social": "#2563eb", "governance": "#d17f1e"}
    df["color"] = df.get("category", "").map(color_map).fillna("#627d98")

    fig = go.Figure()
    for cat, grp in df.groupby("category"):
        fig.add_trace(go.Scatter(
            x=grp["financial_score"], y=grp["impact_score"],
            mode="markers+text",
            marker=dict(size=16, color=color_map.get(cat, "#627d98"), opacity=0.85,
                        line=dict(width=1, color="white")),
            text=grp["topic"], textposition="top center",
            textfont=dict(size=10, color="#102a43"),
            name=cat.title(),
        ))

    fig.add_shape(type="line", x0=3, y0=0, x1=3, y1=5.5,
                  line=dict(dash="dot", color="#cbd5e0", width=1))
    fig.add_shape(type="line", x0=0, y0=3, x1=5.5, y1=3,
                  line=dict(dash="dot", color="#cbd5e0", width=1))

    fig.update_layout(
        xaxis=dict(title="Financial Materiality →", range=[0, 5.5], tickvals=[1,2,3,4,5]),
        yaxis=dict(title="Impact Materiality →",    range=[0, 5.5], tickvals=[1,2,3,4,5]),
        height=440,
        margin=dict(l=40, r=20, t=20, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#f6f8ff",
        legend=dict(orientation="h", y=-0.15),
        font=dict(family="Inter, sans-serif", size=12),
    )
    return fig

def risk_bar_chart(risks: list):
    if not risks:
        return None
    df = pd.DataFrame(risks)[["name", "score", "category", "severity"]].copy()
    df["score"] = pd.to_numeric(df["score"], errors="coerce").fillna(0)
    df = df.sort_values("score", ascending=True).tail(12)
    color_map = {"environmental": "#2f855a", "social": "#2563eb",
                 "governance": "#d17f1e", "climate": "#6366f1"}
    df["color"] = df["category"].map(color_map).fillna("#627d98")

    fig = go.Figure(go.Bar(
        x=df["score"], y=df["name"],
        orientation="h",
        marker_color=df["color"],
        text=df["score"].astype(int).astype(str),
        textposition="outside",
    ))
    fig.update_layout(
        height=max(300, len(df) * 36),
        xaxis=dict(range=[0, 105], title="Risk Score (0–100)"),
        yaxis=dict(tickfont=dict(size=12)),
        margin=dict(l=0, r=40, t=10, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", size=12),
        showlegend=False,
    )
    return fig


# ──────────────────────────────────────────────────────────────────────────────
# Sidebar navigation
# ──────────────────────────────────────────────────────────────────────────────
def render_sidebar():
    with st.sidebar:
        st.markdown("""
        <div style="display:flex;align-items:center;gap:10px;padding:6px 0 18px">
          <div style="width:32px;height:32px;background:#3154ff;border-radius:8px;display:flex;
               align-items:center;justify-content:center;font-size:16px;">🌱</div>
          <div>
            <div style="font-weight:800;font-size:16px;color:#102a43;letter-spacing:-.3px">ESGIntel</div>
            <div style="font-size:10px;font-weight:500;color:#627d98;text-transform:uppercase;letter-spacing:.5px">Due Diligence Platform</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        has_result = st.session_state.result is not None

        # New Assessment button (always visible)
        if st.button("＋  New Assessment", use_container_width=True, type="primary"):
            st.session_state.page        = "input"
            st.session_state.step        = 1
            st.session_state.analysis_id = None
            st.session_state.result      = None
            st.rerun()

        st.markdown("---")

        if has_result:
            co = st.session_state.result.get("company", {})
            scores = st.session_state.result.get("esg_scores", {})
            st.markdown(f"""
            <div class="card-box" style="margin-bottom:12px">
              <div style="font-size:11px;color:#627d98;text-transform:uppercase;font-weight:700;letter-spacing:.5px">Active Assessment</div>
              <div style="font-size:14px;font-weight:800;color:#102a43;margin-top:4px">{co.get("name","—")}</div>
              <div style="font-size:12px;color:#627d98;margin-top:2px">NACE {co.get("nace_code","—")} · {co.get("country","—")}</div>
              <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">
                <span class="{score_badge_class(scores.get('overall'))}">ESG {scores.get('overall','—')}</span>
                <span class="{score_badge_class(scores.get('environmental'))}">E:{scores.get('environmental','—')}</span>
                <span class="{score_badge_class(scores.get('social'))}">S:{scores.get('social','—')}</span>
                <span class="{score_badge_class(scores.get('governance'))}">G:{scores.get('governance','—')}</span>
              </div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("**ANALYSIS**")
            pages_main = {
                "📊 Dashboard":             "dashboard",
                "🏢 Company Profile":       "profile",
                "⚖️ Materiality Assessment": "materiality",
            }
            for label, key in pages_main.items():
                active = st.session_state.page == key
                if st.button(label, key=f"nav_{key}", use_container_width=True,
                             type="secondary" if not active else "primary"):
                    st.session_state.page = key
                    st.rerun()

            st.markdown("**ESG RISK**")
            pages_risk = {
                "🔴 ESG Risk Overview":     "esg_risk",
                "🌿 Environmental":         "environmental",
                "👥 Social":               "social",
                "🏛️ Governance":            "governance",
            }
            for label, key in pages_risk.items():
                active = st.session_state.page == key
                if st.button(label, key=f"nav_{key}", use_container_width=True,
                             type="secondary" if not active else "primary"):
                    st.session_state.page = key
                    st.rerun()

            st.markdown("**CLIMATE & ACTIONS**")
            pages_action = {
                "🌡️ Climate Risk":          "climate",
                "💬 ESG Engagement":        "engagement",
                "📄 Report Generator":      "reports",
            }
            for label, key in pages_action.items():
                active = st.session_state.page == key
                if st.button(label, key=f"nav_{key}", use_container_width=True,
                             type="secondary" if not active else "primary"):
                    st.session_state.page = key
                    st.rerun()

        else:
            st.markdown("""
            <div style="font-size:13px;color:#627d98;padding:8px 0">
              Start a new assessment to unlock all analysis modules.
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")

        # Past analyses
        st.markdown("**PAST ANALYSES**")
        try:
            past = api_list()
            if past:
                for item in past[:5]:
                    status_icon = "✅" if item["status"] == "complete" else ("⏳" if item["status"] == "processing" else "❌")
                    if st.button(
                        f"{status_icon} {item['company_name'][:22]}",
                        key=f"past_{item['id']}",
                        use_container_width=True
                    ):
                        if item["status"] == "complete":
                            full = api_result(item["id"])
                            st.session_state.analysis_id = item["id"]
                            st.session_state.result = full.get("result", full)
                            st.session_state.page = "dashboard"
                            st.rerun()
            else:
                st.markdown("<span style='font-size:12px;color:#627d98'>No past analyses</span>",
                            unsafe_allow_html=True)
        except Exception:
            st.markdown("<span style='font-size:12px;color:#e24141'>⚠ Backend offline</span>",
                        unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# Page: New Assessment (Input form + upload + run)
# ──────────────────────────────────────────────────────────────────────────────
def page_input():
    st.markdown('<div class="page-title">New ESG Assessment</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Complete mandatory inputs and upload supporting documents to begin.</div>', unsafe_allow_html=True)

    # Step indicator
    step = st.session_state.step
    step_labels = ["Company Inputs", "Upload Documents", "Run Assessment"]
    cols = st.columns(len(step_labels))
    for i, (col, label) in enumerate(zip(cols, step_labels), 1):
        with col:
            color  = "#3154ff" if i == step else ("#2f855a" if i < step else "#cbd5e0")
            weight = "800" if i == step else "600"
            st.markdown(f"""
            <div style="text-align:center">
              <div style="width:32px;height:32px;border-radius:50%;background:{color};
                   color:white;font-size:13px;font-weight:800;line-height:32px;
                   margin:0 auto 6px">{'✓' if i < step else i}</div>
              <div style="font-size:12px;font-weight:{weight};color:{color if i <= step else '#627d98'}">{label}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Step 1: Company Inputs ──
    if step == 1:
        with st.form("step1_form"):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### Mandatory Inputs")
                company_name = st.text_input("Company Name *",
                    value=st.session_state.company_name,
                    placeholder="e.g. Acme Manufacturing S.p.A.",
                    help="Used for external research, news monitoring, regulatory databases, ESG controversies.")

                nace_opts = NACE_OPTIONS
                nace_idx  = next((i for i, o in enumerate(nace_opts)
                                  if o.startswith(st.session_state.nace_code)), 9)
                nace_sel  = st.selectbox("NACE Sector Code *", nace_opts, index=nace_idx,
                    help="Primary driver for material ESG topics per ESRS, ISSB, SASB, GRI sector standards.")

                website_url = st.text_input("Company Website *",
                    value=st.session_state.website_url,
                    placeholder="https://company.com",
                    help="Used for public intelligence assessment when no documents are uploaded.")

            with c2:
                st.markdown("#### Company Context")
                country_idx = COUNTRIES.index(st.session_state.country) if st.session_state.country in COUNTRIES else 11
                country   = st.selectbox("Country / Region *", COUNTRIES, index=country_idx)

                emp_idx   = EMPLOYEE_RANGES.index(st.session_state.employees) if st.session_state.employees in EMPLOYEE_RANGES else 3
                employees = st.selectbox("Employee Range *", EMPLOYEE_RANGES, index=emp_idx)

                rev_idx   = REVENUE_RANGES.index(st.session_state.revenue) if st.session_state.revenue in REVENUE_RANGES else 4
                revenue   = st.selectbox("Annual Revenue (EUR) *", REVENUE_RANGES, index=rev_idx)

                st.markdown("""
                <div class="card-box" style="margin-top:14px">
                  <div style="font-size:12px;font-weight:700;color:#627d98;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Assessment Mode</div>
                  <div style="font-size:13px;color:#334e68">
                    📄 <strong>Document mode</strong> — if you upload PDFs/reports<br>
                    🌐 <strong>Public intelligence mode</strong> — if you only provide a website URL
                  </div>
                </div>
                """, unsafe_allow_html=True)

            submitted = st.form_submit_button("Continue to Upload →", type="primary", use_container_width=True)
            if submitted:
                if not company_name:
                    st.error("Company name is required.")
                else:
                    st.session_state.company_name = company_name
                    st.session_state.nace_code    = nace_sel.split(" — ")[0]
                    st.session_state.website_url  = website_url
                    st.session_state.country      = country
                    st.session_state.employees    = employees
                    st.session_state.revenue      = revenue
                    st.session_state.step         = 2
                    st.rerun()

    # ── Step 2: Upload Documents ──
    elif step == 2:
        st.markdown(f"#### Uploading for: **{st.session_state.company_name}**")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("##### 📄 ESG Documents (Optional)")
            st.caption("PDF or TXT — policies, sustainability reports, annual reports, TCFD disclosures")
            uploaded_files = st.file_uploader(
                "Drop documents here",
                accept_multiple_files=True,
                type=["pdf", "txt"],
                key="doc_uploader",
                label_visibility="collapsed",
            )
            if uploaded_files:
                for f in uploaded_files:
                    st.markdown(f"✅ `{f.name}` ({round(f.size/1024, 1)} KB)")
            else:
                st.info("No documents uploaded — will run in Public Intelligence mode using the company website.")

        with c2:
            st.markdown("##### 📊 Quantitative ESG Data (Optional)")
            st.caption("Excel, CSV, PDF — GHG emissions, energy, water, waste, safety, diversity")
            data_files = st.file_uploader(
                "Drop data files here",
                accept_multiple_files=True,
                type=["pdf", "csv", "xlsx", "xls"],
                key="data_uploader",
                label_visibility="collapsed",
            )

            st.markdown("""
            <div class="card-box" style="margin-top:12px">
              <div style="font-size:12px;font-weight:700;color:#2563eb;margin-bottom:6px">What AI extracts:</div>
              <div style="font-size:12px;color:#334e68;line-height:1.8">
                🏭 GHG emissions (Scope 1, 2, 3)<br>
                ⚡ Energy consumption & intensity<br>
                💧 Water withdrawal & stress<br>
                🦺 LTIFR, TRIR, fatalities<br>
                👩 Board diversity & gender pay<br>
                ♻️ Waste generation & recycling<br>
                📋 Policy maturity & assurance
              </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")
        bc1, bc2, bc3 = st.columns([1, 1, 1])
        with bc1:
            if st.button("← Back", use_container_width=True):
                st.session_state.step = 1
                st.rerun()
        with bc3:
            if st.button("Continue to Run Assessment →", type="primary", use_container_width=True):
                st.session_state["queued_files"] = uploaded_files or []
                st.session_state.step = 3
                st.rerun()

    # ── Step 3: Run Assessment ──
    elif step == 3:
        st.markdown(f"#### Ready to analyse: **{st.session_state.company_name}**")
        c1, c2 = st.columns([1, 1])
        with c1:
            st.markdown("""
            <div class="card-box">
              <div style="font-size:13px;font-weight:700;color:#627d98;margin-bottom:8px">ASSESSMENT INPUTS</div>
            </div>
            """, unsafe_allow_html=True)
            st.write(f"**Company:** {st.session_state.company_name}")
            st.write(f"**NACE Code:** {st.session_state.nace_code}")
            st.write(f"**Website:** {st.session_state.website_url or '—'}")
            st.write(f"**Country:** {st.session_state.country}")
            st.write(f"**Employees:** {st.session_state.employees}")
            st.write(f"**Revenue:** {st.session_state.revenue}")

            files = st.session_state.get("queued_files", [])
            if files:
                st.write(f"**Documents:** {len(files)} file(s) uploaded")
            else:
                st.info("📡 No documents — Public Intelligence mode (website scraping)")

        with c2:
            st.markdown("""
            <div class="card-box">
              <div style="font-size:13px;font-weight:700;color:#627d98;margin-bottom:8px">ANALYSIS PIPELINE</div>
              <div style="font-size:13px;color:#334e68;line-height:2">
                1. 📑 PDF discovery & report extraction<br>
                2. 🌐 Website scraping (public intelligence)<br>
                3. 🤖 AI Call 1 — Company profile & scores<br>
                4. 🤖 AI Call 2 — Deep risk, materiality & climate<br>
                5. 📊 KPI extraction (Opus structured pipeline)<br>
                6. 🏁 Results ready
              </div>
            </div>
            """, unsafe_allow_html=True)

        if not backend_ok():
            st.error("⚠️ Backend is offline. Start the FastAPI server first: `uvicorn app:app --reload --port 8000` in the `backend/` directory.")
            return

        bc1, bc2, bc3 = st.columns([1, 2, 1])
        with bc1:
            if st.button("← Back", use_container_width=True):
                st.session_state.step = 2
                st.rerun()
        with bc2:
            run_btn = st.button("🚀 Run ESG Assessment", type="primary", use_container_width=True)

        if run_btn:
            with st.spinner("Submitting analysis…"):
                try:
                    files = st.session_state.get("queued_files", [])
                    resp  = api_submit(
                        st.session_state.company_name,
                        st.session_state.website_url,
                        st.session_state.nace_code,
                        st.session_state.country,
                        st.session_state.employees,
                        st.session_state.revenue,
                        files if files else None,
                    )
                    st.session_state.analysis_id = resp["id"]
                    st.session_state.page = "running"
                    st.rerun()
                except Exception as e:
                    st.error(f"Submission failed: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Page: Running (progress polling)
# ──────────────────────────────────────────────────────────────────────────────
def page_running():
    aid = st.session_state.analysis_id
    st.markdown('<div class="page-title">🔄 Running ESG Assessment</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="page-sub">Company: <strong>{st.session_state.company_name}</strong> · Analysis ID: <code>{aid[:8]}…</code></div>',
                unsafe_allow_html=True)

    status_ph = st.empty()
    logs_ph   = st.empty()
    prog_ph   = st.progress(0)

    max_polls = 240  # 4 minutes
    for i in range(max_polls):
        try:
            status_data = api_status(aid)
        except Exception as e:
            status_ph.error(f"Polling error: {e}")
            time.sleep(3)
            continue

        status = status_data.get("status", "processing")
        logs   = status_data.get("logs", [])

        n_done = sum(1 for l in logs if l.get("done"))
        total  = max(len(logs), 1)
        prog_ph.progress(min(n_done / max(total, 6), 0.95))

        with logs_ph.container():
            st.markdown("**Progress log:**")
            for entry in logs[-12:]:
                icon   = "✅" if entry.get("done") else "⏳"
                elapsed = f"[{entry.get('elapsed',''):.0f}s]" if entry.get("elapsed") else ""
                cls    = "progress-done" if entry.get("done") else "progress-step"
                st.markdown(f'<div class="{cls}">{icon} {entry.get("msg","")} <span style="color:#cbd5e0;font-size:11px">{elapsed}</span></div>',
                            unsafe_allow_html=True)

        if status == "complete":
            prog_ph.progress(1.0)
            status_ph.success("✅ Assessment complete!")
            time.sleep(0.8)
            try:
                full = api_result(aid)
                st.session_state.result = full.get("result", full)
                st.session_state.page   = "dashboard"
                st.rerun()
            except Exception as e:
                st.error(f"Could not load result: {e}")
            return

        elif status == "error":
            status_ph.error(f"❌ Analysis failed: {status_data.get('error','Unknown error')}")
            if st.button("← Back to Input"):
                st.session_state.page = "input"
                st.session_state.step = 1
                st.rerun()
            return

        time.sleep(3)

    st.warning("Analysis is taking longer than expected. It may still be running — check back shortly.")


# ──────────────────────────────────────────────────────────────────────────────
# Page: Dashboard
# ──────────────────────────────────────────────────────────────────────────────
def page_dashboard():
    r      = st.session_state.result or {}
    co     = r.get("company",   {})
    scores = r.get("esg_scores",{})
    ov     = r.get("overview",  {})
    cov    = r.get("data_coverage", {})
    mode   = r.get("_mode", "document")

    # ── Header ──
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown('<div class="page-title">📊 Dashboard</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="page-sub">{ov.get("esg_summary","")}</div>', unsafe_allow_html=True)
    with c2:
        if mode == "public_intelligence":
            st.markdown('<span class="badge-blue">🌐 Public Intelligence Mode</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="badge-green">📄 Document Mode</span>', unsafe_allow_html=True)
        docs = cov.get("documents_analyzed", 0)
        year = cov.get("reporting_year", "—")
        st.caption(f"Docs reviewed: {docs} · Reporting year: {year} · Confidence: {scores.get('confidence','—')}/100")

    # ── Analyst Snapshot banner ──
    overall = scores.get("overall", 0)
    conf    = scores.get("confidence", 0)
    tier    = "High Risk" if overall >= 70 else ("Medium Risk" if overall >= 40 else "Low Risk")
    tier_color = "#e24141" if overall >= 70 else ("#d17f1e" if overall >= 40 else "#2f855a")

    st.markdown(f"""
    <div class="card-box" style="border-left:4px solid {tier_color};display:flex;gap:24px;align-items:center;flex-wrap:wrap">
      <div>
        <div style="font-size:11px;color:#627d98;font-weight:700;text-transform:uppercase;letter-spacing:.5px">Company Quality Rating</div>
        <div style="font-size:20px;font-weight:800;color:#102a43;margin-top:2px">{co.get("name","—")}</div>
        <div style="font-size:13px;color:#627d98">{co.get("sector","—")} · {co.get("country","—")}</div>
      </div>
      <div style="margin-left:auto;text-align:center">
        <div style="font-size:11px;color:#627d98;font-weight:700;text-transform:uppercase">ESG Risk Tier</div>
        <div style="font-size:22px;font-weight:800;color:{tier_color}">{tier}</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:11px;color:#627d98;font-weight:700;text-transform:uppercase">Confidence</div>
        <div style="font-size:22px;font-weight:800;color:#102a43">{conf}/100</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:11px;color:#627d98;font-weight:700;text-transform:uppercase">Docs Reviewed</div>
        <div style="font-size:22px;font-weight:800;color:#102a43">{docs}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── KPI Cards ──
    st.markdown("#### ESG Risk Scores")
    kc1, kc2, kc3, kc4, kc5 = st.columns(5)
    kpi_data = [
        (kc1, "Overall ESG Score",    scores.get("overall",       0)),
        (kc2, "Environmental Risk",   scores.get("environmental", 0)),
        (kc3, "Social Risk",          scores.get("social",        0)),
        (kc4, "Governance Risk",      scores.get("governance",    0)),
        (kc5, "Data Confidence",      scores.get("confidence",    0)),
    ]
    for col, label, val in kpi_data:
        with col:
            color = score_color(val)
            st.markdown(f"""
            <div class="kpi-card">
              <div class="kpi-label">{label}</div>
              <div class="kpi-value" style="color:{color}">{val}</div>
              <div class="kpi-sub">/100</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Radar + Signals ──
    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.markdown("#### ESG Risk Radar")
        radar_data = {
            "Environmental": scores.get("environmental", 0),
            "Social":        scores.get("social",        0),
            "Governance":    scores.get("governance",    0),
        }
        # Add climate if available
        climate_risks = r.get("climate", {})
        if climate_risks:
            phys_avg = 0
            if climate_risks.get("physical_risks"):
                phys_avg = sum(x.get("score",0) for x in climate_risks["physical_risks"]) / len(climate_risks["physical_risks"])
            if phys_avg:
                radar_data["Climate (Physical)"] = phys_avg
        st.plotly_chart(radar_chart(radar_data), use_container_width=True)

    with col_right:
        st.markdown("#### ESG Signal Feed")
        signals = r.get("signals", [])
        if signals:
            for sig in signals[:6]:
                stype = sig.get("type", "neutral")
                cls   = f"signal-{stype}"
                fw    = sig.get("framework", "")
                st.markdown(f"""
                <div class="{cls}">
                  <div class="signal-label">{sig.get("label","")}</div>
                  <div class="signal-desc">{sig.get("description","")}</div>
                  <div style="font-size:11px;color:#627d98;margin-top:3px">{fw} · Confidence: {sig.get("confidence","—")}</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No signals available.")

    # ── Material Topics Overview ──
    st.markdown("#### Material Topic Overview")
    topics = r.get("material_topics", [])
    if topics:
        df = pd.DataFrame(topics)
        show_cols = [c for c in ["topic", "category", "impact_score", "financial_score", "confidence", "trend"] if c in df.columns]
        st.dataframe(df[show_cols].sort_values("impact_score", ascending=False) if "impact_score" in df.columns else df[show_cols],
                     use_container_width=True, hide_index=True)
    else:
        st.info("No material topics available.")

    # ── Strengths & Gaps ──
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("#### Key Strengths")
        for s in ov.get("key_strengths", []):
            st.markdown(f'✅ {s}')
    with g2:
        st.markdown("#### Key Gaps")
        for g in ov.get("key_gaps", []):
            st.markdown(f'🔴 {g}')


# ──────────────────────────────────────────────────────────────────────────────
# Page: Company Profile
# ──────────────────────────────────────────────────────────────────────────────
def page_profile():
    r   = st.session_state.result or {}
    co  = r.get("company", {})
    ov  = r.get("overview",{})
    cov = r.get("data_coverage",{})
    geo = r.get("geographic_exposure", [])
    pol = r.get("policy_maturity", [])
    disc = r.get("disclosure_gaps", [])

    st.markdown('<div class="page-title">🏢 Company Profile</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Business overview, corporate structure, and ESG maturity snapshot.</div>', unsafe_allow_html=True)

    # ── Header strip ──
    h1, h2, h3, h4 = st.columns(4)
    fields = [
        (h1, "Sector",     f"NACE {co.get('nace_code','—')} — {co.get('sector','—')}"),
        (h2, "Country",    co.get("country", "—")),
        (h3, "Employees",  co.get("employees", "—")),
        (h4, "Revenue",    co.get("revenue", "—")),
    ]
    for col, label, val in fields:
        with col:
            st.metric(label, val)

    # ── Business overview ──
    st.markdown("#### Business Overview")
    st.markdown(f"""
    <div class="card-box">
      <div style="font-size:15px;color:#334e68;line-height:1.7">{ov.get("business_summary","—")}</div>
    </div>
    """, unsafe_allow_html=True)

    # ── ESG Maturity ──
    if pol:
        st.markdown("#### ESG Maturity Snapshot")
        for p in pol:
            level = p.get("level", 0)
            label = p.get("level_label", f"Level {level}")
            area  = p.get("policy_area", "")
            color = ["#cbd5e0","#e24141","#d17f1e","#ecc94b","#68d391","#2f855a"][min(level, 5)]
            bar_w = f"{level * 20}%"
            st.markdown(f"""
            <div style="margin-bottom:12px">
              <div style="display:flex;justify-content:space-between;margin-bottom:4px">
                <span style="font-size:13px;font-weight:700;color:#102a43">{area}</span>
                <span style="font-size:12px;color:#627d98">{label}</span>
              </div>
              <div style="height:6px;background:#eef3fb;border-radius:3px;overflow:hidden">
                <div style="height:100%;width:{bar_w};background:{color};border-radius:3px;transition:width .3s"></div>
              </div>
              <div style="font-size:11.5px;color:#627d98;margin-top:3px">{p.get("observable_evidence","")}</div>
            </div>
            """, unsafe_allow_html=True)

    # ── Geographic Exposure ──
    if geo:
        st.markdown("#### Geographic Exposure")
        geo_df = pd.DataFrame(geo)
        if "lat" in geo_df.columns and "lng" in geo_df.columns:
            # Map
            geo_df["lat"] = pd.to_numeric(geo_df["lat"], errors="coerce")
            geo_df["lng"] = pd.to_numeric(geo_df["lng"], errors="coerce")
            size_col = [12] * len(geo_df)
            color_vals = geo_df["risk_level"].map({"high": 3, "medium": 2, "low": 1}).fillna(2)
            fig = go.Figure(go.Scattergeo(
                lat=geo_df["lat"], lon=geo_df["lng"],
                text=geo_df.apply(lambda row: f"{row.get('country','?')} — {row.get('role','?')}<br>{row.get('rationale',''[:60])}", axis=1),
                mode="markers+text",
                marker=dict(
                    size=14,
                    color=color_vals,
                    colorscale=[[0,"#2f855a"],[0.5,"#d17f1e"],[1,"#e24141"]],
                    showscale=False,
                    line=dict(width=1, color="white"),
                ),
                textposition="top center",
                textfont=dict(size=10),
            ))
            fig.update_layout(
                geo=dict(showframe=False, showcoastlines=True,
                         coastlinecolor="#e2e8f0", landcolor="#f8fafc",
                         oceancolor="#e7f0ff", showocean=True, showlakes=True),
                height=340,
                margin=dict(l=0, r=0, t=0, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig, use_container_width=True)

        show_cols = [c for c in ["country","role","risk_level","climate_risk","rationale"] if c in geo_df.columns]
        st.dataframe(geo_df[show_cols], use_container_width=True, hide_index=True)

    # ── Disclosure Gaps ──
    if disc:
        st.markdown("#### Disclosure Gaps")
        for gap in disc:
            sev = gap.get("severity", "Medium")
            st.markdown(f"""
            <div class="card-box" style="border-left:3px solid {'#e24141' if sev=='Critical' else '#d17f1e' if sev in ('High','Medium') else '#2f855a'}">
              <div style="display:flex;justify-content:space-between">
                <div style="font-size:13px;font-weight:700">{gap.get("area","")}</div>
                {severity_badge(sev)}
              </div>
              <div style="font-size:12px;color:#627d98;margin-top:4px">{gap.get("type","")}</div>
              <div style="font-size:13px;color:#334e68;margin-top:6px">{gap.get("explanation","")}</div>
              <div style="font-size:12px;color:#2563eb;margin-top:4px">💡 {gap.get("recommendation","")}</div>
            </div>
            """, unsafe_allow_html=True)

    # ── Data Coverage ──
    st.markdown("#### Data Coverage & Completeness")
    d1, d2, d3, d4 = st.columns(4)
    with d1:
        st.metric("Documents Analyzed", cov.get("documents_analyzed", 0))
    with d2:
        st.metric("Reporting Year", cov.get("reporting_year", "—"))
    with d3:
        st.metric("Assurance Level", cov.get("assurance", "Unknown"))
    with d4:
        st.metric("Scope 3 Disclosed", "Yes" if cov.get("scope3_disclosed") else "No")

    fwks = cov.get("frameworks_referenced", [])
    if fwks:
        st.markdown("**Frameworks referenced:** " + " · ".join(f"`{f}`" for f in fwks))


# ──────────────────────────────────────────────────────────────────────────────
# Page: Materiality Assessment
# ──────────────────────────────────────────────────────────────────────────────
def page_materiality():
    r      = st.session_state.result or {}
    topics = r.get("material_topics", [])

    st.markdown('<div class="page-title">⚖️ Materiality Assessment</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Dual materiality (financial + impact). Sources: SASB sector standards, ESRS, GRI 3.</div>', unsafe_allow_html=True)

    if not topics:
        st.info("No material topics in this assessment.")
        return

    # Filter controls
    cats = ["All"] + sorted({t.get("category","") for t in topics if t.get("category")})
    cat_filter = st.selectbox("Filter by category", cats, key="mat_cat_filter")
    filtered = topics if cat_filter == "All" else [t for t in topics if t.get("category") == cat_filter]

    # ── Dual materiality matrix ──
    st.markdown("#### Dual Materiality Matrix")
    fig = materiality_matrix(filtered)
    if fig:
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("""
    <div style="display:flex;gap:16px;font-size:12px;color:#627d98;margin-bottom:16px">
      <span>● <span style="color:#2f855a">Environmental</span></span>
      <span>● <span style="color:#2563eb">Social</span></span>
      <span>● <span style="color:#d17f1e">Governance</span></span>
    </div>
    """, unsafe_allow_html=True)

    # ── Topic table ──
    st.markdown("#### Material Topic Detail")
    for t in sorted(filtered, key=lambda x: -(x.get("impact_score",0) + x.get("financial_score",0))):
        imp = t.get("impact_score",   0)
        fin = t.get("financial_score",0)
        cat = t.get("category", "")
        cat_color = {"environmental":"#2f855a","social":"#2563eb","governance":"#d17f1e"}.get(cat,"#627d98")

        with st.expander(f"{t.get('topic','—')}  —  Impact: {imp}/5  ·  Financial: {fin}/5"):
            cc1, cc2, cc3 = st.columns(3)
            with cc1:
                st.markdown(f"**Category:** <span style='color:{cat_color}'>{cat.title()}</span>", unsafe_allow_html=True)
                st.markdown(f"**Trend:** {t.get('trend','—').title()}")
                st.markdown(f"**Confidence:** {t.get('confidence','—').title()}")
            with cc2:
                st.markdown("**Rationale:**")
                st.markdown(t.get("rationale", "—"))
                if t.get("financial_rationale"):
                    st.markdown("**Financial rationale:**")
                    st.markdown(t.get("financial_rationale"))
            with cc3:
                if t.get("evidence"):
                    st.markdown(f"""
                    <div class="evidence-box">
                      <div class="evidence-source">Evidence</div>
                      <div class="evidence-text">{t.get('evidence','')}</div>
                    </div>
                    """, unsafe_allow_html=True)
                fwks = t.get("frameworks", [])
                if fwks:
                    st.markdown("**Frameworks:** " + " · ".join(f"`{f}`" for f in fwks))


# ──────────────────────────────────────────────────────────────────────────────
# Shared: Risk list renderer (used by E/S/G/overview pages)
# ──────────────────────────────────────────────────────────────────────────────
def render_risk_list(risks, category_filter=None):
    filtered = risks
    if category_filter:
        filtered = [r for r in risks if r.get("category") == category_filter]

    if not filtered:
        st.info("No risks found in this category.")
        return

    # Sort by score desc
    filtered = sorted(filtered, key=lambda x: -(x.get("score") or 0))

    for risk in filtered:
        score = risk.get("score", 0)
        sev   = risk.get("severity", "Medium")
        cat   = risk.get("category", "")
        color = score_color(score)

        with st.expander(f"{'🔴' if score >= 70 else '🟡' if score >= 40 else '🟢'} {risk.get('name','—')}  ·  Score: {score}  ·  {sev}"):
            r1, r2, r3 = st.columns([1, 2, 1])
            with r1:
                st.markdown(f"**Score:** <span style='color:{color};font-size:22px;font-weight:800'>{score}</span>/100", unsafe_allow_html=True)
                st.markdown(f"**Severity:** {severity_badge(sev)}", unsafe_allow_html=True)
                st.markdown(f"**Category:** {cat.title()}")
                st.markdown(f"**Framework:** `{risk.get('framework','—')}`")
                if risk.get("confidence"):
                    st.markdown(f"**AI Confidence:** {confidence_badge(risk['confidence'])}", unsafe_allow_html=True)

            with r2:
                st.markdown("**Detail:**")
                st.markdown(risk.get("detail", "—"))
                if risk.get("recommendation"):
                    st.markdown("**Recommendation:**")
                    st.markdown(f"> 💡 {risk.get('recommendation')}")

            with r3:
                evidence = risk.get("evidence", [])
                if isinstance(evidence, list) and evidence:
                    st.markdown("**Evidence:**")
                    for ev in evidence[:3]:
                        src  = ev.get("source","") if isinstance(ev, dict) else str(ev)
                        text = ev.get("text","")   if isinstance(ev, dict) else ""
                        conf = ev.get("confidence","") if isinstance(ev, dict) else ""
                        st.markdown(f"""
                        <div class="evidence-box">
                          <div class="evidence-source">{src}</div>
                          <div class="evidence-text">{text}</div>
                          {'<div class="evidence-conf">Confidence: ' + conf + '</div>' if conf else ''}
                        </div>
                        """, unsafe_allow_html=True)

                kpis = risk.get("kpis", [])
                if kpis:
                    st.markdown("**KPIs:**")
                    for kpi in kpis[:3]:
                        val  = kpi.get("value","—")
                        unit = kpi.get("unit","")
                        st.markdown(f"- **{kpi.get('metric','')}:** {val} {unit}")


# ──────────────────────────────────────────────────────────────────────────────
# Page: ESG Risk Overview
# ──────────────────────────────────────────────────────────────────────────────
def page_esg_risk():
    r      = st.session_state.result or {}
    risks  = r.get("risks", [])
    scores = r.get("esg_scores", {})

    st.markdown('<div class="page-title">🔴 ESG Risk Overview</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">All identified ESG risks scored, categorised, and evidence-backed.</div>', unsafe_allow_html=True)

    # Score summary
    s1, s2, s3 = st.columns(3)
    for col, label, key in [(s1,"Environmental",  "environmental"),
                              (s2,"Social",         "social"),
                              (s3,"Governance",     "governance")]:
        val = scores.get(key, 0)
        with col:
            st.plotly_chart(gauge_chart(val, label), use_container_width=True)

    # Risk bar chart
    st.markdown("#### Risk Scores Overview")
    fig = risk_bar_chart(risks)
    if fig:
        st.plotly_chart(fig, use_container_width=True)

    # Full risk list
    st.markdown("#### All ESG Risks")
    render_risk_list(risks)


# ──────────────────────────────────────────────────────────────────────────────
# Page: Environmental / Social / Governance (shared template)
# ──────────────────────────────────────────────────────────────────────────────
def page_pillar(category: str):
    r     = st.session_state.result or {}
    risks = r.get("risks", [])
    scores = r.get("esg_scores", {})

    icons = {"environmental": "🌿", "social": "👥", "governance": "🏛️"}
    titles = {"environmental": "Environmental Risk", "social": "Social Risk", "governance": "Governance Risk"}
    icon   = icons.get(category, "")
    title  = titles.get(category, category.title())

    st.markdown(f'<div class="page-title">{icon} {title}</div>', unsafe_allow_html=True)

    score = scores.get(category, 0)
    bench = r.get("benchmarking", {}).get(category, {})

    c1, c2 = st.columns([1, 2])
    with c1:
        st.plotly_chart(gauge_chart(score, title), use_container_width=True)
    with c2:
        if bench:
            st.markdown("#### Benchmarking")
            st.markdown(bench.get("narrative", "—"))
            if bench.get("peer_group"):
                st.caption(f"Peer group: {bench['peer_group']}")

    # KPIs for this category
    kpis_all = r.get("kpis", [])
    cat_kpis = [k for k in kpis_all if k.get("category") == category and k.get("available", True)]
    if cat_kpis:
        st.markdown("#### Key Performance Indicators")
        kpi_df = pd.DataFrame(cat_kpis)
        show_cols = [c for c in ["metric","value","unit","year","benchmark","percentile","source"] if c in kpi_df.columns]
        st.dataframe(kpi_df[show_cols], use_container_width=True, hide_index=True)

    # Risks for this category
    st.markdown(f"#### {title} Risks")
    render_risk_list(risks, category_filter=category)


# ──────────────────────────────────────────────────────────────────────────────
# Page: Climate Risk
# ──────────────────────────────────────────────────────────────────────────────
def page_climate():
    r       = st.session_state.result or {}
    climate = r.get("climate", {})
    phys    = climate.get("physical_risks",   [])
    trans   = climate.get("transition_risks", [])

    st.markdown('<div class="page-title">🌡️ Climate Risk</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Physical and transition risk assessment. Frameworks: IFRS S2, TCFD, RCP 4.5 / 8.5 scenarios.</div>', unsafe_allow_html=True)

    tab_phys, tab_trans = st.tabs(["🌊 Physical Risks", "⚡ Transition Risks"])

    def risk_card(risk, kind="physical"):
        score   = risk.get("score", 0)
        color   = score_color(score)
        meta    = risk.get("scenario") if kind == "physical" else risk.get("horizon","")
        conf    = risk.get("confidence","")
        return f"""
        <div class="card-box" style="border-left:4px solid {color}">
          <div style="display:flex;justify-content:space-between;align-items:flex-start">
            <div style="font-size:15px;font-weight:800;color:#102a43">{risk.get("name","—")}</div>
            <div style="font-size:24px;font-weight:800;color:{color}">{score}</div>
          </div>
          <div style="font-size:12px;color:#627d98;margin-top:2px">{meta} {'· Confidence: ' + conf.title() if conf else ''}</div>
          <div style="font-size:13px;color:#334e68;margin-top:8px;line-height:1.6">{risk.get("detail","—")}</div>
        </div>
        """

    with tab_phys:
        if phys:
            c1, c2 = st.columns(2)
            cols = [c1, c2]
            for i, risk in enumerate(phys):
                with cols[i % 2]:
                    st.markdown(risk_card(risk, "physical"), unsafe_allow_html=True)
        else:
            st.info("No physical risks identified.")

        # Physical risk bar
        if phys:
            df_p = pd.DataFrame(phys)[["name","score"]].copy()
            df_p["score"] = pd.to_numeric(df_p["score"], errors="coerce").fillna(0)
            df_p = df_p.sort_values("score")
            fig = go.Figure(go.Bar(
                x=df_p["score"], y=df_p["name"], orientation="h",
                marker_color=[score_color(s) for s in df_p["score"]],
            ))
            fig.update_layout(height=max(200, len(df_p)*40),
                              margin=dict(l=0,r=20,t=0,b=0),
                              paper_bgcolor="rgba(0,0,0,0)",
                              plot_bgcolor="rgba(0,0,0,0)",
                              xaxis_title="Risk Score")
            st.plotly_chart(fig, use_container_width=True)

    with tab_trans:
        if trans:
            c1, c2 = st.columns(2)
            cols = [c1, c2]
            for i, risk in enumerate(trans):
                with cols[i % 2]:
                    st.markdown(risk_card(risk, "transition"), unsafe_allow_html=True)
        else:
            st.info("No transition risks identified.")

        if trans:
            df_t = pd.DataFrame(trans)[["name","score"]].copy()
            df_t["score"] = pd.to_numeric(df_t["score"], errors="coerce").fillna(0)
            df_t = df_t.sort_values("score")
            fig2 = go.Figure(go.Bar(
                x=df_t["score"], y=df_t["name"], orientation="h",
                marker_color=[score_color(s) for s in df_t["score"]],
            ))
            fig2.update_layout(height=max(200, len(df_t)*40),
                               margin=dict(l=0,r=20,t=0,b=0),
                               paper_bgcolor="rgba(0,0,0,0)",
                               plot_bgcolor="rgba(0,0,0,0)",
                               xaxis_title="Risk Score")
            st.plotly_chart(fig2, use_container_width=True)

    # Scenario pathway cards
    st.markdown("#### Scenario Pathways")
    sc1, sc2, sc3 = st.columns(3)
    scenarios = [
        (sc1, "Conservative", "RCP 4.5 aligned · 1.5–2°C", "#2f855a", "Assumes accelerated decarbonisation, carbon pricing, renewable energy scale-up, and proactive transition policy."),
        (sc2, "Moderate",     "RCP 6.0 aligned · 2–3°C",   "#d17f1e", "Current policy trajectory with moderate transition pace. Significant physical risks materialise by 2050."),
        (sc3, "Leading",      "RCP 8.5 aligned · 3–4°C+",  "#e24141", "High-emission scenario. Severe physical risks, stranded asset risk, and regulatory disruption."),
    ]
    for col, name, sub, color, desc in scenarios:
        with col:
            st.markdown(f"""
            <div class="card-box" style="border-top:4px solid {color}">
              <div style="font-size:15px;font-weight:800;color:#102a43">{name}</div>
              <div style="font-size:12px;color:#627d98;margin-top:2px">{sub}</div>
              <div style="font-size:13px;color:#334e68;margin-top:8px;line-height:1.6">{desc}</div>
            </div>
            """, unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# Page: ESG Engagement
# ──────────────────────────────────────────────────────────────────────────────
def page_engagement():
    r      = st.session_state.result or {}
    co     = r.get("company", {})
    risks  = r.get("risks", [])
    topics = r.get("material_topics", [])

    st.markdown('<div class="page-title">💬 ESG Engagement</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Transform assessment findings into engagement letters, questions, and action plans.</div>', unsafe_allow_html=True)

    tab_qns, tab_letter, tab_plan = st.tabs(["❓ Engagement Questions", "📝 Engagement Letter", "📋 Action Plan"])

    with tab_qns:
        st.markdown("#### Priority Engagement Questions")
        st.caption("Generated from top risks and material topics. Tailor to your investor / lender engagement strategy.")

        top_risks  = sorted(risks, key=lambda x: -(x.get("score") or 0))[:5]
        top_topics = sorted(topics, key=lambda x: -(x.get("impact_score",0)+x.get("financial_score",0)))[:3]

        questions = []
        for risk in top_risks:
            questions.append({
                "theme": risk.get("name",""),
                "framework": risk.get("framework",""),
                "question": f"What specific actions has {co.get('name','the company')} taken to manage {risk.get('name','')} risk, "
                            f"and what quantitative targets or KPIs are in place to track progress?",
                "follow_up": f"What is your current exposure quantification under {risk.get('framework','ESRS')} and how does this compare to your 2030 targets?",
            })
        for topic in top_topics:
            questions.append({
                "theme": topic.get("topic",""),
                "framework": ", ".join(topic.get("frameworks",[]) or []),
                "question": f"Can you provide evidence of how {topic.get('topic','')} is managed as a material topic "
                            f"under your double materiality assessment?",
                "follow_up": f"What are your most recent performance metrics for {topic.get('topic','')} and how do these benchmark against sector peers?",
            })

        for i, q in enumerate(questions, 1):
            with st.expander(f"Q{i}: {q['theme']}  ·  {q['framework']}"):
                st.markdown(f"**Primary question:**")
                st.markdown(f"> {q['question']}")
                st.markdown(f"**Follow-up:**")
                st.markdown(f"> {q['follow_up']}")

    with tab_letter:
        st.markdown("#### Engagement Letter")
        company = co.get("name","[Company Name]")
        sector  = co.get("sector", "the sector")
        scores  = r.get("esg_scores", {})
        overall = scores.get("overall","—")
        country = co.get("country","—")

        letter_text = f"""**[Your Organisation Name]**
[Address]
[Date]

**ESG Engagement Notice — {company}**

Dear Management,

We are writing as [investors/lenders/creditors] in {company} to initiate a structured ESG engagement dialogue in connection with our ongoing due diligence review under [SFDR Article 8 / TCFD / PRI Responsible Investment Policy].

Our preliminary ESG risk assessment of {company} has identified an overall ESG Risk Score of **{overall}/100** across Environmental, Social, and Governance pillars. The assessment was conducted against ESRS, ISSB/IFRS S1-S2, GRI, and SASB sector standards applicable to {sector} operations in {country}.

**Priority Engagement Themes:**
{chr(10).join(f"- {r.get('name','')}: {r.get('severity','Medium')} risk — {r.get('detail','')[:80]}..." for r in sorted(risks, key=lambda x: -(x.get("score") or 0))[:3])}

We respectfully request the following disclosures within [30/60] days:

1. Quantitative GHG emissions data (Scope 1, 2, and 3) with year-on-year trend
2. Written description of board oversight and management processes for ESG risks
3. Confirmation of alignment with or plans to align to ESRS / IFRS S1-S2
4. Specific targets and timelines for the material topics identified above

We are committed to constructive dialogue and recognise the positive steps {company} has already taken. We would welcome a call or meeting at your earliest convenience.

Yours sincerely,
[Portfolio Manager / ESG Lead]
[Organisation]
"""
        st.text_area("Engagement Letter Draft", value=letter_text, height=500, key="engagement_letter")
        if st.button("📋 Copy to Clipboard"):
            st.code(letter_text, language=None)

    with tab_plan:
        st.markdown("#### Recommended Action Plan")
        st.caption("Priority actions ranked by risk severity. Use for stewardship and engagement tracking.")

        actions = []
        for risk in sorted(risks, key=lambda x: -(x.get("score") or 0)):
            if risk.get("recommendation"):
                actions.append({
                    "Priority": risk.get("severity","Medium"),
                    "Risk Topic": risk.get("name",""),
                    "Category": risk.get("category","").title(),
                    "Action": risk.get("recommendation",""),
                    "Framework": risk.get("framework",""),
                    "Score": risk.get("score",0),
                })
        if actions:
            df = pd.DataFrame(actions)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No specific recommendations available from this assessment.")


# ──────────────────────────────────────────────────────────────────────────────
# Page: Report Generator
# ──────────────────────────────────────────────────────────────────────────────
def page_reports():
    r  = st.session_state.result or {}
    co = r.get("company", {})
    aid = st.session_state.analysis_id

    st.markdown('<div class="page-title">📄 Report Generator</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Generate professional ESG reports in Word, PDF, Excel, and PowerPoint formats.</div>', unsafe_allow_html=True)

    c1, c2 = st.columns([1, 2])

    with c1:
        st.markdown("#### Report Configuration")
        report_type = st.radio("Report Type", [
            "Full ESG Due Diligence Report",
            "Executive Summary (2 pages)",
            "Climate Risk Report (TCFD)",
            "ESG Engagement Letter",
            "Risk Register Export",
        ], key="report_type")

        st.markdown("#### Sections to Include")
        sections = {
            "Executive Summary & Analyst Narrative": True,
            "Company Profile & Sector Context": True,
            "Materiality Assessment": True,
            "Environmental Pillar Analysis": True,
            "Social Pillar Analysis": True,
            "Governance Pillar Analysis": True,
            "Climate Risk Assessment (TCFD)": True,
            "Full ESG Risk Register": True,
            "Benchmarking Analysis": True,
            "Recommended Actions": True,
            "Engagement Questions": False,
            "Scenario Analysis Financials": False,
            "Appendix: Data Sources": False,
            "Appendix: Methodology Notes": False,
        }
        selected_sections = {}
        for sec, default in sections.items():
            selected_sections[sec] = st.checkbox(sec, value=default, key=f"sec_{sec}")

        st.markdown("#### Output Format")
        fmt = st.radio("Format", ["PDF", "Word (.docx)", "Excel (.xlsx)", "PowerPoint (.pptx)", "JSON"],
                       key="report_fmt", horizontal=True)

    with c2:
        st.markdown("#### Report Preview")
        company = co.get("name","[Company]")
        scores  = r.get("esg_scores",{})
        st.markdown(f"""
        <div class="card-box">
          <div style="font-size:18px;font-weight:800;color:#102a43">ESG Due Diligence Report</div>
          <div style="font-size:13px;color:#627d98;margin-top:4px">{company} · {co.get("sector","—")} · {co.get("country","—")}</div>
          <hr style="border-color:rgba(145,158,171,0.14)">
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:12px">
            <div style="text-align:center"><div style="font-size:11px;color:#627d98;text-transform:uppercase">Overall</div><div style="font-size:24px;font-weight:800;color:{score_color(scores.get('overall',0))}">{scores.get('overall','—')}</div></div>
            <div style="text-align:center"><div style="font-size:11px;color:#627d98;text-transform:uppercase">Environmental</div><div style="font-size:24px;font-weight:800;color:{score_color(scores.get('environmental',0))}">{scores.get('environmental','—')}</div></div>
            <div style="text-align:center"><div style="font-size:11px;color:#627d98;text-transform:uppercase">Social</div><div style="font-size:24px;font-weight:800;color:{score_color(scores.get('social',0))}">{scores.get('social','—')}</div></div>
          </div>
          <div style="margin-top:16px;font-size:13px;color:#334e68">
            <strong>Sections:</strong> {", ".join(k for k,v in selected_sections.items() if v)[:120]}…
          </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("#### Download Report")
        if not aid:
            st.warning("No active analysis. Run an assessment first.")
            return

        if not backend_ok():
            st.error("Backend is offline. Start the FastAPI server first.")
            return

        fmt_endpoints = {
            "Word (.docx)":      ("/api/documents/report", "report.docx",     "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            "PDF":               ("/api/documents/report", "report.pdf",      "application/pdf"),
            "PowerPoint (.pptx)":("/api/documents/deck",   "report.pptx",     "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
            "Excel (.xlsx)":     ("/api/documents/risk-register", "risks.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "JSON":              (None, "report.json", "application/json"),
        }

        if st.button(f"🔄 Generate {fmt} Report", type="primary", use_container_width=True):
            endpoint_info = fmt_endpoints.get(fmt)
            if fmt == "JSON":
                import json
                json_bytes = json.dumps(r, indent=2, ensure_ascii=False).encode("utf-8")
                st.download_button("⬇ Download JSON", data=json_bytes,
                                   file_name=f"ESGIntel_{company.replace(' ','_')}.json",
                                   mime="application/json")
            elif endpoint_info:
                endpoint, filename, mime = endpoint_info
                with st.spinner(f"Generating {fmt} report…"):
                    try:
                        resp = requests.post(
                            f"{API_BASE}{endpoint}",
                            json={"analysis_id": aid, "report_type": report_type,
                                  "sections": [k for k,v in selected_sections.items() if v]},
                            timeout=60,
                        )
                        if resp.status_code == 200:
                            cname = company.replace(" ","_").replace("/","_")
                            st.download_button(
                                f"⬇ Download {fmt}",
                                data=resp.content,
                                file_name=f"ESGIntel_{cname}_{filename}",
                                mime=mime,
                            )
                        else:
                            st.error(f"Report generation failed (HTTP {resp.status_code}): {resp.text[:200]}")
                    except requests.exceptions.ConnectionError:
                        st.error("Could not connect to backend. Is the FastAPI server running?")
                    except Exception as e:
                        st.error(f"Error: {e}")

        # Quick JSON download always available
        import json as json_mod
        if r:
            json_bytes = json_mod.dumps(r, indent=2, ensure_ascii=False).encode("utf-8")
            cname = company.replace(" ","_").replace("/","_")
            st.download_button(
                "⬇ Download Raw JSON (always available)",
                data=json_bytes,
                file_name=f"ESGIntel_{cname}_raw.json",
                mime="application/json",
                key="json_dl_2",
            )


# ──────────────────────────────────────────────────────────────────────────────
# Router
# ──────────────────────────────────────────────────────────────────────────────
def main():
    render_sidebar()

    page = st.session_state.page

    if page == "input":
        page_input()
    elif page == "running":
        page_running()
    elif page == "dashboard":
        page_dashboard()
    elif page == "profile":
        page_profile()
    elif page == "materiality":
        page_materiality()
    elif page == "esg_risk":
        page_esg_risk()
    elif page == "environmental":
        page_pillar("environmental")
    elif page == "social":
        page_pillar("social")
    elif page == "governance":
        page_pillar("governance")
    elif page == "climate":
        page_climate()
    elif page == "engagement":
        page_engagement()
    elif page == "reports":
        page_reports()
    else:
        st.error(f"Unknown page: {page}")
        st.session_state.page = "input"
        st.rerun()


if __name__ == "__main__":
    main()
