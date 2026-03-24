"""
agentic_app/search.py
Program Purpose: Implements direct website crawling bindings against IndianKanoon.org, allowing extraction of standard judgments directly instead of API calls.
Input: Free-text search phrases representing court arguments.
Output: A python List containing custom parsed SearchCandidates metadata blocks.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from agentic_app.http import HttpClient
from agentic_app.models import SearchCandidate, SearchTrace


INDIAN_KANOON_DOC_PATTERN = re.compile(r"^https://indiankanoon\.org/doc/\d+/$")
INDIAN_KANOON_DOCFRAGMENT_PATTERN = re.compile(r"^https://indiankanoon\.org/docfragment/\d+/")


class CourtSearchService:
    def __init__(self, http_client: HttpClient) -> None:
        self.http_client = http_client

    def search_indian_kanoon(
        self,
        query: str,
        *,
        trace: SearchTrace | None = None,
        limit: int = 10,
    ) -> list[SearchCandidate]:
        if trace:
            trace.add(
                "search_request",
                "Searching Indian Kanoon",
                query=query,
                metadata={"limit": limit},
            )

        response = self.http_client.get(
            "https://indiankanoon.org/search/",
            params={"formInput": query},
        )
        soup = BeautifulSoup(response.text, "html.parser")
        candidates: list[SearchCandidate] = []

        for result in soup.select(".result, .browselist, .result_title, .searchresult"):
            anchor = result.select_one("a[href]")
            if not anchor:
                continue
            href = urljoin("https://indiankanoon.org", anchor.get("href", ""))
            title = anchor.get_text(" ", strip=True)
            snippet = result.get_text(" ", strip=True)
            if not href or not title:
                continue
            candidate = SearchCandidate(
                title=title,
                url=href,
                source="Indian Kanoon Search",
                snippet=snippet,
            )
            candidates.append(candidate)
            if trace:
                trace.add(
                    "search_result_found",
                    "Found candidate from Indian Kanoon search",
                    query=query,
                    url=href,
                    depth=0,
                    path=[href],
                    metadata={"title": title},
                )
            if len(candidates) >= limit:
                break

        if not candidates:
            for anchor in soup.select("a[href]"):
                href = urljoin("https://indiankanoon.org", anchor.get("href", ""))
                if not (INDIAN_KANOON_DOC_PATTERN.match(href) or INDIAN_KANOON_DOCFRAGMENT_PATTERN.match(href)):
                    continue
                title = anchor.get_text(" ", strip=True)
                if not title:
                    continue
                candidate = SearchCandidate(
                    title=title,
                    url=href,
                    source="Indian Kanoon Search",
                )
                candidates.append(candidate)
                if trace:
                    trace.add(
                        "search_result_found",
                        "Found fallback candidate from Indian Kanoon page links",
                        query=query,
                        url=href,
                        depth=0,
                        path=[href],
                        metadata={"title": title},
                    )
                if len(candidates) >= limit:
                    break

        deduped = self._dedupe(candidates)
        if trace:
            trace.add(
                "search_complete",
                "Completed Indian Kanoon search",
                query=query,
                metadata={"raw_count": len(candidates), "deduped_count": len(deduped)},
            )
        return deduped

    def resolve_candidate(
        self,
        candidate: SearchCandidate,
        *,
        trace: SearchTrace | None = None,
    ) -> SearchCandidate:
        if INDIAN_KANOON_DOC_PATTERN.match(candidate.url):
            return candidate

        if not INDIAN_KANOON_DOCFRAGMENT_PATTERN.match(candidate.url):
            return candidate

        # Indian Kanoon search often lands on a docfragment page, but the final
        # citation we want is the linked full judgment URL under /doc/<id>/.
        if trace:
            trace.add(
                "fragment_open",
                "Opening Indian Kanoon fragment page to locate full judgment link",
                url=candidate.url,
                metadata={"title": candidate.title},
            )

        response = self.http_client.get(candidate.url)
        soup = BeautifulSoup(response.text, "html.parser")

        for anchor in soup.select("a[href]"):
            href = urljoin("https://indiankanoon.org", anchor.get("href", ""))
            if not INDIAN_KANOON_DOC_PATTERN.match(href):
                continue
            title = anchor.get_text(" ", strip=True) or candidate.title
            if trace:
                trace.add(
                    "fragment_resolved",
                    "Resolved fragment page to a full Indian Kanoon judgment URL",
                    url=href,
                    parent_url=candidate.url,
                    path=[candidate.url, href],
                    metadata={"title": title},
                )
            return SearchCandidate(
                title=title,
                url=href,
                source="Indian Kanoon Fragment Resolution",
                snippet=candidate.snippet,
            )

        normalized = self._normalize_indian_kanoon_url(candidate.url)
        if trace:
            trace.add(
                "fragment_resolution_failed",
                "Could not find a linked full judgment URL inside the fragment page",
                url=candidate.url,
                metadata={"fallback_url": normalized},
            )
        return SearchCandidate(
            title=candidate.title,
            url=normalized,
            source=candidate.source,
            snippet=candidate.snippet,
        )

    def _dedupe(self, candidates: list[SearchCandidate]) -> list[SearchCandidate]:
        seen: set[str] = set()
        unique: list[SearchCandidate] = []
        for candidate in candidates:
            if candidate.url in seen:
                continue
            seen.add(candidate.url)
            unique.append(candidate)
        return unique

    def _normalize_indian_kanoon_url(self, url: str) -> str:
        match = re.search(r"/docfragment/(\d+)/", url)
        if match:
            return f"https://indiankanoon.org/doc/{match.group(1)}/"
        return url
