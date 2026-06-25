"""
ESGIntel PDF Intelligence Pipeline
===================================
Discovers, downloads, and deeply analyzes annual reports and sustainability
reports from a company's website using Claude Opus.

Sub-agent architecture:
  1. DiscoveryAgent   — crawls website + searches the web to find PDF report links
  2. WebSearchAgent   — queries DuckDuckGo/Bing for report PDFs when crawling finds nothing
  3. ExtractionAgent  — runs Claude Opus over each PDF to extract structured ESG data
  4. AggregatorAgent  — merges multi-year data, deduplicates, runs trend analysis
  5. EnricherAgent    — merges PDF-extracted KPIs back into the main analysis result

Two-phase design (called from app.py run_analysis()):
  Phase 1 — discover_and_get_pdf_texts(): runs BEFORE the main AI analysis so the AI
             sees actual report content (quantitative metrics, emission intensities, etc.)
  Phase 2 — run_pdf_pipeline(): runs AFTER AI analysis to extract structured KPI data
             via Opus and merge into result["kpis"]. Accepts pre_discovered_pdfs from
             Phase 1 to avoid re-downloading.
"""

import os, re, json, io, asyncio
from pathlib import Path
from typing import Optional

import httpx
import pdfplumber
from anthropic import Anthropic

# ──────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────
OPUS_MODEL   = "claude-opus-4-8"
HAIKU_MODEL  = "claude-haiku-4-5-20251001"
MAX_PDFS     = 8          # max PDFs to analyze per company
CHARS_PER_PDF = 150_000   # chars extracted from each PDF (full doc)
MAX_PAGES_PER_PDF = 150   # pdfplumber page cap per document

# Keywords that indicate a relevant ESG/annual report link
REPORT_KEYWORDS = [
    "sustainability", "annual-report", "annual_report", "esg", "csr",
    "integrated-report", "integrated_report", "climate", "tcfd", "responsibility",
    "baerekraft", "arsrapport", "aarsrapport", "rapport-de-durabilite",
    "haastegevuslikkus", "yhteiskuntavastuu", "hallbarhets",
    "sustainabilityreport", "annualreport", "esgreport",
    "halbarhet", "nachhaltigkeit", "nachhaltigkeitsbericht",
    "annual report", "sustainability report",
]

REPORT_PAGE_PATHS = [
    # English — sustainability
    "/sustainability/reports", "/sustainability/reports-and-publications",
    "/en/sustainability/reports", "/en/sustainability/reports-and-publications",
    "/sustainability", "/esg", "/esg/reports", "/csr/reports",
    "/corporate-responsibility/reports", "/responsibility/reports",
    "/climate/reports", "/environment/reports",
    # English — investor relations
    "/investor-relations/reports", "/investor-relations/annual-reports",
    "/investor-relations/reports-and-presentations",
    "/en/investor-relations/reports-and-presentations/annual-reports",
    "/en/investor-relations", "/en/investor-relations/reports",
    "/investors/reports", "/investors/annual-reports",
    "/investors/financial-reports", "/investor-centre/reports",
    # Generic report hubs
    "/reports", "/publications", "/downloads", "/media",
    "/annual-report", "/sustainability-report", "/esg-report",
    "/about/sustainability/reports", "/about-us/sustainability",
    "/about/reports", "/about-us/reports",
    # Nordic/European locales
    "/hallbarhet/rapporter", "/nachhaltigkeit/berichte",
    "/baerekraft/rapporter", "/ansvar/rapporter",
    # Common CMS media roots (Sitecore, Kentico, Umbraco)
    "/-/media", "/globalassets", "/siteassets", "/media/documents",
    "/contentassets", "/dam/reports", "/assets/reports",
]

# ── Target years for multi-year coverage ──
TARGET_YEARS = [2025, 2024, 2023, 2022, 2021, 2020, 2019]

# ──────────────────────────────────────────────────────────────
# PDF TEXT EXTRACTION
# ──────────────────────────────────────────────────────────────
def extract_pdf_text(content: bytes, max_pages: int = MAX_PAGES_PER_PDF) -> str:
    """Extract text from PDF bytes using pdfplumber. Returns up to max_pages."""
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = pdf.pages[:max_pages]
            parts = []
            for i, page in enumerate(pages):
                text = page.extract_text() or ""
                if text.strip():
                    parts.append(f"[Page {i+1}]\n{text}")
            return "\n\n".join(parts)
    except Exception as e:
        return f"[PDF extraction failed: {e}]"


# ──────────────────────────────────────────────────────────────
# AI-POWERED URL DISCOVERY
# ──────────────────────────────────────────────────────────────

def _ai_generate_pdf_urls(company_name: str, base_url: str) -> list[str]:
    """
    Use Haiku to generate a list of likely direct PDF download URLs for this company.
    Covers annual reports and sustainability reports across TARGET_YEARS.
    Returns absolute URLs to try directly.
    """
    api_key = os.getenv("CLAUDE_API_KEY", "")
    if not api_key:
        return []
    client = Anthropic(api_key=api_key)
    years_str = ", ".join(str(y) for y in TARGET_YEARS)
    prompt = f"""You are helping locate publicly available PDF reports for ESG due diligence.

Company: {company_name}
Website: {base_url}
Target years: {years_str}

Generate up to 25 likely direct PDF URL paths for this company's:
- Annual reports (e.g. "Annual Report 2024")
- Sustainability / ESG reports (e.g. "Sustainability Report 2024")
- Integrated reports
- Climate / TCFD reports

Use the website domain structure you would expect for this specific company.
Consider common CMS patterns:
- Sitecore: /-/media/Company_Annual_Report_2024.pdf
- Generic: /reports/annual-report-2024.pdf
- Investor relations: /investor-relations/annual-report-2024.pdf
- Direct media: /globalassets/annual-report-2024.pdf
- CDN: /contentassets/.../annual-report-2024.pdf

Return ONLY a valid JSON array of URL paths (must start with /). No prose, no markdown.
Example: ["/-/media/Annual_Report_2024_EN.pdf", "/reports/sustainability-2023.pdf"]"""

    try:
        resp = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        paths = json.loads(raw)
        if not isinstance(paths, list):
            return []
        base = base_url.rstrip("/")
        return [base + p if p.startswith("/") else p for p in paths if isinstance(p, str)]
    except Exception:
        return []


# ──────────────────────────────────────────────────────────────
# WEB SEARCH AGENT — finds report PDFs via DuckDuckGo when crawling fails
# ──────────────────────────────────────────────────────────────
async def search_reports_online(
    company_name: str,
    base_url: str,
    client: httpx.AsyncClient,
) -> dict[str, str]:
    """
    Query DuckDuckGo HTML for annual and sustainability report PDFs.
    Returns {url: anchor_text} dict of candidate PDF URLs.
    Used as a fallback when the website crawler finds no PDFs.
    """
    import urllib.parse

    domain = base_url.replace("https://", "").replace("http://", "").split("/")[0]
    found: dict[str, str] = {}

    # Search queries — site-scoped first, then broader
    queries = [
        f'site:{domain} filetype:pdf "annual report"',
        f'site:{domain} filetype:pdf "sustainability report"',
        f'site:{domain} filetype:pdf "ESG report"',
        f'"{company_name}" annual report 2024 filetype:pdf',
        f'"{company_name}" sustainability report 2024 filetype:pdf',
        f'"{company_name}" ESG report 2023 OR 2024 filetype:pdf',
        f'"{company_name}" integrated report 2024 filetype:pdf',
        f'"{company_name}" TCFD report filetype:pdf',
    ]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # DuckDuckGo HTML endpoint (no API key needed)
    for q in queries[:5]:  # limit to 5 queries to avoid rate limiting
        try:
            encoded = urllib.parse.urlencode({"q": q})
            r = await client.get(
                f"https://html.duckduckgo.com/html/?{encoded}",
                timeout=12,
                headers=headers,
            )
            if r.status_code != 200:
                continue
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a.get("href", "").strip()
                text = a.get_text(" ", strip=True)
                # DuckDuckGo wraps real URLs in redirect links — extract the real URL
                if "//duckduckgo.com/l/" in href or "uddg=" in href:
                    try:
                        parsed = urllib.parse.urlparse(href)
                        params = urllib.parse.parse_qs(parsed.query)
                        real_url = params.get("uddg", [href])[0]
                        href = urllib.parse.unquote(real_url)
                    except Exception:
                        pass
                if href.lower().endswith(".pdf") and href.startswith("http"):
                    combined = (href + " " + text).lower()
                    if any(kw in combined for kw in REPORT_KEYWORDS):
                        found[href] = text
        except Exception:
            pass

    # Bing fallback if DuckDuckGo found nothing
    if not found:
        for q in queries[:4]:
            try:
                encoded = urllib.parse.urlencode({"q": q, "count": "20"})
                r = await client.get(
                    f"https://www.bing.com/search?{encoded}",
                    timeout=12,
                    headers=headers,
                )
                if r.status_code != 200:
                    continue
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a.get("href", "").strip()
                    text = a.get_text(" ", strip=True)
                    if href.lower().endswith(".pdf") and href.startswith("http"):
                        combined = (href + " " + text).lower()
                        if any(kw in combined for kw in REPORT_KEYWORDS):
                            found[href] = text
            except Exception:
                pass

    return found


def _extrapolate_year_variants(found_urls: dict[str, str]) -> dict[str, str]:
    """
    For any PDF URL that contains a year (2019-2025), generate variants
    for all TARGET_YEARS by substituting the year in the URL.
    Returns new {url: anchor} pairs to add to the candidate set.
    """
    extras: dict[str, str] = {}
    year_re = re.compile(r"(20(?:19|2[0-5]))")
    for url, anchor in found_urls.items():
        m = year_re.search(url)
        if not m:
            continue
        found_year = m.group(1)
        for yr in TARGET_YEARS:
            variant = url.replace(found_year, str(yr), 1)
            if variant != url and variant not in found_urls:
                extras[variant] = anchor.replace(found_year, str(yr)) if found_year in anchor else anchor
    return extras


# ──────────────────────────────────────────────────────────────
# PRIMARY DISCOVERY: Claude Opus + web_search_20250305
# Runs BEFORE the website crawler so we find reports even on JS-heavy or
# CDN-hosted sites where HTML scraping returns no PDF links.
# ──────────────────────────────────────────────────────────────
async def _claude_web_search_for_reports(
    company_name: str,
    base_url: str,
    log_fn=None,
) -> dict[str, str]:
    """
    Use Claude Opus with the built-in web_search tool to find annual/sustainability
    report PDFs.  Returns {url: description} of discovered PDF links.

    The web_search_20250305 tool is executed server-side by Anthropic — we run a
    standard agentic tool_use loop to collect Claude's final answer.
    """
    from anthropic import AsyncAnthropic

    def _l(msg: str, done: bool = False):
        if log_fn:
            log_fn(msg, done=done)

    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY", "")
    if not api_key:
        return {}

    ai = AsyncAnthropic(api_key=api_key)
    domain = base_url.replace("https://", "").replace("http://", "").split("/")[0]
    found: dict[str, str] = {}

    prompt = (
        f"Search the web for direct PDF download links to corporate reports published by "
        f"'{company_name}' (website: {base_url}).\n\n"
        f"Look for ALL of these document types:\n"
        f"- Annual report / årsrapport (years 2022, 2023, 2024, 2025)\n"
        f"- Sustainability report / bærekraftsrapport\n"
        f"- ESG report / integrated report / TCFD report / climate report\n\n"
        f"Search the company website directly AND public sources. "
        f"For each PDF you find, output a line in this exact format:\n"
        f"PDF: <full URL ending in .pdf> | <year> <report type>\n\n"
        f"Only output lines for direct .pdf file URLs you are confident exist. "
        f"Prioritise documents from {domain}."
    )

    messages: list[dict] = [{"role": "user", "content": prompt}]

    for turn in range(10):  # max agentic turns
        try:
            response = await ai.messages.create(
                model=OPUS_MODEL,
                max_tokens=4096,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=messages,
            )
        except Exception as exc:
            _l(f"Claude web search error (turn {turn}): {str(exc)[:80]}")
            break

        # Record assistant turn
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # Parse PDF URLs from Claude's final response
            for block in response.content:
                if hasattr(block, "text"):
                    for m in re.finditer(r'https?://[^\s<>"\'()\[\]]+\.pdf', block.text):
                        url = m.group().rstrip(".,;)|>")
                        if url not in found:
                            found[url] = company_name + " report"
            break

        elif response.stop_reason == "tool_use":
            # web_search_20250305 is server-side: Anthropic executes the search.
            # We send back empty tool_results so the loop continues.
            tool_results = []
            for block in response.content:
                if hasattr(block, "type") and block.type == "tool_use":
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "",
                    })
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
            else:
                break  # no tool_use blocks found — avoid infinite loop
        else:
            break  # unexpected stop_reason

    return found


# ──────────────────────────────────────────────────────────────
# AGENT 1: DISCOVERY
# ──────────────────────────────────────────────────────────────
async def discover_report_pdfs(
    base_url: str,
    client: httpx.AsyncClient,
    company_name: str = "",
    seed_urls: Optional[dict[str, str]] = None,
) -> list[dict]:
    """
    Crawl the company website to find PDF annual/sustainability reports.
    seed_urls: {url: anchor} dict of PDF candidates already found by the Opus web search
               (Track A). Injected immediately into the candidate pool so they are scored
               and downloaded alongside crawler-found PDFs.
    Returns a list of {"url": ..., "text": ..., "filename": ..., "size": ...}.
    """
    base_url = base_url.rstrip("/")
    if not base_url.startswith("http"):
        base_url = "https://" + base_url

    found_pdfs: dict[str, str] = {}   # url -> anchor text

    # ── Step 0: seed with Opus web search results ──
    if seed_urls:
        for url, anchor in seed_urls.items():
            found_pdfs[url] = anchor or company_name + " report"

    def _abs(href: str) -> str:
        href = href.strip()
        if href.startswith("http"):
            return href
        if href.startswith("//"):
            return "https:" + href
        return base_url + "/" + href.lstrip("/")

    # Keywords that identify a page as a sustainability/investor/report hub
    _REPORT_PAGE_KEYWORDS = [
        "sustainability", "baerekraft", "bærekraft", "hallbarhet", "nachhaltigkeit",
        "investor", "rapport", "reports", "publications", "esg", "csr",
        "responsibility", "annual", "downloads", "media",
    ]

    def _is_report_page(url: str) -> bool:
        """True if the page URL suggests it's a sustainability/investor/report hub."""
        url_lower = url.lower()
        return any(kw in url_lower for kw in _REPORT_PAGE_KEYWORDS)

    def _is_report_link(href: str, anchor: str, page_is_report_page: bool = False) -> bool:
        """
        True if this link looks like a direct PDF report download.
        If we're already on a report/sustainability page, trust any PDF link —
        companies like Vy use opaque CDN URLs (e.g. /files/eyx1eny7/hash.pdf)
        with generic "Download" anchor text that contain no keywords.
        """
        if not href.lower().endswith(".pdf"):
            return False
        if page_is_report_page:
            return True  # On a report page: accept any PDF (it's almost certainly a report)
        combined = (href + " " + anchor).lower()
        return any(kw in combined for kw in REPORT_KEYWORDS)

    # ── Step 1: fetch homepage + known report-index pages concurrently ──
    async def _get_page(url: str) -> tuple[str, str]:
        try:
            r = await client.get(url, timeout=12, follow_redirects=True)
            if r.status_code == 200:
                return url, r.text
        except Exception:
            pass
        return url, ""

    pages_to_check = [base_url] + [base_url + p for p in REPORT_PAGE_PATHS]
    results = await asyncio.gather(*[_get_page(u) for u in pages_to_check[:20]])

    # ── Step 2: harvest PDF links from each fetched page ──
    secondary_pages: set[str] = set()

    for page_url, html in results:
        if not html:
            continue
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a.get("href", "").strip()
                anchor = a.get_text(" ", strip=True)
                if not href:
                    continue
                abs_href = _abs(href)
                if _is_report_link(href, anchor):
                    found_pdfs[abs_href] = anchor
                elif any(kw in href.lower() or kw in anchor.lower()
                         for kw in ["report", "download", "publication", "investor", "sustainability", "annual"]):
                    if abs_href.startswith(base_url) or any(d in abs_href for d in [base_url.split("//")[-1].split("/")[0]]):
                        secondary_pages.add(abs_href)
        except Exception:
            pass

    # ── Step 3: fetch secondary pages to find more PDFs ──
    secondary_results = await asyncio.gather(
        *[_get_page(u) for u in list(secondary_pages - {r[0] for r in results})[:15]]
    )
    for page_url, html in secondary_results:
        if not html:
            continue
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            page_ctx = _is_report_page(page_url)  # e.g. vy.no/sustainability → True
            for a in soup.find_all("a", href=True):
                href = a.get("href", "").strip()
                anchor = a.get_text(" ", strip=True)
                if href and _is_report_link(href, anchor, page_is_report_page=page_ctx):
                    found_pdfs[_abs(href)] = anchor
        except Exception:
            pass

    # ── Step 4: year-extrapolation — generate year variants from found URLs ──
    year_variants = _extrapolate_year_variants(found_pdfs)
    found_pdfs.update(year_variants)

    # ── Step 5: AI URL generation — fill gaps when crawler found few PDFs ──
    # Always run this to supplement crawler results with AI-generated candidate URLs
    ai_urls = _ai_generate_pdf_urls(company_name, base_url)
    for url in ai_urls:
        if url not in found_pdfs:
            found_pdfs[url] = ""  # no anchor text for AI-generated URLs

    # Also generate year variants from the AI-discovered URLs
    ai_year_variants = _extrapolate_year_variants({u: "" for u in ai_urls})
    for url in ai_year_variants:
        if url not in found_pdfs:
            found_pdfs[url] = ""

    # ── Step 6: Web search fallback — when crawler finds few/no PDFs ──
    # Many companies use JavaScript-rendered report pages that BeautifulSoup can't parse.
    # If we have fewer than 2 PDF candidates, supplement with web search results.
    if len(found_pdfs) < 2:
        web_pdfs = await search_reports_online(company_name, base_url, client)
        for url, anchor in web_pdfs.items():
            if url not in found_pdfs:
                found_pdfs[url] = anchor
        if web_pdfs:
            # Also generate year variants from web-found URLs
            web_variants = _extrapolate_year_variants(web_pdfs)
            for url in web_variants:
                if url not in found_pdfs:
                    found_pdfs[url] = ""

    if not found_pdfs:
        return []

    # ── Step 7: score and download top PDFs ──
    def _score_pdf(url: str, anchor: str) -> int:
        score = 0
        combined = (url + " " + anchor).lower()
        for kw in ["sustainability", "annual", "esg", "integrated", "climate", "tcfd", "environment"]:
            if kw in combined:
                score += 2
        # Reward coverage of multiple years — prefer spread across years over duplication
        for yr in TARGET_YEARS:
            if str(yr) in combined:
                score += 4
                break
        # Penalise likely non-report PDFs
        for bad in ["proxy", "governance-guidelines", "terms", "privacy", "form-"]:
            if bad in combined:
                score -= 5
        return score

    ranked = sorted(found_pdfs.items(), key=lambda kv: _score_pdf(kv[0], kv[1]), reverse=True)

    async def _download(url: str, anchor: str) -> Optional[dict]:
        try:
            r = await client.get(url, timeout=40, follow_redirects=True)
            if r.status_code == 200 and len(r.content) > 20_000:
                ct = r.headers.get("content-type", "")
                if "pdf" not in ct.lower() and not url.lower().endswith(".pdf"):
                    return None
                text = extract_pdf_text(r.content)
                if len(text) < 800:
                    return None
                filename = url.split("/")[-1].split("?")[0] or "report.pdf"
                return {
                    "url": url,
                    "anchor": anchor,
                    "filename": filename,
                    "size_bytes": len(r.content),
                    "text": text[:CHARS_PER_PDF],
                    "_text_len": len(text),
                }
        except Exception:
            pass
        return None

    # Download candidates in batches — try more candidates since many AI URLs may 404
    download_tasks = [_download(url, anchor) for url, anchor in ranked[:MAX_PDFS * 4]]
    dl_results = await asyncio.gather(*download_tasks)
    valid = [r for r in dl_results if r]

    # De-duplicate by filename (same report downloaded from two URL variants)
    seen_fnames: set[str] = set()
    deduped = []
    for r in valid:
        fname = r["filename"].lower()
        if fname not in seen_fnames:
            seen_fnames.add(fname)
            deduped.append(r)

    # Sort by text length (richer = more content), keep top MAX_PDFS
    deduped.sort(key=lambda x: x["_text_len"], reverse=True)
    for r in deduped:
        r.pop("_text_len", None)
    return deduped[:MAX_PDFS]


# ──────────────────────────────────────────────────────────────
# AGENT 2: EXTRACTION (Claude Opus)
# ──────────────────────────────────────────────────────────────
PDF_EXTRACTION_SYSTEM = """You are a senior sustainability analyst with CFA-ESG and GRI-certified expertise.
Your task is to extract every quantitative ESG data point from a corporate sustainability or annual report.

CRITICAL RULES:
1. Only extract data explicitly stated in the provided text. Never invent values.
2. Include the exact page number (e.g. "p.47") in the source field whenever visible.
3. Capture ALL years of data found in the document — multi-year tables are especially valuable.
4. For each metric, record the exact unit as stated in the document.
5. Return ONLY valid JSON — no markdown fences, no preamble."""

PDF_EXTRACTION_PROMPT = """Extract all quantitative and material qualitative ESG data from this corporate report.

Company: {company_name}
Document: {filename}

Return a JSON object with this exact schema. Set any field to null if the data is not present in the document.

{{
  "report_meta": {{
    "title": "full report title as stated",
    "year": <integer reporting year, e.g. 2023>,
    "type": "sustainability|annual|integrated|esg|climate|tcfd",
    "frameworks": ["GRI", "SASB", "TCFD", "ESRS", "CDP", "IFRS S2", "UN SDGs", ...],
    "assurance": "Limited|Reasonable|None",
    "auditor": "assurance provider name or null"
  }},
  "ghg_emissions": {{
    "scope1": [{{"year": <int>, "value": <number>, "unit": "tCO2e"}}],
    "scope2_location": [{{"year": <int>, "value": <number>, "unit": "tCO2e"}}],
    "scope2_market": [{{"year": <int>, "value": <number>, "unit": "tCO2e"}}],
    "scope3_total": [{{"year": <int>, "value": <number>, "unit": "tCO2e"}}],
    "scope3_categories": {{
      "cat1_purchased_goods": [{{"year": <int>, "value": <number>, "unit": "tCO2e"}}],
      "cat6_business_travel": [{{"year": <int>, "value": <number>, "unit": "tCO2e"}}],
      "cat11_use_of_sold_products": [{{"year": <int>, "value": <number>, "unit": "tCO2e"}}],
      "cat15_investments_financed": [{{"year": <int>, "value": <number>, "unit": "tCO2e"}}]
    }},
    "total_emissions": [{{"year": <int>, "value": <number>, "unit": "tCO2e"}}],
    "emission_intensity": [{{"year": <int>, "value": <number>, "unit": "tCO2e per unit (specify unit)"}}]
  }},
  "energy": {{
    "total_consumption": [{{"year": <int>, "value": <number>, "unit": "GJ|MWh|kWh"}}],
    "electricity": [{{"year": <int>, "value": <number>, "unit": "GJ|MWh|kWh"}}],
    "renewable_electricity_pct": [{{"year": <int>, "value": <number>, "unit": "%"}}],
    "renewable_energy_pct": [{{"year": <int>, "value": <number>, "unit": "%"}}],
    "heat_and_steam": [{{"year": <int>, "value": <number>, "unit": "GJ|MWh"}}],
    "energy_intensity": [{{"year": <int>, "value": <number>, "unit": "unit (specify)"}}]
  }},
  "water": {{
    "total_withdrawal": [{{"year": <int>, "value": <number>, "unit": "m3|ML|kL"}}],
    "municipal_supply": [{{"year": <int>, "value": <number>, "unit": "m3|ML"}}],
    "surface_water": [{{"year": <int>, "value": <number>, "unit": "m3|ML"}}],
    "total_discharge": [{{"year": <int>, "value": <number>, "unit": "m3|ML"}}],
    "water_recycled_pct": [{{"year": <int>, "value": <number>, "unit": "%"}}],
    "water_intensity": [{{"year": <int>, "value": <number>, "unit": "unit (specify)"}}]
  }},
  "waste": {{
    "total_waste": [{{"year": <int>, "value": <number>, "unit": "tonnes|MT"}}],
    "hazardous_waste": [{{"year": <int>, "value": <number>, "unit": "tonnes"}}],
    "non_hazardous_waste": [{{"year": <int>, "value": <number>, "unit": "tonnes"}}],
    "waste_recycled_pct": [{{"year": <int>, "value": <number>, "unit": "%"}}],
    "landfill_pct": [{{"year": <int>, "value": <number>, "unit": "%"}}]
  }},
  "social": {{
    "total_employees": [{{"year": <int>, "value": <number>, "unit": "FTE|headcount"}}],
    "employees_female_pct": [{{"year": <int>, "value": <number>, "unit": "%"}}],
    "employees_male_pct": [{{"year": <int>, "value": <number>, "unit": "%"}}],
    "management_female_pct": [{{"year": <int>, "value": <number>, "unit": "%"}}],
    "new_hires": [{{"year": <int>, "value": <number>, "unit": "number"}}],
    "voluntary_turnover_pct": [{{"year": <int>, "value": <number>, "unit": "%"}}],
    "total_turnover_pct": [{{"year": <int>, "value": <number>, "unit": "%"}}],
    "training_hours_per_employee": [{{"year": <int>, "value": <number>, "unit": "hours"}}],
    "ltifr": [{{"year": <int>, "value": <number>, "unit": "per million hours worked"}}],
    "trifr": [{{"year": <int>, "value": <number>, "unit": "per million hours worked"}}],
    "fatalities": [{{"year": <int>, "value": <number>, "unit": "number"}}],
    "gender_pay_gap_pct": [{{"year": <int>, "value": <number>, "unit": "% gap"}}],
    "employee_engagement_score": [{{"year": <int>, "value": <number>, "unit": "%|score"}}]
  }},
  "governance": {{
    "board_size": [{{"year": <int>, "value": <number>, "unit": "members"}}],
    "board_female_pct": [{{"year": <int>, "value": <number>, "unit": "%"}}],
    "board_independent_pct": [{{"year": <int>, "value": <number>, "unit": "%"}}],
    "ceo_pay_ratio": [{{"year": <int>, "value": <number>, "unit": "x median employee"}}],
    "executive_pay_ratio": [{{"year": <int>, "value": <number>, "unit": "x"}}],
    "ethics_violations": [{{"year": <int>, "value": <number>, "unit": "number"}}],
    "whistleblower_reports": [{{"year": <int>, "value": <number>, "unit": "number"}}]
  }},
  "climate_targets": [
    {{
      "target": "description of target",
      "baseline_year": <int or null>,
      "target_year": <int or null>,
      "scope": "Scope 1|Scope 1+2|Scope 1+2+3|All Scopes",
      "reduction_pct": <number or null>,
      "sbti_aligned": true|false|null,
      "status": "Committed|In Progress|Achieved|null"
    }}
  ],
  "net_zero": {{
    "committed": true|false,
    "target_year": <int or null>,
    "pathway": "1.5C|Well below 2C|2C|Not specified|null"
  }},
  "biodiversity": {{
    "policy_exists": true|false|null,
    "tnfd_aligned": true|false|null,
    "protected_areas_commitment": true|false|null
  }},
  "supply_chain": {{
    "suppliers_assessed_pct": [{{"year": <int>, "value": <number>, "unit": "%"}}],
    "suppliers_audited_pct": [{{"year": <int>, "value": <number>, "unit": "%"}}],
    "supplier_code_of_conduct": true|false|null
  }},
  "financial_context": {{
    "revenue": [{{"year": <int>, "value": <number>, "unit": "currency (specify)"}}],
    "employees_reported": <number or null>,
    "hq_country": "string or null",
    "reporting_boundary": "string (e.g. 'Operational control', 'Financial control')"
  }},
  "key_qualitative_findings": [
    "string — each a specific, evidence-backed finding from the document"
  ],
  "data_sources": [
    {{"metric": "which metric", "page": "e.g. p.47", "table": "table name if applicable"}}
  ]
}}

Extract every single data point available. For time-series data, include ALL years shown in tables — not just the most recent. Include any metrics specific to the financial sector (e.g. financed emissions, portfolio carbon intensity, green finance volumes) if present.

DOCUMENT TEXT:
{text}"""


def _call_opus_extract(text: str, company_name: str, filename: str) -> dict:
    """Call Claude Opus to extract structured ESG data from a single PDF's text."""
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        raise ValueError("CLAUDE_API_KEY not set in .env")

    client = Anthropic(api_key=api_key)
    prompt = PDF_EXTRACTION_PROMPT.format(
        company_name=company_name,
        filename=filename,
        text=text[:CHARS_PER_PDF],
    )

    message = client.messages.create(
        model=OPUS_MODEL,
        max_tokens=8000,
        system=PDF_EXTRACTION_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    # Extract JSON span
    for i, ch in enumerate(raw):
        if ch == "{":
            raw = raw[i:]
            break
    try:
        return json.loads(raw)
    except Exception:
        # Best-effort repair
        try:
            raw = re.sub(r",\s*([\}\]])", r"\1", raw)  # trailing commas
            return json.loads(raw)
        except Exception:
            return {"_parse_error": raw[:500]}


# ──────────────────────────────────────────────────────────────
# AGENT 3: AGGREGATOR + TREND ANALYST
# ──────────────────────────────────────────────────────────────
def _merge_time_series(series_list: list[list[dict]]) -> list[dict]:
    """Merge time series from multiple documents, deduplicate by year, keep most-recent source."""
    merged: dict[int, dict] = {}
    for series in series_list:
        if not isinstance(series, list):
            continue
        for entry in series:
            if not isinstance(entry, dict):
                continue
            yr = entry.get("year")
            if yr is None:
                continue
            try:
                yr = int(yr)
            except (ValueError, TypeError):
                continue
            if yr not in merged or entry.get("value") is not None:
                merged[yr] = {**entry, "year": yr}
    return sorted(merged.values(), key=lambda x: x["year"])


def _trend(series: list[dict]) -> Optional[dict]:
    """Calculate trend metrics for a time series."""
    if not series:
        return None
    vals = [(e["year"], e["value"]) for e in series if e.get("value") is not None]
    if len(vals) < 2:
        return {"direction": "insufficient_data", "n_years": len(vals)}

    vals.sort(key=lambda x: x[0])
    years = [v[0] for v in vals]
    values = [v[1] for v in vals]

    # YoY latest
    if len(values) >= 2:
        yoy = (values[-1] - values[-2]) / abs(values[-2]) if values[-2] != 0 else None
    else:
        yoy = None

    # CAGR
    n = years[-1] - years[0]
    if n > 0 and values[0] > 0:
        cagr = (values[-1] / values[0]) ** (1 / n) - 1
    else:
        cagr = None

    # Direction (based on CAGR or YoY)
    rate = cagr if cagr is not None else yoy
    if rate is None:
        direction = "unknown"
    elif rate < -0.03:
        direction = "decreasing"
    elif rate > 0.03:
        direction = "increasing"
    else:
        direction = "stable"

    return {
        "direction": direction,
        "yoy_pct_latest": round(yoy * 100, 1) if yoy is not None else None,
        "cagr_pct": round(cagr * 100, 1) if cagr is not None else None,
        "n_years": len(vals),
        "first_year": years[0],
        "latest_year": years[-1],
        "first_value": values[0],
        "latest_value": values[-1],
    }


def aggregate_extractions(extracted_docs: list[dict], company_name: str) -> dict:
    """
    Merge all per-PDF extractions into a unified time-series dataset.
    Runs Python-side trend analysis on every metric.
    """
    if not extracted_docs:
        return {"error": "No PDF data extracted"}

    # ── Merge time series by metric ──
    def collect(field_path: list[str]) -> list[dict]:
        """Collect all time-series entries for a nested field across all docs."""
        all_series = []
        for doc in extracted_docs:
            node = doc
            for key in field_path:
                node = node.get(key) if isinstance(node, dict) else None
                if node is None:
                    break
            if isinstance(node, list):
                all_series.append(node)
        return _merge_time_series(all_series)

    def collect_nested(parent: str, child: str) -> list[dict]:
        all_series = []
        for doc in extracted_docs:
            parent_node = doc.get(parent, {})
            if isinstance(parent_node, dict):
                node = parent_node.get(child)
                if isinstance(node, list):
                    all_series.append(node)
        return _merge_time_series(all_series)

    # Gather all time series
    metrics = {
        # GHG
        "scope1_emissions":            collect(["ghg_emissions", "scope1"]),
        "scope2_location_emissions":   collect(["ghg_emissions", "scope2_location"]),
        "scope2_market_emissions":     collect(["ghg_emissions", "scope2_market"]),
        "scope3_total_emissions":      collect(["ghg_emissions", "scope3_total"]),
        "scope3_cat15_financed":       collect(["ghg_emissions", "scope3_categories", "cat15_investments_financed"]),
        "scope3_cat6_travel":          collect(["ghg_emissions", "scope3_categories", "cat6_business_travel"]),
        "total_emissions":             collect(["ghg_emissions", "total_emissions"]),
        "emission_intensity":          collect(["ghg_emissions", "emission_intensity"]),
        # Energy
        "total_energy":                collect_nested("energy", "total_consumption"),
        "renewable_electricity_pct":   collect_nested("energy", "renewable_electricity_pct"),
        "renewable_energy_pct":        collect_nested("energy", "renewable_energy_pct"),
        "electricity_consumption":     collect_nested("energy", "electricity"),
        # Water
        "water_withdrawal":            collect_nested("water", "total_withdrawal"),
        "water_recycled_pct":          collect_nested("water", "water_recycled_pct"),
        # Waste
        "total_waste":                 collect_nested("waste", "total_waste"),
        "waste_recycled_pct":          collect_nested("waste", "waste_recycled_pct"),
        # Social
        "total_employees":             collect_nested("social", "total_employees"),
        "employees_female_pct":        collect_nested("social", "employees_female_pct"),
        "management_female_pct":       collect_nested("social", "management_female_pct"),
        "voluntary_turnover_pct":      collect_nested("social", "voluntary_turnover_pct"),
        "training_hours_per_employee": collect_nested("social", "training_hours_per_employee"),
        "ltifr":                       collect_nested("social", "ltifr"),
        "gender_pay_gap_pct":          collect_nested("social", "gender_pay_gap_pct"),
        "employee_engagement_score":   collect_nested("social", "employee_engagement_score"),
        # Governance
        "board_female_pct":            collect_nested("governance", "board_female_pct"),
        "board_independent_pct":       collect_nested("governance", "board_independent_pct"),
        "ceo_pay_ratio":               collect_nested("governance", "ceo_pay_ratio"),
    }

    # ── Trend analysis ──
    trends = {key: _trend(series) for key, series in metrics.items() if series}

    # ── Collect targets & net-zero commitments ──
    targets = []
    net_zero = {}
    for doc in extracted_docs:
        for t in (doc.get("climate_targets") or []):
            if isinstance(t, dict) and t not in targets:
                targets.append(t)
        if doc.get("net_zero") and doc["net_zero"].get("committed"):
            if not net_zero.get("committed"):
                net_zero = doc["net_zero"]

    # ── Collect frameworks ──
    frameworks: set[str] = set()
    for doc in extracted_docs:
        meta = doc.get("report_meta") or {}
        for f in (meta.get("frameworks") or []):
            if isinstance(f, str) and f:
                frameworks.add(f)

    # ── Build flat KPI list for the frontend ──
    kpis = _build_kpi_list(metrics, extracted_docs)

    # ── Key findings ──
    findings: list[str] = []
    for doc in extracted_docs:
        for f in (doc.get("key_qualitative_findings") or []):
            if isinstance(f, str) and f not in findings:
                findings.append(f)

    # ── Reports metadata ──
    reports = []
    for doc in extracted_docs:
        meta = doc.get("report_meta") or {}
        src  = doc.get("_source_url", "")
        fname = doc.get("_filename", "")
        reports.append({
            "url":       src,
            "filename":  fname,
            "title":     meta.get("title") or fname,
            "year":      meta.get("year"),
            "type":      meta.get("type"),
            "assurance": meta.get("assurance"),
            "frameworks": meta.get("frameworks") or [],
        })

    # Data quality
    available_series = sum(1 for v in metrics.values() if v)
    data_quality = "high" if available_series >= 12 else ("medium" if available_series >= 6 else "low")

    return {
        "pdf_reports_analyzed": reports,
        "reports_count": len(reports),
        "time_series": metrics,
        "trend_analysis": trends,
        "climate_targets": targets,
        "net_zero": net_zero or None,
        "frameworks_referenced": sorted(frameworks),
        "kpis": kpis,
        "key_findings": findings[:20],
        "data_quality": data_quality,
        "metrics_available": available_series,
    }


def _build_kpi_list(metrics: dict, docs: list[dict]) -> list[dict]:
    """
    Convert time-series data into a flat KPI list compatible with the frontend
    renderKpiTable() function. Each row = latest year's value for each metric.
    """

    METRIC_LABELS = {
        "scope1_emissions":            ("Scope 1 GHG Emissions",           "tCO2e",  "environmental"),
        "scope2_location_emissions":   ("Scope 2 GHG (Location-based)",    "tCO2e",  "environmental"),
        "scope2_market_emissions":     ("Scope 2 GHG (Market-based)",      "tCO2e",  "environmental"),
        "scope3_total_emissions":      ("Scope 3 GHG Emissions (Total)",   "tCO2e",  "environmental"),
        "scope3_cat15_financed":       ("Scope 3 Cat.15 Financed Emissions","tCO2e", "environmental"),
        "scope3_cat6_travel":          ("Scope 3 Cat.6 Business Travel",   "tCO2e",  "environmental"),
        "total_emissions":             ("Total GHG Emissions",             "tCO2e",  "environmental"),
        "emission_intensity":          ("GHG Emission Intensity",          "tCO2e/unit","environmental"),
        "total_energy":                ("Total Energy Consumption",        "GJ",     "environmental"),
        "renewable_electricity_pct":   ("Renewable Electricity Share",     "%",      "environmental"),
        "renewable_energy_pct":        ("Renewable Energy Share",          "%",      "environmental"),
        "electricity_consumption":     ("Electricity Consumption",        "MWh",    "environmental"),
        "water_withdrawal":            ("Total Water Withdrawal",          "m³",     "environmental"),
        "water_recycled_pct":          ("Water Recycled/Reused",           "%",      "environmental"),
        "total_waste":                 ("Total Waste Generated",           "tonnes", "environmental"),
        "waste_recycled_pct":          ("Waste Recycled/Recovered",        "%",      "environmental"),
        "total_employees":             ("Total Employees",                 "FTE",    "social"),
        "employees_female_pct":        ("Female Employees",                "%",      "social"),
        "management_female_pct":       ("Women in Management",             "%",      "social"),
        "voluntary_turnover_pct":      ("Voluntary Employee Turnover",     "%",      "social"),
        "training_hours_per_employee": ("Training Hours per Employee",     "hours",  "social"),
        "ltifr":                       ("Lost-Time Injury Rate (LTIFR)",  "per M hrs","social"),
        "gender_pay_gap_pct":          ("Gender Pay Gap",                  "%",      "social"),
        "employee_engagement_score":   ("Employee Engagement Score",       "%",      "social"),
        "board_female_pct":            ("Women on Board",                  "%",      "governance"),
        "board_independent_pct":       ("Independent Board Directors",     "%",      "governance"),
        "ceo_pay_ratio":               ("CEO Pay Ratio",                  "x median","governance"),
    }

    kpis = []
    for key, (label, default_unit, category) in METRIC_LABELS.items():
        series = metrics.get(key, [])
        if not series:
            continue
        # Get the latest entry with a real value
        latest = None
        for entry in sorted(series, key=lambda x: x.get("year", 0), reverse=True):
            if entry.get("value") is not None:
                latest = entry
                break
        if not latest:
            continue
        unit = latest.get("unit") or default_unit
        year = str(latest.get("year", ""))
        val  = latest.get("value")
        if val is None:
            continue

        # Format value nicely
        if isinstance(val, float) and val == int(val):
            val_str = f"{int(val):,}"
        elif isinstance(val, (int, float)):
            val_str = f"{val:,.1f}" if val < 1000 else f"{val:,.0f}"
        else:
            val_str = str(val)

        # Source: find first report that has this metric
        source = None
        for doc in docs:
            meta = doc.get("report_meta") or {}
            title = meta.get("title") or doc.get("_filename") or ""
            yr    = meta.get("year")
            if yr and str(yr) == year and title:
                source = title
                break
        if not source and docs:
            meta = (docs[0].get("report_meta") or {})
            source = meta.get("title") or docs[0].get("_filename") or "PDF Report"

        kpis.append({
            "category":  category,
            "metric":    label,
            "value":     val_str,
            "unit":      unit,
            "year":      year,
            "source":    source,
            "benchmark": None,
            "percentile": None,
            "available": True,
        })

    return kpis


# ──────────────────────────────────────────────────────────────
# AGENT 4: ENRICHER — merge PDF KPIs into main analysis
# ──────────────────────────────────────────────────────────────
def enrich_analysis(result: dict, pdf_intel: dict) -> dict:
    """
    Merge PDF-extracted KPIs into the main analysis result.
    PDF-sourced KPIs take precedence over AI-inferred ones.
    """
    if not pdf_intel or "error" in pdf_intel:
        result["pdf_intelligence"] = None
        return result

    # Store full PDF intelligence
    result["pdf_intelligence"] = pdf_intel

    # Merge KPIs: PDF-sourced data overrides inferred data for the same metric
    existing_kpis = result.get("kpis") or []
    pdf_kpis = pdf_intel.get("kpis") or []

    if pdf_kpis:
        # Index existing by metric name (lowercase)
        existing_by_metric = {k["metric"].lower(): k for k in existing_kpis if k.get("metric")}
        for pk in pdf_kpis:
            key = (pk.get("metric") or "").lower()
            existing_by_metric[key] = pk  # PDF data wins
        result["kpis"] = list(existing_by_metric.values())

    # Merge net-zero and targets into data_coverage
    dc = result.get("data_coverage") or {}
    if pdf_intel.get("net_zero", {}) and pdf_intel["net_zero"].get("committed"):
        dc["sbti_committed"] = True
        dc["net_zero_year"]  = pdf_intel["net_zero"].get("target_year")
    if pdf_intel.get("frameworks_referenced"):
        existing_fw = set(dc.get("frameworks_referenced") or [])
        existing_fw.update(pdf_intel["frameworks_referenced"])
        dc["frameworks_referenced"] = sorted(existing_fw)
    dc["pdf_reports_analyzed"] = pdf_intel.get("reports_count", 0)
    dc["data_quality_pdf"]     = pdf_intel.get("data_quality")
    result["data_coverage"] = dc

    return result


# ──────────────────────────────────────────────────────────────
# PHASE 1 — Early text extraction (runs BEFORE the main AI analysis)
# ──────────────────────────────────────────────────────────────
async def discover_and_get_pdf_texts(
    company_name: str,
    website_url: str,
    log_fn=None,
) -> list[dict]:
    """
    Phase 1 of the PDF pipeline: discover and download report PDFs, return their raw text.

    Discovery strategy (two parallel tracks):
      Track A — Claude Opus + web_search_20250305 (ALWAYS runs):
        Searches the web for "{company} annual report PDF", etc. Finds reports even
        when the company site uses JS rendering, CDN-hosted hash URLs, or opaque link text.
      Track B — Website crawler (ALWAYS runs in parallel):
        Crawls the company's own site, report-index pages, and secondary pages.
        Now context-aware: PDFs on sustainability/investor pages are accepted regardless
        of whether the URL or anchor text contains report keywords.
      Both tracks feed into discover_report_pdfs() for scoring, dedup, and download.

    Returns a list of {"url": str, "filename": str, "text": str, "anchor": str}.
    Called BEFORE the main AI analysis so Claude sees actual report content.
    """
    def _l(msg: str, done: bool = False):
        if log_fn:
            log_fn(msg, done=done)

    if not website_url:
        return []
    if not website_url.startswith("http"):
        website_url = "https://" + website_url

    base_url = website_url.rstrip("/")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ESGIntelBot/1.0; +https://esgintel.io/bot)"}

    try:
        # ── Track A: Claude Opus web search (primary, runs first) ──
        _l(f"Searching for annual & sustainability reports via Opus web search…")
        claude_pdf_urls: dict[str, str] = {}
        try:
            claude_pdf_urls = await _claude_web_search_for_reports(
                company_name, base_url, log_fn=log_fn
            )
            if claude_pdf_urls:
                _l(f"Opus web search found {len(claude_pdf_urls)} PDF candidate(s)")
        except Exception as ws_err:
            _l(f"Opus web search skipped: {str(ws_err)[:60]}")

        # ── Track B: Website crawler (runs in parallel context) ──
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers=headers,
            verify=False,
        ) as client:
            pdfs = await discover_report_pdfs(
                base_url, client,
                company_name=company_name,
                seed_urls=claude_pdf_urls,   # inject Opus-found URLs into the crawler pool
            )

        if pdfs:
            years_found = sorted(
                {int(m) for p in pdfs
                 for m in re.findall(r"20[12][0-9]", p.get("url", "") + p.get("filename", ""))},
                reverse=True,
            )
            ystr = " · ".join(str(y) for y in years_found) if years_found else "year unknown"
            _l(f"Reports found ({ystr}): {len(pdfs)} PDF(s) — injecting into AI analysis context", done=True)
        else:
            _l("No public reports discovered — AI analysis proceeds on available text", done=True)

        return pdfs

    except Exception as e:
        _l(f"Early PDF discovery error: {str(e)[:60]}", done=True)
        return []


# ──────────────────────────────────────────────────────────────
# MAIN PIPELINE ENTRY POINT
# ──────────────────────────────────────────────────────────────
async def run_pdf_pipeline(
    company_name: str,
    website_url: str,
    log_fn=None,
    pre_discovered_pdfs: Optional[list[dict]] = None,
) -> dict:
    """
    Phase 2: Opus structured extraction → aggregation → trend analysis → KPI list.
    Called from run_analysis() in app.py AFTER the main AI analysis calls.

    pre_discovered_pdfs: if Phase 1 (discover_and_get_pdf_texts) already ran, pass its
    output here to skip re-discovery and avoid double-downloading the same PDFs.
    log_fn: optional callable(msg, done=bool) for live progress streaming.
    """
    def _l(msg: str, done: bool = False):
        if log_fn:
            log_fn(msg, done=done)

    if not website_url:
        return {"error": "No website URL provided"}

    if not website_url.startswith("http"):
        website_url = "https://" + website_url

    base_url = website_url.rstrip("/")
    domain = base_url.replace("https://", "").replace("http://", "").split("/")[0]

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ESGIntelBot/1.0; +https://esgintel.io/bot)",
    }

    try:
        # ── Agent 1: Discover PDFs (skip if Phase 1 already ran) ──
        if pre_discovered_pdfs is not None:
            pdfs = pre_discovered_pdfs
            if pdfs:
                _l(f"Using {len(pdfs)} pre-discovered reports from Phase 1 — skipping re-download", done=True)
        else:
            async with httpx.AsyncClient(
                timeout=15,
                follow_redirects=True,
                headers=headers,
                verify=False,
            ) as client:
                pdfs = await discover_report_pdfs(base_url, client, company_name=company_name)

        if not pdfs:
            _l(f"No PDF reports found for {company_name} — check website URL", done=True)
            return {"error": "No PDF reports found on company website", "reports_count": 0}

        # Show which years were found
        import re as _re
        years_found = sorted({int(m) for p in pdfs for m in _re.findall(r"20[12][0-9]", p.get("url","") + p.get("filename",""))}, reverse=True)
        years_str = " · ".join(str(y) for y in years_found) if years_found else "year unknown"
        names = [p.get("filename", "report.pdf") for p in pdfs[:3]]
        _l(f"Found {len(pdfs)} reports ({years_str}) — {' · '.join(names)}{'…' if len(pdfs) > 3 else ''}", done=True)

        # ── Agent 2: Extract with Opus (sequential — Opus is expensive) ──
        extracted_docs = []
        for i, pdf in enumerate(pdfs):
            text = pdf.get("text", "")
            if not text or len(text) < 500:
                continue
            fname = pdf.get("filename", "report.pdf")
            pages_est = round(len(text) / 3000)  # ~3000 chars/page
            _l(f"Extracting [{i+1}/{len(pdfs)}]: {fname} (~{pages_est}p) with Claude Opus…")
            try:
                doc_data = _call_opus_extract(text, company_name, fname)
                doc_data["_source_url"] = pdf.get("url", "")
                doc_data["_filename"]   = fname
                extracted_docs.append(doc_data)
                # Count how many metrics were found
                ghg = doc_data.get("ghg_emissions", {}) or {}
                def _has_values(series):
                    """True only when at least one entry has a non-null numeric value."""
                    return any(
                        e.get("value") is not None
                        for e in (series or [])
                        if isinstance(e, dict)
                    )
                has_scope1 = _has_values(ghg.get("scope1")) or _has_values(ghg.get("total_emissions"))
                has_intensity = _has_values(ghg.get("emission_intensity"))
                metric_tag = "GHG + intensity data" if (has_scope1 and has_intensity) else ("GHG data" if has_scope1 else "qualitative data extracted")
                _l(f"Extracted {fname} — {metric_tag}", done=True)
            except Exception as e:
                extracted_docs.append({
                    "_source_url": pdf.get("url", ""),
                    "_filename":   fname,
                    "_extraction_error": str(e),
                })
                _l(f"Extraction failed for {fname}: {str(e)[:50]}", done=True)

        if not extracted_docs:
            return {"error": "PDF extraction returned no data", "reports_count": len(pdfs)}

        # ── Agent 3: Aggregate + trend analysis ──
        _l("Running Python trend analysis across all extracted metrics…")
        aggregated = aggregate_extractions(extracted_docs, company_name)
        ts_count = len(aggregated.get("time_series", {}))
        trend_count = len(aggregated.get("trend_analysis", {}))
        _l(f"Trend analysis complete — {ts_count} metric series · {trend_count} trends computed", done=True)
        return aggregated

    except Exception as e:
        _l(f"PDF pipeline error: {str(e)[:60]}", done=True)
        return {"error": f"Pipeline failed: {str(e)}", "reports_count": 0}
