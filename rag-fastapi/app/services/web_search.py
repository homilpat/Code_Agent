import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    publisher: str
    snippet: str
    score: float
    checked_at: str


class WebSearchService:
    """Search the web through the project's self-hosted SearXNG instance."""

    _TRUSTED_HOSTS = {
        "arxiv.org": 1.0,
        "doi.org": 1.0,
        "docs.python.org": 1.0,
        "developer.mozilla.org": 1.0,
        "kubernetes.io": 1.0,
        "pytorch.org": 1.0,
        "tensorflow.org": 1.0,
        "w3.org": 1.0,
        "rfc-editor.org": 1.0,
        "nist.gov": 1.0,
        "iso.org": 1.0,
        "ieee.org": 0.95,
        "acm.org": 0.95,
        "spring.io": 0.95,
        "docs.docker.com": 0.95,
        "learn.microsoft.com": 0.95,
        "cloud.google.com": 0.95,
        "docs.aws.amazon.com": 0.95,
    }
    _TRACKING_KEYS = {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "gclid", "fbclid",
    }

    @staticmethod
    def _canonical_url(value: str) -> str:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        query = urlencode([
            (key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in WebSearchService._TRACKING_KEYS
        ])
        return urlunsplit((parsed.scheme, parsed.netloc.casefold(), parsed.path, query, ""))

    @classmethod
    def authority_score(cls, host: str) -> float:
        normalized = host.removeprefix("www.").casefold()
        for trusted, score in cls._TRUSTED_HOSTS.items():
            if normalized == trusted or normalized.endswith("." + trusted):
                return score
        if normalized.endswith((".gov", ".gov.uk", ".go.kr", ".edu", ".ac.kr")):
            return 0.95
        return 0.35

    def search(self, query: str, limit: int | None = None) -> List[WebSearchResult]:
        if not settings.SEARXNG_URL:
            return []
        result_limit = limit or settings.WEB_SEARCH_MAX_RESULTS
        try:
            response = httpx.get(
                settings.SEARXNG_URL.rstrip("/") + "/search",
                params={
                    "q": query,
                    "format": "json",
                    "categories": "general,science,it",
                    "language": "all",
                    "safesearch": 1,
                },
                timeout=settings.WEB_SEARCH_TIMEOUT_SECONDS,
                follow_redirects=False,
            )
            response.raise_for_status()
            rows = response.json().get("results", [])
        except Exception as error:
            logger.warning("Self-hosted web search unavailable: %s", error)
            return []

        checked_at = datetime.now(timezone.utc).isoformat()
        ranked = []
        seen = set()
        for rank, row in enumerate(rows, start=1):
            url = self._canonical_url(str(row.get("url", "")))
            if not url or url in seen:
                continue
            seen.add(url)
            title = str(row.get("title", "")).strip()
            snippet = str(row.get("content", "")).strip()
            if not title:
                continue
            publisher = urlsplit(url).netloc.removeprefix("www.")
            authority = self.authority_score(publisher)
            search_score = float(row.get("score") or 0.0)
            score = authority * 0.7 + min(search_score, 1.0) * 0.2 + (1 / rank) * 0.1
            ranked.append(WebSearchResult(
                title=title[:300],
                url=url,
                publisher=publisher,
                snippet=snippet[:800],
                score=round(score, 4),
                checked_at=checked_at,
            ))
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:result_limit]


web_search_service = WebSearchService()
