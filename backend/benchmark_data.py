"""
ESGIntel Sector Benchmarking Engine
===================================
Real percentile / z-score / quartile benchmarking of a company's ESG risk
scores against sector-level reference distributions.

IMPORTANT — REFERENCE DATASET DISCLAIMER
----------------------------------------
`SECTOR_DISTRIBUTIONS` below is a REFERENCE / DEMONSTRATION dataset. The mean
and standard-deviation figures are plausible, ESG-domain-informed estimates of
how ESG *risk* scores are distributed within each NACE sector — they are NOT
sourced from a licensed peer database. They exist so the platform can compute
statistically meaningful benchmarking (z-scores, percentiles, quartiles)
end-to-end.

To productionise: replace `SECTOR_DISTRIBUTIONS` with a call to a real peer
database (e.g. MSCI, Sustainalytics, ISS ESG, or an internal book of scored
companies). The public contract of `compute_benchmarking()` stays identical —
it only needs a `{mean, stddev, n}` per pillar per sector — so the swap is a
data-source change, not a code change.

SCALE
-----
All scores are on the platform's 0–100 ESG *RISK* scale, where a HIGHER score
means GREATER ESG risk (this matches `esg_scores` in app.py / pdf_pipeline.py).
Therefore a HIGHER percentile here means the company carries MORE risk than a
larger share of its sector peers (i.e. worse), and Q4 is the highest-risk
quartile.

Sectors are keyed by NACE Rev. 2 SECTION LETTER (the leading letter of a code
like "C24" -> section "C"). If a sector is unknown, a broad-market default is
used.
"""

from __future__ import annotations

import statistics
from typing import Optional

# ──────────────────────────────────────────────────────────────
# NACE section labels (for human-readable peer-group descriptions)
# ──────────────────────────────────────────────────────────────
NACE_SECTION_LABELS: dict[str, str] = {
    "A": "Agriculture, Forestry & Fishing",
    "B": "Mining & Quarrying",
    "C": "Manufacturing",
    "D": "Electricity, Gas, Steam & Air Conditioning",
    "E": "Water, Sewerage & Waste Management",
    "F": "Construction",
    "G": "Wholesale & Retail Trade",
    "H": "Transportation & Storage",
    "I": "Accommodation & Food Service",
    "J": "Information & Communication",
    "K": "Financial & Insurance Activities",
    "L": "Real Estate Activities",
    "M": "Professional, Scientific & Technical",
    "N": "Administrative & Support Services",
    "O": "Public Administration & Defence",
    "P": "Education",
    "Q": "Human Health & Social Work",
    "R": "Arts, Entertainment & Recreation",
    "S": "Other Service Activities",
    "T": "Household Employers",
    "U": "Extraterritorial Organisations",
}

# ──────────────────────────────────────────────────────────────
# REFERENCE distributions of ESG RISK scores by NACE section.
# Each pillar carries a (mean, stddev) pair on the 0-100 risk scale plus an
# indicative peer-count `n`. Heavy / extractive / carbon-intensive sectors have
# higher environmental-risk means; people-heavy sectors skew social; every
# sector carries baseline governance risk.
# ──────────────────────────────────────────────────────────────
SECTOR_DISTRIBUTIONS: dict[str, dict] = {
    #                overall        environmental   social         governance      peers
    "A": {"overall": (62, 12), "environmental": (66, 13), "social": (60, 13), "governance": (55, 13), "n": 90},
    "B": {"overall": (68, 10), "environmental": (78, 10), "social": (62, 12), "governance": (58, 12), "n": 70},
    "C": {"overall": (55, 12), "environmental": (58, 14), "social": (52, 13), "governance": (50, 12), "n": 320},
    "D": {"overall": (62, 11), "environmental": (72, 12), "social": (50, 12), "governance": (52, 12), "n": 110},
    "E": {"overall": (52, 11), "environmental": (55, 13), "social": (48, 12), "governance": (50, 12), "n": 85},
    "F": {"overall": (58, 12), "environmental": (60, 13), "social": (58, 13), "governance": (54, 12), "n": 160},
    "G": {"overall": (51, 12), "environmental": (48, 13), "social": (55, 13), "governance": (50, 12), "n": 280},
    "H": {"overall": (58, 11), "environmental": (64, 12), "social": (54, 12), "governance": (50, 12), "n": 140},
    "I": {"overall": (51, 12), "environmental": (45, 12), "social": (56, 13), "governance": (52, 12), "n": 120},
    "J": {"overall": (44, 12), "environmental": (38, 12), "social": (48, 13), "governance": (46, 13), "n": 210},
    "K": {"overall": (44, 11), "environmental": (34, 12), "social": (46, 12), "governance": (52, 13), "n": 190},
    "L": {"overall": (48, 12), "environmental": (52, 13), "social": (44, 12), "governance": (48, 12), "n": 100},
    "M": {"overall": (42, 11), "environmental": (36, 12), "social": (44, 12), "governance": (46, 12), "n": 175},
    "N": {"overall": (47, 11), "environmental": (42, 12), "social": (50, 12), "governance": (48, 12), "n": 130},
    "O": {"overall": (46, 11), "environmental": (42, 12), "social": (46, 12), "governance": (50, 13), "n": 60},
    "P": {"overall": (42, 11), "environmental": (38, 12), "social": (44, 12), "governance": (44, 12), "n": 80},
    "Q": {"overall": (47, 11), "environmental": (44, 12), "social": (48, 12), "governance": (48, 12), "n": 95},
    "R": {"overall": (45, 11), "environmental": (40, 12), "social": (48, 12), "governance": (48, 12), "n": 70},
    "S": {"overall": (47, 11), "environmental": (44, 12), "social": (50, 12), "governance": (48, 12), "n": 90},
}

# Broad-market fallback used when the sector is unknown / unmapped.
DEFAULT_DISTRIBUTION: dict = {
    "overall": (52, 13),
    "environmental": (52, 14),
    "social": (52, 13),
    "governance": (52, 13),
    "n": 250,
}

_PILLARS = ("overall", "environmental", "social", "governance")


def _section_letter(sector_code: Optional[str]) -> str:
    """Extract the NACE section letter from a code like 'C24' -> 'C'.

    Falls back to '' (unknown) when no leading letter is present.
    """
    if not sector_code:
        return ""
    for ch in str(sector_code).strip():
        if ch.isalpha():
            return ch.upper()
    return ""


def _quartile(percentile: float) -> str:
    """Map a 0-100 percentile onto a risk quartile label (Q4 = highest risk)."""
    if percentile < 25:
        return "Q1"
    if percentile < 50:
        return "Q2"
    if percentile < 75:
        return "Q3"
    return "Q4"


def _pillar_stat(score, mean: float, stddev: float) -> Optional[dict]:
    """Compute z-score / percentile / quartile for one pillar.

    z-score  = (score - sector_mean) / sector_stddev
    percentile = Phi(z) * 100, using the standard-normal CDF (statistics
                 .NormalDist, Python 3.8+ stdlib — no external dependency).
    Because the scale is a RISK scale, a higher percentile == riskier than a
    larger share of peers.
    """
    if score is None or stddev <= 0:
        return None
    try:
        score = float(score)
    except (TypeError, ValueError):
        return None

    z = (score - mean) / stddev
    percentile = statistics.NormalDist().cdf(z) * 100.0
    return {
        "z_score": round(z, 2),
        "percentile": round(percentile),
        "sector_avg": round(mean, 1),
        "quartile": _quartile(percentile),
    }


def compute_benchmarking(esg_scores: dict, sector_code: str) -> dict:
    """Benchmark a company's ESG risk scores against its sector distribution.

    Args:
        esg_scores: dict with keys overall/environmental/social/governance on
                    the 0-100 risk scale (as produced by the analysis pipeline).
        sector_code: NACE code (e.g. "C24") — only the section letter is used.

    Returns a dict keyed by pillar (overall/environmental/social/governance),
    each carrying {z_score, percentile, sector_avg, quartile}, plus a
    `sector_reference` block describing the peer group used. Pillars with no
    input score are returned as None so the caller can preserve existing
    narrative fields without overwriting them with junk.
    """
    esg_scores = esg_scores or {}
    letter = _section_letter(sector_code)
    dist = SECTOR_DISTRIBUTIONS.get(letter, DEFAULT_DISTRIBUTION)

    out: dict = {
        "sector_reference": {
            "nace_section": letter or None,
            "label": NACE_SECTION_LABELS.get(letter, "Broad market (sector unmapped)"),
            "n_peers": dist.get("n"),
            "is_reference_dataset": True,
        }
    }

    for pillar in _PILLARS:
        mean, stddev = dist.get(pillar, DEFAULT_DISTRIBUTION[pillar])
        out[pillar] = _pillar_stat(esg_scores.get(pillar), mean, stddev)

    return out
