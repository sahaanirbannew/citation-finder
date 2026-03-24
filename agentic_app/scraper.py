from __future__ import annotations

from io import BytesIO
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from pypdf import PdfReader

from agentic_app.http import HttpClient
from agentic_app.models import ScrapedDocument, SearchCandidate, SearchTrace


ALLOWED_DOMAINS = (
    "indiankanoon.org",
    "main.sci.gov.in",
    "sci.gov.in",
    "supremecourtofindia.nic.in",
    ".ecourts.gov.in",
    ".hc.nic.in",
)


class CourtScraper:
    def __init__(self, http_client: HttpClient, max_hyperlinks_per_page: int) -> None:
        self.http_client = http_client
        self.max_hyperlinks_per_page = max_hyperlinks_per_page

    def scrape(self, url: str, *, trace: SearchTrace | None = None) -> ScrapedDocument:
        if trace:
            trace.add("scrape_request", "Fetching URL for scraping", url=url)
        response = self.http_client.get(url)

        content_type = response.headers.get("content-type", "").lower()
        if url.lower().endswith(".pdf") or "application/pdf" in content_type:
            if trace:
                trace.add("scrape_pdf", "Scraping PDF document", url=url)
            return self._scrape_pdf(response.content, url)

        if trace:
            trace.add(
                "scrape_html",
                "Scraping HTML document",
                url=url,
                metadata={"content_type": content_type or "unknown"},
            )
        soup = BeautifulSoup(response.text, "html.parser")
        title = self._extract_title(soup)
        text = self._extract_text(soup)
        links = self._extract_links(soup, url, trace=trace)
        return ScrapedDocument(
            url=url,
            title=title,
            text=text,
            source=self._domain(url),
            content_type="html",
            discovered_links=links,
        )

    def _scrape_pdf(self, pdf_bytes: bytes, url: str) -> ScrapedDocument:
        reader = PdfReader(BytesIO(pdf_bytes))
        pages = []
        for page in reader.pages:
            pages.append((page.extract_text() or "").strip())
        text = " ".join(part for part in pages if part)
        title = url.rstrip("/").split("/")[-1] or "Supreme Court PDF"
        return ScrapedDocument(
            url=url,
            title=title,
            text=" ".join(text.split())[:25000],
            source=self._domain(url),
            content_type="pdf",
            discovered_links=[],
        )

    def _extract_title(self, soup: BeautifulSoup) -> str:
        selectors = ["h2.docsource_main", "div.doc_title", "title", "h1", "h2"]
        for selector in selectors:
            node = soup.select_one(selector)
            if node:
                return node.get_text(" ", strip=True)
        return "Untitled Document"

    def _extract_text(self, soup: BeautifulSoup) -> str:
        selectors = [
            "div.judgments",
            "pre",
            "div#pre_1",
            "div.doc",
            "div.content",
            "body",
        ]
        for selector in selectors:
            node = soup.select_one(selector)
            if node:
                return " ".join(node.get_text(" ", strip=True).split())[:25000]
        return ""

    def _extract_links(
        self,
        soup: BeautifulSoup,
        base_url: str,
        *,
        trace: SearchTrace | None = None,
    ) -> list[SearchCandidate]:
        links: list[SearchCandidate] = []
        seen: set[str] = set()
        base_domain = self._domain(base_url)

        for anchor in soup.select("a[href]"):
            href = urljoin(base_url, anchor.get("href", ""))
            if not self._is_allowed_domain(href):
                continue
            if "#" in href:
                continue
            if base_domain.endswith("indiankanoon.org") and self._domain(href).endswith("indiankanoon.org"):
                if "/doc/" not in href:
                    continue
            if href in seen:
                continue
            seen.add(href)
            title = anchor.get_text(" ", strip=True) or href
            candidate = SearchCandidate(
                title=title,
                url=href,
                source=f"Hyperlink from {self._domain(base_url)}",
            )
            links.append(candidate)
            if trace:
                trace.add(
                    "discovered_link",
                    "Discovered hyperlink while scraping page",
                    url=href,
                    parent_url=base_url,
                    metadata={"title": title},
                )
            if len(links) >= self.max_hyperlinks_per_page:
                break
        return links

    def _is_allowed_domain(self, url: str) -> bool:
        domain = self._domain(url)
        return any(domain == allowed or domain.endswith(allowed) for allowed in ALLOWED_DOMAINS)

    def _domain(self, url: str) -> str:
        return urlparse(url).netloc.lower()
