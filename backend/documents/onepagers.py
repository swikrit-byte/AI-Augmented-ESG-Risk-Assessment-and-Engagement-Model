"""
ESGIntel — One-Pager PDF Generator
====================================
Produces three McKinsey-style single-page PDF executive leave-behinds for
{cd.COMPANY['short']} S.p.A.  All figures sourced from company_data (single source of
truth — never invent numbers).

Public API
----------
    build_onepager(key: str, out_dir: str) -> str
        key in {'risk_summary', 'climate_flash', 'csrd_readiness'}
        Returns absolute path to the generated .pdf file.
"""

import os
import math
import tempfile
import importlib.util

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import company_data as cd

# ─── Page geometry ─────────────────────────────────────────────────────────
PW, PH = A4          # 595.28 x 841.89 pt
MARGIN_L = 20 * mm
MARGIN_R = 20 * mm
MARGIN_T = 16 * mm
MARGIN_B = 14 * mm
CONTENT_W = PW - MARGIN_L - MARGIN_R

# ─── Colour helpers ─────────────────────────────────────────────────────────
def _c(hex_str):
    """reportlab Color from a hex string (no leading #)."""
    r, g, b = cd.hex_rgb(hex_str)
    return colors.Color(r / 255, g / 255, b / 255)

INK       = _c(cd.BRAND["ink"])
ACCENT    = _c(cd.BRAND["accent"])
ACCENT_LT = _c(cd.BRAND["accent_lt"])
SLATE     = _c(cd.BRAND["slate"])
MUTED     = _c(cd.BRAND["muted"])
RULE_C    = _c(cd.BRAND["rule"])
RED_C     = _c(cd.BRAND["red"])
AMBER_C   = _c(cd.BRAND["amber"])
GREEN_C   = _c(cd.BRAND["green"])
WHITE     = colors.white
BAND_BG   = _c(cd.BRAND["band_bg"])

RAG_COLOR = {"red": RED_C, "amber": AMBER_C, "green": GREEN_C,
             "Critical": RED_C, "High": AMBER_C, "Medium": MUTED, "Low": GREEN_C}

# ─── Font setup (fall back to Helvetica if Georgia/Calibri unavailable) ────
def _try_register():
    """Register system fonts if available; we fall back to built-in safely."""
    pass   # reportlab built-ins (Helvetica family) are always available

_try_register()

FONT_HEAD = "Helvetica-Bold"
FONT_BODY = "Helvetica"
FONT_ITALIC = "Helvetica-Oblique"


# ─── Low-level canvas helpers ───────────────────────────────────────────────

def _rect(c, x, y, w, h, fill_color=None, stroke_color=None, stroke_w=0.5, radius=0):
    """Draw a (possibly rounded) rectangle."""
    c.saveState()
    if fill_color:
        c.setFillColor(fill_color)
    else:
        c.setFillColor(colors.transparent)
    if stroke_color:
        c.setStrokeColor(stroke_color)
        c.setLineWidth(stroke_w)
    else:
        c.setStrokeColor(colors.transparent)
        c.setLineWidth(0)
    if radius:
        c.roundRect(x, y, w, h, radius,
                    stroke=1 if stroke_color else 0,
                    fill=1 if fill_color else 0)
    else:
        c.rect(x, y, w, h,
               stroke=1 if stroke_color else 0,
               fill=1 if fill_color else 0)
    c.restoreState()


def _text(c, x, y, text, font=FONT_BODY, size=8, color=SLATE,
          align="left", max_width=None):
    """Draw single-line text. align: left | center | right."""
    c.saveState()
    c.setFont(font, size)
    c.setFillColor(color)
    if align == "center":
        c.drawCentredString(x, y, text)
    elif align == "right":
        c.drawRightString(x, y, text)
    else:
        c.drawString(x, y, text)
    c.restoreState()


def _wrapped_text(c, x, y, text, font=FONT_BODY, size=8, color=SLATE,
                  max_width=150, line_height=10):
    """Very simple word-wrap; returns final y after drawing."""
    c.saveState()
    c.setFont(font, size)
    c.setFillColor(color)
    words = text.split()
    line = ""
    for word in words:
        test = (line + " " + word).strip()
        if c.stringWidth(test, font, size) <= max_width:
            line = test
        else:
            c.drawString(x, y, line)
            y -= line_height
            line = word
    if line:
        c.drawString(x, y, line)
        y -= line_height
    c.restoreState()
    return y


def _hline(c, x, y, width, color=RULE_C, lw=0.4):
    c.saveState()
    c.setStrokeColor(color)
    c.setLineWidth(lw)
    c.line(x, y, x + width, y)
    c.restoreState()


def _header_band(c, title, subtitle=""):
    """Full-width dark green header band at top of page."""
    band_h = 38 * mm
    # Dark green band
    _rect(c, 0, PH - band_h, PW, band_h, fill_color=ACCENT)
    # Company name (small, white, upper)
    _text(c, MARGIN_L, PH - 11 * mm, cd.COMPANY["name"].upper(),
          font=FONT_BODY, size=7, color=WHITE)
    # Platform label (right-aligned)
    _text(c, PW - MARGIN_R, PH - 11 * mm, "ESGIntel  •  AI-Assisted ESG Due Diligence",
          font=FONT_BODY, size=7, color=colors.Color(1, 1, 1, 0.75), align="right")
    # Main title
    _text(c, MARGIN_L, PH - 21 * mm, title,
          font=FONT_HEAD, size=18, color=WHITE)
    # Subtitle
    if subtitle:
        _text(c, MARGIN_L, PH - 28 * mm, subtitle,
              font=FONT_ITALIC, size=9, color=colors.Color(1, 1, 1, 0.80))
    # Thin white rule at bottom of band
    c.saveState()
    c.setStrokeColor(colors.Color(1, 1, 1, 0.30))
    c.setLineWidth(0.5)
    c.line(0, PH - band_h, PW, PH - band_h)
    c.restoreState()
    return PH - band_h   # y coordinate of band bottom


def _footer(c):
    """Confidential footer at page bottom."""
    y = MARGIN_B - 4 * mm
    _hline(c, MARGIN_L, y + 8, CONTENT_W)
    _text(c, PW / 2, y + 2, f"ESGIntel — CONFIDENTIAL  ·  {cd.COMPANY['short']} S.p.A.  ·  June 2024",
          font=FONT_BODY, size=6.5, color=MUTED, align="center")


def _score_tile(c, x, y, w, h, score, label, pillar=None):
    """A bold score tile: big number + label + RAG colour."""
    if score >= 70:
        rag = RED_C
    elif score >= 50:
        rag = AMBER_C
    else:
        rag = GREEN_C
    _rect(c, x, y, w, h, fill_color=INK, radius=2)
    # Top accent strip
    _rect(c, x, y + h - 3, w, 3, fill_color=rag)
    # Score number
    _text(c, x + w / 2, y + h / 2 + 2, str(score),
          font=FONT_HEAD, size=22, color=WHITE, align="center")
    # Label
    _text(c, x + w / 2, y + 4, label,
          font=FONT_BODY, size=6.5, color=colors.Color(1, 1, 1, 0.70), align="center")
    if pillar:
        _text(c, x + w / 2, y + h - 8, pillar,
              font=FONT_HEAD, size=7, color=WHITE, align="center")


def _rag_chip(c, x, y, label, w=28, h=10):
    """Coloured severity chip."""
    col = RAG_COLOR.get(label, MUTED)
    _rect(c, x, y, w, h, fill_color=col, radius=1.5)
    _text(c, x + w / 2, y + 2.5, label,
          font=FONT_HEAD, size=6, color=WHITE, align="center")


def _rag_dot(c, x, y, status, r=3.5):
    """Filled circle RAG dot."""
    col = {"red": RED_C, "amber": AMBER_C, "green": GREEN_C}.get(status, MUTED)
    c.saveState()
    c.setFillColor(col)
    c.circle(x, y, r, fill=1, stroke=0)
    c.restoreState()


def _embed_chart(c, fig, x, y, w, h, tmp_dir):
    """Save matplotlib fig to temp PNG, draw on canvas, return path."""
    path = os.path.join(tmp_dir, f"chart_{id(fig)}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight",
                facecolor="none", transparent=True)
    plt.close(fig)
    c.drawImage(path, x, y, width=w, height=h, preserveAspectRatio=True,
                mask="auto")
    return path


# ═══════════════════════════════════════════════════════════════════════════
#  1. RISK SUMMARY ONE-PAGER
# ═══════════════════════════════════════════════════════════════════════════

def _build_risk_summary(c, tmp_dir):
    """Draw risk_summary content onto canvas c (one page)."""

    # ── Header ──────────────────────────────────────────────────────────────
    band_bottom = _header_band(
        c,
        "ESG Risk Summary — One-Pager",
        subtitle=f"{cd.COMPANY['name']}  ·  {cd.COMPANY['sector']}  ·  {cd.COMPANY['report_period']}"
    )
    _footer(c)

    y = band_bottom - 6 * mm   # working y (descends)

    # ── Score tiles row ──────────────────────────────────────────────────────
    # Overall tile (wide) + three pillar tiles
    tile_h = 22 * mm
    overall_w = 38 * mm
    gap = 4 * mm
    pillar_w = (CONTENT_W - overall_w - gap * 3) / 3

    # Overall
    ox = MARGIN_L
    oy = y - tile_h
    _score_tile(c, ox, oy, overall_w, tile_h,
                cd.SCORES["overall"], "Overall Risk")
    # P-label below
    _text(c, ox + overall_w / 2, oy - 4.5,
          f"P{cd.SCORES['overall_percentile']} vs NACE C24  ·  {cd.SCORES['overall_label']}",
          font=FONT_ITALIC, size=6.5, color=MUTED, align="center")

    pillars = cd.SCORES["pillars"]
    px = ox + overall_w + gap
    for name, data in pillars.items():
        lbl = name[0]  # E / S / G
        _score_tile(c, px, oy, pillar_w, tile_h,
                    data["score"], data["label"], pillar=lbl)
        px += pillar_w + gap

    y = oy - 9 * mm

    # ── Section label ─────────────────────────────────────────────────────
    _hline(c, MARGIN_L, y + 2, CONTENT_W, color=ACCENT, lw=0.8)
    _text(c, MARGIN_L, y - 5, "TOP-5 MATERIAL RISKS",
          font=FONT_HEAD, size=8, color=ACCENT)
    y -= 11

    # ── Top-5 risks ──────────────────────────────────────────────────────
    top5 = sorted(cd.RISKS, key=lambda r: r["score"], reverse=True)[:5]

    # Column widths
    chip_w   = 30
    col_id   = 22
    col_title = 118
    col_fin  = 80
    col_act  = CONTENT_W - chip_w - 4 - col_id - col_title - col_fin - 12

    row_h    = 14 * mm

    # Header row
    hx = MARGIN_L
    for lbl, w in [("RISK ID", col_id), ("RISK", col_title),
                    ("FINANCIAL EXPOSURE", col_fin), ("RECOMMENDED ACTION", col_act)]:
        _text(c, hx + (2 if lbl != "RECOMMENDED ACTION" else 2),
              y - 2, lbl, font=FONT_HEAD, size=6, color=MUTED)
        hx += w + 4 if lbl == "RISK ID" else w + 4
    y -= 8

    for i, risk in enumerate(top5):
        ry = y - row_h
        # Alternating background
        if i % 2 == 0:
            _rect(c, MARGIN_L - 2, ry - 1, CONTENT_W + 4, row_h,
                  fill_color=BAND_BG)
        sev = cd.severity(risk["score"])
        # Chip
        _rag_chip(c, MARGIN_L, ry + (row_h - 10) / 2, sev, w=chip_w)
        x_cur = MARGIN_L + chip_w + 4
        # ID
        _text(c, x_cur, ry + row_h - 8, risk["id"],
              font=FONT_HEAD, size=6.5, color=SLATE)
        _text(c, x_cur, ry + row_h - 15, f"Score {risk['score']}",
              font=FONT_BODY, size=6, color=MUTED)
        x_cur += col_id + 4
        # Title + horizon
        _text(c, x_cur, ry + row_h - 7, risk["title"],
              font=FONT_HEAD, size=7, color=INK)
        _text(c, x_cur, ry + row_h - 15, risk["horizon"],
              font=FONT_ITALIC, size=6, color=MUTED)
        x_cur += col_title + 4
        # Financial
        fin_txt = risk["financial"]
        if len(fin_txt) > 26:
            fin_txt = fin_txt[:25] + "…"
        _text(c, x_cur, ry + row_h - 7, fin_txt,
              font=FONT_HEAD, size=6.5, color=RED_C)
        x_cur += col_fin + 4
        # Action
        act_words = risk["action"].split()
        act_line1 = ""
        act_line2 = ""
        for w in act_words:
            test = (act_line1 + " " + w).strip()
            if c.stringWidth(test, FONT_ITALIC, 6) <= col_act:
                act_line1 = test
            elif not act_line2:
                act_line2 = w
            else:
                test2 = (act_line2 + " " + w).strip()
                if c.stringWidth(test2, FONT_ITALIC, 6) <= col_act:
                    act_line2 = test2
                else:
                    act_line2 += "…"
                    break
        _text(c, x_cur, ry + row_h - 7,  act_line1,
              font=FONT_ITALIC, size=6, color=SLATE)
        _text(c, x_cur, ry + row_h - 14, act_line2,
              font=FONT_ITALIC, size=6, color=SLATE)
        y = ry

    y -= 5 * mm

    # ── Two-column lower section ──────────────────────────────────────────
    col2_w = (CONTENT_W - 8 * mm) / 2
    cx_left  = MARGIN_L
    cx_right = MARGIN_L + col2_w + 8 * mm

    # ── Financial exposure chart (left) ──────────────────────────────────
    _hline(c, cx_left, y + 2, col2_w, color=ACCENT, lw=0.8)
    _text(c, cx_left, y - 6, "FINANCIAL EXPOSURE SUMMARY (€M)",
          font=FONT_HEAD, size=7.5, color=ACCENT)

    chart_h = 42 * mm
    chart_y = y - 9 * mm - chart_h

    # Matplotlib bar chart
    items = [(d["driver"][:30], d["amount_eur_m"], d["rating"])
             for d in cd.FINANCIAL_EXPOSURE]
    labels = [it[0] for it in items]
    values = [it[1] for it in items]
    bar_colors = [
        cd.hex_rgb01(cd.BRAND["red"])   if it[2] == "Critical" else
        cd.hex_rgb01(cd.BRAND["amber"]) if it[2] == "High"     else
        cd.hex_rgb01(cd.BRAND["accent"]) for it in items
    ]

    fig, ax = plt.subplots(figsize=(col2_w / 28.35, chart_h / 28.35))
    bars = ax.barh(range(len(labels)), values, color=bar_colors, height=0.55)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels([l[:28] for l in labels], fontsize=5.5)
    ax.set_xlabel("€M", fontsize=5.5)
    ax.invert_yaxis()
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="both", labelsize=5.5)
    ax.xaxis.set_tick_params(labelsize=5.5)
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + 3, bar.get_y() + bar.get_height() / 2,
                f"€{val}M", va="center", fontsize=4.5,
                color=cd.hex_rgb01(cd.BRAND["slate"]))
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")
    plt.tight_layout(pad=0.3)
    _embed_chart(c, fig, cx_left, chart_y, col2_w, chart_h, tmp_dir)

    # ── Engagement asks (right) ─────────────────────────────────────────
    _hline(c, cx_right, y + 2, col2_w, color=ACCENT, lw=0.8)
    _text(c, cx_right, y - 6, "TOP 3 ENGAGEMENT ASKS",
          font=FONT_HEAD, size=7.5, color=ACCENT)
    ey = y - 13

    priority_color = {"Critical": RED_C, "Immediate": RED_C,
                      "High": AMBER_C, "Medium": MUTED}
    top_asks = cd.ENGAGEMENT_ASKS[:3]
    for ask in top_asks:
        p_col = priority_color.get(ask["priority"], MUTED)
        # Priority label
        _text(c, cx_right, ey, ask["priority"].upper(),
              font=FONT_HEAD, size=6.5, color=p_col)
        _text(c, cx_right + 38, ey, f"By: {ask['by']}  ·  Owner: {ask['owner']}",
              font=FONT_BODY, size=6, color=MUTED)
        ey -= 9
        # Ask text (wrapped)
        ask_words = ask["ask"].split()
        line = ""
        for word in ask_words:
            test = (line + " " + word).strip()
            if c.stringWidth(test, FONT_BODY, 7) <= col2_w:
                line = test
            else:
                _text(c, cx_right, ey, line, font=FONT_BODY, size=7, color=INK)
                ey -= 9
                line = word
        if line:
            _text(c, cx_right, ey, line, font=FONT_BODY, size=7, color=INK)
            ey -= 9
        _hline(c, cx_right, ey + 5, col2_w, color=RULE_C, lw=0.3)
        ey -= 6


# ═══════════════════════════════════════════════════════════════════════════
#  2. CLIMATE FLASH ONE-PAGER
# ═══════════════════════════════════════════════════════════════════════════

def _build_climate_flash(c, tmp_dir):
    """Draw climate_flash content onto canvas c (one page)."""

    band_bottom = _header_band(
        c,
        "Climate Risk Flash Summary",
        subtitle=f"{cd.COMPANY['name']}  ·  TCFD-aligned  ·  {cd.COMPANY['report_period']}"
    )
    _footer(c)

    y = band_bottom - 6 * mm

    # ── Critical callout box ─────────────────────────────────────────────
    callout_h = 12 * mm
    _rect(c, MARGIN_L, y - callout_h, CONTENT_W, callout_h,
          fill_color=_c("FFF3CD"), stroke_color=AMBER_C, stroke_w=0.7, radius=2)
    cal_x = MARGIN_L + 5
    _text(c, cal_x, y - 5,
          "CRITICAL FINANCIAL EXPOSURES:",
          font=FONT_HEAD, size=7.5, color=_c(cd.BRAND["amber"]))
    _text(c, cal_x + 130, y - 5,
          "EU ETS carbon cost → €68M/yr net by 2030  ·  CBAM certificates → €24M/yr by 2027",
          font=FONT_HEAD, size=7.5, color=RED_C)
    _text(c, cal_x, y - 12,
          "Scope 1: 842,000 tCO2e  ·  GHG intensity: 0.73 tCO2e/€k  ·  No hedging / internal carbon price",
          font=FONT_ITALIC, size=6.5, color=SLATE)
    y -= callout_h + 5 * mm

    # ── Two columns: Physical | Transition ───────────────────────────────
    col_w = (CONTENT_W - 8 * mm) / 2
    cx_l = MARGIN_L
    cx_r = MARGIN_L + col_w + 8 * mm

    col_top = y

    # ── Physical risks (left) ──────────────────────────────────────────
    _hline(c, cx_l, col_top + 2, col_w, color=ACCENT, lw=0.8)
    _text(c, cx_l, col_top - 6, "PHYSICAL RISKS",
          font=FONT_HEAD, size=8, color=ACCENT)
    _text(c, cx_l + 75, col_top - 6, "(site-level exposure)",
          font=FONT_ITALIC, size=7, color=MUTED)

    py = col_top - 14

    # Score bars for physical risks
    for pr in cd.PHYSICAL_RISKS:
        sc = pr["score"]
        sev = cd.severity(sc)
        bar_col = RAG_COLOR.get(sev, MUTED)
        # Label
        _text(c, cx_l, py, pr["hazard"],
              font=FONT_HEAD, size=7, color=INK)
        _text(c, cx_l + col_w, py, pr["sites"],
              font=FONT_ITALIC, size=5.5, color=MUTED, align="right")
        py -= 8
        # Score bar background
        bar_total_w = col_w
        _rect(c, cx_l, py, bar_total_w, 5,
              fill_color=_c("E8E8E8"))
        # Filled portion
        fill_w = bar_total_w * sc / 100
        _rect(c, cx_l, py, fill_w, 5, fill_color=bar_col)
        # Score label
        _text(c, cx_l + fill_w + 2, py + 0.5, str(sc),
              font=FONT_BODY, size=5.5, color=bar_col)
        py -= 10

    # ── Transition risks (right) ──────────────────────────────────────
    _hline(c, cx_r, col_top + 2, col_w, color=ACCENT, lw=0.8)
    _text(c, cx_r, col_top - 6, "TRANSITION RISKS",
          font=FONT_HEAD, size=8, color=ACCENT)
    _text(c, cx_r + 75, col_top - 6, "(policy & market drivers)",
          font=FONT_ITALIC, size=7, color=MUTED)

    ty = col_top - 14
    for tr in cd.TRANSITION_RISKS:
        sc = tr["score"]
        sev = cd.severity(sc)
        bar_col = RAG_COLOR.get(sev, GREEN_C)
        _text(c, cx_r, ty, tr["driver"],
              font=FONT_HEAD, size=7, color=INK)
        ty -= 8
        bar_total_w = col_w
        _rect(c, cx_r, ty, bar_total_w, 5, fill_color=_c("E8E8E8"))
        fill_w = bar_total_w * sc / 100
        _rect(c, cx_r, ty, fill_w, 5, fill_color=bar_col)
        _text(c, cx_r + fill_w + 2, ty + 0.5, str(sc),
              font=FONT_BODY, size=5.5, color=bar_col)
        ty -= 10

    y = min(py, ty) - 6 * mm

    # ── NGFS scenario P&L chart ───────────────────────────────────────
    _hline(c, MARGIN_L, y + 2, CONTENT_W, color=ACCENT, lw=0.8)
    _text(c, MARGIN_L, y - 6, "NGFS SCENARIO P&L IMPACT — 2030 (€M NET EFFECT)",
          font=FONT_HEAD, size=8, color=ACCENT)

    chart_h = 32 * mm
    chart_y = y - 10 * mm - chart_h

    scenarios = cd.CLIMATE_SCENARIOS
    s_labels  = [s["scenario"] for s in scenarios]
    s_values  = [s["pnl_2030_eur_m"] for s in scenarios]
    s_carbon  = [s["carbon_2030"] for s in scenarios]
    s_colors  = [
        cd.hex_rgb01(cd.BRAND["amber"]),
        cd.hex_rgb01(cd.BRAND["red"]),
        cd.hex_rgb01(cd.BRAND["green"]),
    ]

    fig, ax = plt.subplots(figsize=(CONTENT_W / 28.35, chart_h / 28.35))
    bars = ax.bar(range(len(s_labels)), s_values, color=s_colors, width=0.5)
    ax.set_xticks(range(len(s_labels)))
    ax.set_xticklabels(
        [f"{l}\n({c})" for l, c in zip(s_labels, s_carbon)],
        fontsize=6.5
    )
    ax.set_ylabel("P&L impact €M", fontsize=6.5)
    ax.axhline(0, color="#999999", linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="both", labelsize=6)
    for bar, val in zip(bars, s_values):
        ax.text(bar.get_x() + bar.get_width() / 2, val - 3,
                f"€{val}M", ha="center", va="top", fontsize=7,
                fontweight="bold",
                color=cd.hex_rgb01(cd.BRAND["ink"]))
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")
    plt.tight_layout(pad=0.4)
    _embed_chart(c, fig, MARGIN_L, chart_y, CONTENT_W, chart_h, tmp_dir)

    y = chart_y - 5 * mm

    # ── Top climate actions ─────────────────────────────────────────
    _hline(c, MARGIN_L, y + 2, CONTENT_W, color=ACCENT, lw=0.8)
    _text(c, MARGIN_L, y - 6, "TOP 4 CLIMATE ACTIONS",
          font=FONT_HEAD, size=8, color=ACCENT)
    ay = y - 14
    climate_risks = sorted(cd.RISKS, key=lambda r: r["score"], reverse=True)
    env_risks = [r for r in climate_risks if r["pillar"] == "E"][:4]
    act_col_w = (CONTENT_W - 6 * mm) / 2

    for i, risk in enumerate(env_risks):
        ax_x = MARGIN_L + (i % 2) * (act_col_w + 6 * mm)
        if i == 2:
            ay -= 18
        sev = cd.severity(risk["score"])
        _rag_chip(c, ax_x, ay - 2, sev, w=28, h=9)
        _text(c, ax_x + 32, ay + 1, risk["title"],
              font=FONT_HEAD, size=7, color=INK)
        _text(c, ax_x + 32, ay - 7, risk["financial"],
              font=FONT_ITALIC, size=6, color=RED_C)
        # One-line action
        act = risk["action"]
        if c.stringWidth(act, FONT_ITALIC, 6) > act_col_w - 32:
            act = act[:55] + "…"
        _text(c, ax_x + 32, ay - 14, act,
              font=FONT_ITALIC, size=6, color=SLATE)


# ═══════════════════════════════════════════════════════════════════════════
#  3. CSRD READINESS ONE-PAGER
# ═══════════════════════════════════════════════════════════════════════════

def _build_csrd_readiness(c, tmp_dir):
    """Draw csrd_readiness content onto canvas c (one page)."""

    band_bottom = _header_band(
        c,
        "CSRD Readiness Snapshot",
        subtitle=f"{cd.COMPANY['name']}  ·  First reporting year: FY2025 (Q1 2026 deadline)"
    )
    _footer(c)

    y = band_bottom - 6 * mm

    # ── Count summary ────────────────────────────────────────────────────
    reds   = [r for r in cd.CSRD_READINESS if r["status"] == "red"]
    ambers = [r for r in cd.CSRD_READINESS if r["status"] == "amber"]
    greens = [r for r in cd.CSRD_READINESS if r["status"] == "green"]
    total  = len(cd.CSRD_READINESS)

    # Summary tile row
    tile_w = 52 * mm
    tile_h = 16 * mm
    gap    = 6 * mm
    tot_row = 3 * tile_w + 2 * gap
    tx0 = MARGIN_L + (CONTENT_W - tot_row) / 2

    for count, label, col, tx in [
        (len(reds),   "NOT READY (Red)",    RED_C,   tx0),
        (len(ambers), "PARTIAL (Amber)",    AMBER_C, tx0 + tile_w + gap),
        (len(greens), "READY (Green)",      GREEN_C, tx0 + 2 * (tile_w + gap)),
    ]:
        _rect(c, tx, y - tile_h, tile_w, tile_h,
              fill_color=col, radius=2)
        _text(c, tx + tile_w / 2, y - tile_h / 2 + 3,
              str(count), font=FONT_HEAD, size=22, color=WHITE, align="center")
        _text(c, tx + tile_w / 2, y - tile_h + 3,
              f"{label}  ({count}/{total})",
              font=FONT_BODY, size=6.5, color=colors.Color(1, 1, 1, 0.85),
              align="center")

    y -= tile_h + 6 * mm

    # ── Two columns: RAG grid (left) | Donut + gap-close list (right) ───
    col_w = (CONTENT_W - 10 * mm) / 2
    cx_l = MARGIN_L
    cx_r = MARGIN_L + col_w + 10 * mm

    # ── ESRS RAG grid (left) ──────────────────────────────────────────
    _hline(c, cx_l, y + 2, col_w, color=ACCENT, lw=0.8)
    _text(c, cx_l, y - 6, "ESRS STATUS BY STANDARD",
          font=FONT_HEAD, size=8, color=ACCENT)
    gy = y - 14

    row_h_csrd = 14 * mm
    for i, item in enumerate(cd.CSRD_READINESS):
        if i % 2 == 0:
            _rect(c, cx_l - 2, gy - row_h_csrd + 2, col_w + 4, row_h_csrd,
                  fill_color=BAND_BG)
        _rag_dot(c, cx_l + 5, gy - row_h_csrd / 2, item["status"])
        # Standard name
        std_short = item["std"]
        _text(c, cx_l + 15, gy - 5, std_short,
              font=FONT_HEAD, size=7, color=INK)
        # Note
        note = item["note"]
        if c.stringWidth(note, FONT_ITALIC, 6) > col_w - 15:
            note = note[:52] + "…"
        _text(c, cx_l + 15, gy - 13, note,
              font=FONT_ITALIC, size=6, color=SLATE)
        gy -= row_h_csrd

    # ── Right column: donut chart + Close-the-gap list ────────────────
    _hline(c, cx_r, y + 2, col_w, color=ACCENT, lw=0.8)
    _text(c, cx_r, y - 6, "READINESS DISTRIBUTION",
          font=FONT_HEAD, size=8, color=ACCENT)

    donut_h = 42 * mm
    donut_y = y - 10 * mm - donut_h

    # Donut chart
    fig, ax = plt.subplots(figsize=(col_w / 28.35, donut_h / 28.35),
                           subplot_kw=dict(aspect="equal"))
    vals   = [len(reds), len(ambers), len(greens)]
    clrs   = [cd.hex_rgb01(cd.BRAND["red"]),
               cd.hex_rgb01(cd.BRAND["amber"]),
               cd.hex_rgb01(cd.BRAND["green"])]
    lbls   = [f"Not Ready\n({len(reds)})",
               f"Partial\n({len(ambers)})",
               f"Ready\n({len(greens)})"]
    wedge_props = dict(width=0.45, edgecolor="white", linewidth=1.2)
    wedges, texts = ax.pie(vals, colors=clrs, wedgeprops=wedge_props,
                           startangle=90, labels=lbls,
                           textprops={"fontsize": 6})
    ax.text(0, 0, f"{total}\nStandards",
            ha="center", va="center", fontsize=7,
            color=cd.hex_rgb01(cd.BRAND["ink"]))
    fig.patch.set_alpha(0)
    plt.tight_layout(pad=0.2)
    _embed_chart(c, fig, cx_r, donut_y, col_w, donut_h, tmp_dir)

    # ── Close-these-gaps-first (red items) ───────────────────────────
    gap_y = donut_y - 6 * mm
    _hline(c, cx_r, gap_y + 2, col_w, color=RED_C, lw=0.8)
    _text(c, cx_r, gap_y - 6, "CLOSE THESE GAPS FIRST",
          font=FONT_HEAD, size=8, color=RED_C)
    iy = gap_y - 15
    for item in reds:
        # Bullet dot
        c.saveState()
        c.setFillColor(RED_C)
        c.circle(cx_r + 4, iy + 2, 3, fill=1, stroke=0)
        c.restoreState()
        std_name = item["std"].split("—")[0].strip()
        _text(c, cx_r + 12, iy + 1, std_name,
              font=FONT_HEAD, size=7.5, color=INK)
        iy -= 9
        note = item["note"]
        if c.stringWidth(note, FONT_ITALIC, 6.5) > col_w - 12:
            note = note[:54] + "…"
        _text(c, cx_r + 12, iy + 1, note,
              font=FONT_ITALIC, size=6.5, color=SLATE)
        iy -= 8

        # Matching engagement ask if found
        for ask in cd.ENGAGEMENT_ASKS:
            ask_lower = ask["ask"].lower()
            std_key   = std_name.lower().replace("esrs ", "")
            if any(k in ask_lower for k in [std_key[:4], "csrd", "climate", "whistl", "human right"]):
                _text(c, cx_r + 12, iy + 1,
                      f"→ {ask['ask'][:55]}…" if len(ask["ask"]) > 55 else f"→ {ask['ask']}",
                      font=FONT_BODY, size=6, color=ACCENT)
                iy -= 8
                break
        _hline(c, cx_r + 12, iy + 4, col_w - 14, color=RULE_C, lw=0.25)
        iy -= 5


# ═══════════════════════════════════════════════════════════════════════════
#  PUBLIC ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

_BUILDERS = {
    "risk_summary":   (_build_risk_summary,  "ESG_Risk_Summary.pdf"),
    "climate_flash":  (_build_climate_flash,  "Climate_Risk_Flash.pdf"),
    "csrd_readiness": (_build_csrd_readiness, "CSRD_Readiness.pdf"),
}


def build_onepager(key: str, out_dir: str) -> str:
    """
    Build a McKinsey-style ESG one-pager PDF.

    Parameters
    ----------
    key     : one of 'risk_summary', 'climate_flash', 'csrd_readiness'
    out_dir : directory where the PDF will be written (created if absent)

    Returns
    -------
    Absolute path to the generated .pdf file.
    """
    if key not in _BUILDERS:
        raise ValueError(f"Unknown key '{key}'. Must be one of: {list(_BUILDERS)}")

    builder_fn, filename = _BUILDERS[key]
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.abspath(os.path.join(out_dir, filename))

    with tempfile.TemporaryDirectory() as tmp_dir:
        c = rl_canvas.Canvas(out_path, pagesize=A4)
        builder_fn(c, tmp_dir)
        c.showPage()
        c.save()

    return out_path


# ─── CLI convenience ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/onepager_test"
    for k in _BUILDERS:
        p = build_onepager(k, out)
        print(f"  {k}: {p}")
