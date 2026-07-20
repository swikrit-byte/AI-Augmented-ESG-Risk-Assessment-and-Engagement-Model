"""
ESGIntel Climate Scenario Engine
================================
Derives NGFS-style climate scenario financials plus a stranded-asset score and
a climate-resilience score (with a capability breakdown) from data the pipeline
has ALREADY computed — `climate.physical_risks`, `climate.transition_risks` and
`policy_maturity` — combined with company size/sector context.

Everything here is a TRANSPARENT, AUDITABLE formula (documented inline), not a
black box and not random numbers. Inputs are the existing 0-100 risk scores;
outputs are:

  * climate.scenarios              — 3 NGFS-aligned scenarios with €M impact,
                                     % of EBITDA, and a short narrative
  * climate.stranded_asset_score   — 0-100 (higher = more stranded-asset risk)
  * climate.resilience_score       — 0-100 (higher = MORE resilient)
  * climate.resilience_capabilities— 4 capabilities, each scored 0-100

Scale note: physical/transition risk `score` fields are 0-100 where HIGHER =
greater risk (matches the rest of the platform). resilience_score is inverted
on purpose so that HIGHER = better, which is how the mockup renders it.
"""

from __future__ import annotations

import re
from typing import Optional


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _mean_score(risks: Optional[list], default: float = 45.0) -> float:
    """Mean of the 0-100 `score` fields in a risk list (physical or transition).

    Returns `default` (a neutral-moderate exposure) when no scored risks exist,
    so scenarios are never blank for a company with a thin climate section.
    """
    if not risks:
        return default
    vals = []
    for r in risks:
        if isinstance(r, dict) and r.get("score") is not None:
            try:
                vals.append(float(r["score"]))
            except (TypeError, ValueError):
                pass
    return sum(vals) / len(vals) if vals else default


# ──────────────────────────────────────────────────────────────
# Sector context by NACE section letter.
#   ebitda_margin  — used to turn a revenue estimate into an EBITDA proxy
#   carbon_factor  — relative transition / stranded-asset exposure (0.4 low
#                    services … 1.3 fossil-heavy). Multiplies transition impact.
# These are ESG-domain reference estimates (see benchmark_data.py disclaimer).
# ──────────────────────────────────────────────────────────────
_SECTOR_CONTEXT: dict[str, dict] = {
    "A": {"ebitda_margin": 0.14, "carbon_factor": 1.00},
    "B": {"ebitda_margin": 0.28, "carbon_factor": 1.30},  # mining
    "C": {"ebitda_margin": 0.15, "carbon_factor": 1.05},  # manufacturing
    "D": {"ebitda_margin": 0.22, "carbon_factor": 1.30},  # energy / utilities
    "E": {"ebitda_margin": 0.16, "carbon_factor": 0.95},  # water / waste
    "F": {"ebitda_margin": 0.12, "carbon_factor": 1.00},  # construction
    "G": {"ebitda_margin": 0.09, "carbon_factor": 0.70},  # retail
    "H": {"ebitda_margin": 0.15, "carbon_factor": 1.20},  # transport
    "I": {"ebitda_margin": 0.13, "carbon_factor": 0.65},  # hospitality
    "J": {"ebitda_margin": 0.22, "carbon_factor": 0.45},  # ICT / tech
    "K": {"ebitda_margin": 0.30, "carbon_factor": 0.55},  # financials (financed emissions)
    "L": {"ebitda_margin": 0.35, "carbon_factor": 0.85},  # real estate
    "M": {"ebitda_margin": 0.20, "carbon_factor": 0.45},  # professional services
    "N": {"ebitda_margin": 0.14, "carbon_factor": 0.55},
    "O": {"ebitda_margin": 0.12, "carbon_factor": 0.55},
    "P": {"ebitda_margin": 0.12, "carbon_factor": 0.45},
    "Q": {"ebitda_margin": 0.13, "carbon_factor": 0.55},
    "R": {"ebitda_margin": 0.13, "carbon_factor": 0.55},
    "S": {"ebitda_margin": 0.13, "carbon_factor": 0.55},
}
_DEFAULT_CONTEXT = {"ebitda_margin": 0.15, "carbon_factor": 0.75}

# ──────────────────────────────────────────────────────────────
# NGFS-style scenario multipliers. Each is the fraction of EBITDA lost at a
# risk severity of 1.0 (i.e. a 100/100 risk score) for that scenario, split
# between the transition channel (carbon price / policy stringency) and the
# physical channel (acute + chronic hazards).
#
#   Orderly     — early, smooth policy: material transition cost, low physical.
#   Disorderly  — late, abrupt policy: highest transition shock, some physical.
#   Hot House   — policy failure: minimal transition cost, severe physical.
# ──────────────────────────────────────────────────────────────
_SCENARIOS = [
    {"name": "Orderly Transition",    "transition_mult": 0.18, "physical_mult": 0.05,
     "narrative": "Early, predictable policy tightening. Transition costs are absorbed gradually; physical damage stays limited as warming is held near 1.5-1.8C."},
    {"name": "Disorderly Transition", "transition_mult": 0.35, "physical_mult": 0.12,
     "narrative": "Delayed then abrupt policy action drives a sharp carbon-price shock and asset repricing, with physical hazards already rising."},
    {"name": "Hot House World",       "transition_mult": 0.05, "physical_mult": 0.40,
     "narrative": "Policy fails and warming exceeds 3C. Transition cost is low but chronic and acute physical impacts dominate the loss."},
]

_NUM_RE = re.compile(r"([\d]+(?:[.,]\d+)?)")


def _parse_revenue_eur_m(revenue: Optional[str]) -> Optional[float]:
    """Best-effort parse of a revenue string into € millions.

    Handles forms like '€1.2bn', '1.2 billion', '€850m', 'USD 500 million'.
    Currency is treated as ~EUR (a demonstration simplification). Returns None
    when nothing numeric is found.
    """
    if not revenue:
        return None
    s = str(revenue).lower().replace(",", "")
    m = _NUM_RE.search(s)
    if not m:
        return None
    try:
        num = float(m.group(1))
    except ValueError:
        return None
    if "bn" in s or "bill" in s or "b€" in s or "€b" in s:
        return num * 1000.0            # billions -> millions
    if "trill" in s or "tn" in s:
        return num * 1_000_000.0
    if "m" in s or "mill" in s:
        return num                     # already millions
    # A bare large number is assumed to be an absolute currency amount.
    if num > 100000:
        return num / 1_000_000.0
    return num


def _parse_employees(employees: Optional[str]) -> Optional[int]:
    if not employees:
        return None
    m = _NUM_RE.search(str(employees).replace(",", ""))
    if not m:
        return None
    try:
        return int(float(m.group(1)))
    except ValueError:
        return None


def _estimate_ebitda_eur_m(revenue: Optional[str], employees: Optional[str], margin: float) -> tuple[float, str]:
    """Estimate an EBITDA proxy in € millions and describe the basis used.

    Priority: parsed revenue x sector margin -> employee headcount proxy
    (~€250k revenue / employee) x margin -> nominal mid-market fallback.
    """
    rev_m = _parse_revenue_eur_m(revenue)
    if rev_m:
        return rev_m * margin, f"revenue ≈ €{rev_m:,.0f}M x {margin:.0%} sector EBITDA margin"
    emp = _parse_employees(employees)
    if emp:
        rev_m = emp * 0.25            # €250k revenue per employee (demonstration proxy)
        return rev_m * margin, f"{emp:,} employees x €250k/head x {margin:.0%} margin"
    # Nominal mid-market fallback so the €M column is never blank.
    return 500.0 * margin, "mid-market fallback (revenue undisclosed): €500M x margin"


# ──────────────────────────────────────────────────────────────
# Resilience capability mapping — each capability draws on matching
# policy_maturity areas (1-5 level) plus the relevant risk channel.
# ──────────────────────────────────────────────────────────────
_CAPABILITY_KEYWORDS = {
    "Emissions monitoring":          ["emission", "environment", "climate", "carbon", "ghg", "energy"],
    "Scenario planning":             ["climate", "risk", "tcfd", "strategy", "resilience", "scenario"],
    "Supply chain resilience":       ["supply", "procure", "supplier", "sourcing", "human right"],
    "Capital allocation flexibility":["governance", "board", "capital", "finance", "risk management", "investment"],
}


def _policy_level(policy_maturity: Optional[list], keywords: list[str]) -> Optional[int]:
    """Return the best matching policy_maturity level (1-5) for a capability."""
    if not policy_maturity:
        return None
    best = None
    for p in policy_maturity:
        if not isinstance(p, dict):
            continue
        area = str(p.get("policy_area", "")).lower()
        if any(kw in area for kw in keywords):
            lvl = p.get("level")
            try:
                lvl = int(lvl)
            except (TypeError, ValueError):
                continue
            if best is None or lvl > best:
                best = lvl
    return best


def _mean_policy_level(policy_maturity: Optional[list]) -> Optional[float]:
    if not policy_maturity:
        return None
    lvls = []
    for p in policy_maturity:
        if isinstance(p, dict) and p.get("level") is not None:
            try:
                lvls.append(int(p["level"]))
            except (TypeError, ValueError):
                pass
    return sum(lvls) / len(lvls) if lvls else None


def compute_climate_scenarios(
    climate: Optional[dict],
    nace_code: str = "",
    revenue: str = "",
    employees: str = "",
    policy_maturity: Optional[list] = None,
) -> dict:
    """Compute scenario financials + stranded-asset/resilience scoring.

    Returns a dict with keys: scenarios, stranded_asset_score, resilience_score,
    resilience_capabilities, scenario_basis. Designed to be merged into the
    existing `climate` block (does not overwrite physical/transition risks).
    """
    climate = climate or {}
    physical_sev = _mean_score(climate.get("physical_risks"))       # 0-100
    transition_sev = _mean_score(climate.get("transition_risks"))   # 0-100

    letter = ""
    for ch in (nace_code or "").strip():
        if ch.isalpha():
            letter = ch.upper()
            break
    ctx = _SECTOR_CONTEXT.get(letter, _DEFAULT_CONTEXT)

    ebitda_m, basis = _estimate_ebitda_eur_m(revenue, employees, ctx["ebitda_margin"])
    carbon_factor = ctx["carbon_factor"]

    # ── Scenario financials ──
    # pct_ebitda = transition_channel + physical_channel, where
    #   transition_channel = (transition_severity/100) * carbon_factor * transition_mult
    #   physical_channel   = (physical_severity/100)   * physical_mult
    # (Transition impact is amplified by the sector's carbon exposure; physical
    #  impact is sector-agnostic hazard damage.) Capped at 60% of EBITDA.
    scenarios = []
    for sc in _SCENARIOS:
        transition_channel = (transition_sev / 100.0) * carbon_factor * sc["transition_mult"]
        physical_channel = (physical_sev / 100.0) * sc["physical_mult"]
        pct = min(transition_channel + physical_channel, 0.60)
        scenarios.append({
            "name": sc["name"],
            "financial_impact_eur_m": round(ebitda_m * pct, 1),
            "pct_ebitda": round(pct * 100, 1),
            "narrative": sc["narrative"],
        })

    # ── Stranded-asset score (0-100, higher = worse) ──
    # Driven by transition risk severity amplified by the sector's carbon /
    # fossil exposure (carbon_factor). Low-carbon sectors are damped, fossil-
    # heavy sectors amplified.
    stranded_asset_score = round(_clamp(transition_sev * carbon_factor))

    # ── Resilience score (0-100, higher = MORE resilient) ──
    # Blend of (a) how mature the company's policies are (policy_maturity mean
    # level, scaled 1-5 -> 0-100) and (b) the inverse of its transition risk
    # (100 - transition_severity). 50/50 weighting. Missing policy data -> 50.
    mean_lvl = _mean_policy_level(policy_maturity)
    policy_component = ((mean_lvl - 1) / 4.0 * 100.0) if mean_lvl is not None else 50.0
    resilience_score = round(_clamp(0.5 * policy_component + 0.5 * (100.0 - transition_sev)))

    # ── Capability breakdown (0-100 each) ──
    # Each capability = 60% its matching policy_maturity level (scaled) + 40%
    # the overall resilience base, so it stays consistent with the headline
    # score while reflecting area-specific evidence. No matched policy -> the
    # resilience base alone.
    resilience_capabilities = []
    for cap, kws in _CAPABILITY_KEYWORDS.items():
        lvl = _policy_level(policy_maturity, kws)
        if lvl is not None:
            cap_score = 0.6 * ((lvl - 1) / 4.0 * 100.0) + 0.4 * resilience_score
        else:
            cap_score = float(resilience_score)
        resilience_capabilities.append({
            "capability": cap,
            "score": round(_clamp(cap_score)),
        })

    return {
        "scenarios": scenarios,
        "stranded_asset_score": stranded_asset_score,
        "resilience_score": resilience_score,
        "resilience_capabilities": resilience_capabilities,
        "scenario_basis": {
            "ebitda_estimate_eur_m": round(ebitda_m, 1),
            "ebitda_basis": basis,
            "physical_severity": round(physical_sev, 1),
            "transition_severity": round(transition_sev, 1),
            "sector_carbon_factor": carbon_factor,
        },
    }
