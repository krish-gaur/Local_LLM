"""Deterministic extraction of links and source-grounded facts from untrusted snapshots."""
from __future__ import annotations

from datetime import date, datetime
import re
from urllib.parse import parse_qs, unquote, urlparse

from localpilot.agent.types import Json
from localpilot.tools.base import PermissionClass, Tool, ToolContext, ToolResult


_URL_RE = re.compile(r"https?://[^\s\"'<>\]\[)]+", re.IGNORECASE)
_PRICE_RE = re.compile(
    r"(?:(?:₹|Rs\.?|INR)\s*)([0-9][0-9,.]*)(?:\s*(lakh|lac|crore|cr))?", re.IGNORECASE)
_DATE_RE = re.compile(r"\b(?:20\d{2}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]20\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+20\d{2})\b", re.IGNORECASE)
_STOP = {"the", "and", "for", "with", "par", "karo", "search", "ki", "ka", "sabse", "mein", "car"}
_REPUTABLE_VEHICLE_HOSTS = {"autocarindia.com", "cardekho.com", "carwale.com", "zigwheels.com",
                            "timesofindia.indiatimes.com"}
_BYD_OFFICIAL_HOSTS = {"byd.com", "bydautoindia.com"}


def _host_matches(host: str, candidates: set[str]) -> bool:
    return any(host == candidate or host.endswith("." + candidate) for candidate in candidates)


def _unwrap(url: str) -> str:
    url = unquote(url.rstrip(".,;:"))
    parsed = urlparse(url)
    if parsed.netloc.endswith("google.com") and parsed.path in {"/url", "/search"}:
        params = parse_qs(parsed.query)
        candidate = (params.get("q") or params.get("url") or [url])[0]
        if candidate.startswith(("http://", "https://")): return candidate
    return url


def extract_links(snapshot: str, query: str, max_results: int, search_host: str = "") -> list[str]:
    tokens = {token for token in re.findall(r"[a-z0-9]+", query.lower()) if len(token) > 2 and token not in _STOP}
    candidates: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for position, match in enumerate(_URL_RE.finditer(snapshot.replace("\\u0026", "&"))):
        url = _unwrap(match.group(0)); parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc: continue
        host = parsed.netloc.lower().removeprefix("www.")
        if search_host and (host == search_host or host.endswith(f".{search_host}")): continue
        if host.endswith(("googleusercontent.com", "gstatic.com")): continue
        canonical = parsed._replace(fragment="").geturl()
        if canonical in seen: continue
        seen.add(canonical)
        haystack = f"{host} {parsed.path}".lower()
        relevance = sum(2 for token in tokens if token in haystack)
        if _host_matches(host, _BYD_OFFICIAL_HOSTS): relevance += 5
        elif _host_matches(host, _REPUTABLE_VEHICLE_HOSTS): relevance += 2
        candidates.append((-relevance, position, canonical))
    candidates.sort()
    return [item[2] for item in candidates[:max_results]]


class SearchLinkExtractorTool(Tool):
    name = "research.extract_links"
    description = "Extract bounded HTTP(S) result links from an untrusted search snapshot"
    permission = PermissionClass.READ_ONLY
    schema: dict[str, Json] = {"type": "object", "properties": {
        "snapshot": {"type": "string", "maxLength": 100000},
        "query": {"type": "string", "maxLength": 500},
        "max_results": {"type": "integer"},
        "search_host": {"type": "string", "maxLength": 253}},
        "required": ["snapshot", "query", "max_results", "search_host"]}

    def execute(self, arguments: dict[str, Json], context: ToolContext) -> ToolResult:
        context.raise_if_cancelled(); count = int(arguments["max_results"])
        if not 1 <= count <= 5: return ToolResult.failure("invalid_result_limit", "max_results must be 1..5")
        links = extract_links(str(arguments["snapshot"]), str(arguments["query"]), count,
                              str(arguments["search_host"]))
        if len(links) < count:
            return ToolResult.failure("insufficient_search_results",
                f"only {len(links)} usable result links were observed; required {count}")
        return ToolResult.success({"links": links, "count": len(links), "observed": True})


def _money_value(number: str, unit: str | None) -> int:
    value = float(number.replace(",", "")); unit = (unit or "").lower()
    if unit in {"lakh", "lac"}: value *= 100_000
    elif unit in {"crore", "cr"}: value *= 10_000_000
    return int(value)


def _evidence_excerpt(content: str, start: int, end: int, radius: int = 150) -> str:
    return re.sub(r"\s+", " ", content[max(0, start - radius):min(len(content), end + radius)]).strip()


def _price_type(excerpt: str) -> str:
    lower = excerpt.lower()
    if "on-road" in lower or "on road" in lower: return "on-road"
    if "ex-showroom" in lower or "ex showroom" in lower: return "ex-showroom"
    if "starting" in lower or "starts at" in lower: return "starting/unspecified"
    return "unspecified"


def _date_status(observed: str | None, as_of: str) -> str:
    if observed is None: return "missing"
    formats = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%b %d, %Y", "%B %d, %Y")
    for format_name in formats:
        try:
            observed_date = datetime.strptime(observed, format_name).date()
            return "outdated" if (date.fromisoformat(as_of) - observed_date).days > 365 else "current"
        except ValueError: continue
    return "unparsed"


def compare_sources(query: str, market: str, sources: list[dict[str, str]], as_of_date: str) -> dict[str, Json]:
    findings: list[dict[str, Json]] = []; report_sources: list[dict[str, Json]] = []
    observations: list[dict[str, Json]] = []
    query_tokens = [token for token in re.findall(r"[a-z0-9]+", query.lower())
                    if len(token) > 2 and token not in _STOP]
    for source in sources:
        url, content = source["url"], source["content"]
        report_sources.append({"url": url, "evidence": content[:100000]})
        lower_content = content.lower(); positions = [lower_content.find(token) for token in query_tokens]
        observed_at = min((position for position in positions if position >= 0), default=0)
        observations.append({"url": url,
            "evidence": re.sub(r"\s+", " ", content[max(0, observed_at - 60):observed_at + 260]).strip()})
        for match in _PRICE_RE.finditer(content):
            excerpt = _evidence_excerpt(content, *match.span())
            subject_match = re.search(r"\bBYD\s+[A-Za-z0-9-]+(?:\s+[A-Za-z0-9-]+){0,2}", excerpt, re.IGNORECASE)
            subject = subject_match.group(0) if subject_match else "vehicle/product not explicit near price"
            date_match = _DATE_RE.search(excerpt); observed_date = date_match.group(0) if date_match else None
            findings.append({"url": url, "subject": subject,
                "amount_inr": _money_value(match.group(1), match.group(2)),
                "stated_price": match.group(0), "price_type": _price_type(excerpt),
                "evidence": excerpt, "market_observed": market.lower() in content.lower(),
                "observed_date": observed_date, "date_status": _date_status(observed_date, as_of_date)})
    limitations: list[Json] = []
    price_request = bool(findings) or any(
        term in query.lower() for term in ("price", "cost", "cheapest", "sasti", "kimat", "कीमत", "सस्ती"))
    if not price_request:
        summaries = "; ".join(f"{urlparse(str(item['url'])).netloc}: {str(item['evidence'])[:160]}"
                              for item in observations)
        return {"query": query, "market": market, "as_of_date": as_of_date, "findings": [],
                "observations": observations,
                "conclusion": f"Inspected source observations: {summaries}",
                "verified_conclusion": False, "conflicts": [],
                "limitations": ["No deterministic cross-source consensus criterion exists for this non-price topic."],
                "source_urls": [source["url"] for source in sources], "report_sources": report_sources}
    comparable = [item for item in findings if item["market_observed"] and item["price_type"] != "unspecified"]
    distinct = {str(item["url"]) for item in comparable}
    official = any(_host_matches(urlparse(url).netloc.lower().removeprefix("www."), _BYD_OFFICIAL_HOSTS)
                   for url in distinct)
    price_types = {str(item["price_type"]) for item in comparable}
    grouped: dict[str, list[int]] = {}
    for item in comparable: grouped.setdefault(str(item["subject"]).lower(), []).append(int(item["amount_inr"]))
    conflicts = [subject for subject, amounts in grouped.items()
                 if len(amounts) > 1 and max(amounts) > min(amounts) * 1.05]
    stale_or_missing = [item for item in comparable if item["date_status"] in {"missing", "outdated", "unparsed"}]
    conclusion: str
    verified = (len(distinct) >= 3 and official and len(price_types) == 1
                and not conflicts and not stale_or_missing)
    if verified:
        cheapest = min(comparable, key=lambda item: int(item["amount_inr"]))
        conclusion = (f"Lowest comparable observed price: {cheapest['subject']} at "
                      f"{cheapest['stated_price']} ({cheapest['price_type']}) for {market}, "
                      f"supported by inspected evidence. Source: {cheapest['url']}.")
    else:
        conclusion = "Evidence was insufficient for a verified cheapest-price conclusion."
        if len(distinct) < 3: limitations.append("Fewer than three inspected sources contained prices.")
        if not official: limitations.append("No inspected official/manufacturer domain contained a price.")
        if not comparable: limitations.append("Market and price type were not both explicit in comparable evidence.")
        if len(price_types) > 1: limitations.append("Observed prices used conflicting price types.")
        if conflicts: limitations.append(f"Conflicting prices were observed for: {', '.join(conflicts)}.")
    if stale_or_missing: limitations.append("Some price evidence had missing, unparsed, or older-than-one-year dates.")
    return {"query": query, "market": market, "as_of_date": as_of_date, "findings": findings,
            "observations": observations,
            "conclusion": conclusion, "verified_conclusion": verified, "conflicts": conflicts,
            "limitations": limitations,
            "source_urls": [source["url"] for source in sources], "report_sources": report_sources}


class CompareSourcesTool(Tool):
    name = "research.compare_sources"
    description = "Compare only explicitly observed source snapshots using deterministic criteria"
    permission = PermissionClass.READ_ONLY
    schema: dict[str, Json] = {"type": "object", "properties": {
        "query": {"type": "string", "maxLength": 500}, "market": {"type": "string", "maxLength": 100},
        "as_of_date": {"type": "string", "maxLength": 32},
        "sources": {"type": "array", "maxItems": 5, "items": {"type": "object", "properties": {
            "url": {"type": "string", "maxLength": 4096}, "content": {"type": "string", "maxLength": 100000}},
            "required": ["url", "content"]}}},
        "required": ["query", "market", "as_of_date", "sources"]}

    def execute(self, arguments: dict[str, Json], context: ToolContext) -> ToolResult:
        context.raise_if_cancelled(); sources = arguments["sources"]
        assert isinstance(sources, list)
        if len(sources) < 2: return ToolResult.failure("insufficient_sources", "at least two sources are required")
        return ToolResult.success(compare_sources(str(arguments["query"]), str(arguments["market"]),
                                                  sources, str(arguments["as_of_date"])))  # type: ignore[arg-type]
