from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import re
from collections import deque
from dataclasses import dataclass
from threading import Event
from time import perf_counter

from agentic_app.config import Settings
from agentic_app.gemini_client import GeminiClient
from agentic_app.http import HttpClient
from agentic_app.models import ScrapedDocument, SearchCandidate, SearchTrace, ValidationResult
from agentic_app.scraper import CourtScraper
from agentic_app.search import CourtSearchService


INDIAN_KANOON_FINAL_PATTERN = re.compile(r"^https://indiankanoon\.org/doc/\d+/$")
SUPREME_COURT_PDF_FINAL_PATTERN = re.compile(r"^https://main\.sci\.gov\.in/.+\.pdf$")


@dataclass
class QueueNode:
    candidate: SearchCandidate
    depth: int
    parent_url: str
    path: list[str]


@dataclass
class NodeOutcome:
    node: QueueNode
    document: ScrapedDocument | None
    validation: ValidationResult | None
    error: str | None = None
    cancelled: bool = False


class CitationFinderAgent:
    def __init__(self, settings: Settings) -> None:
        http_client = HttpClient(
            timeout_seconds=settings.request_timeout_seconds,
            max_retries=settings.max_request_retries,
        )
        self.settings = settings
        self.search_service = CourtSearchService(http_client)
        self.scraper = CourtScraper(http_client, max_hyperlinks_per_page=settings.max_hyperlinks_per_page)
        self.gemini = GeminiClient(settings.gemini_api_key, settings.gemini_model, http_client)

    def run(self, case_description: str, trace: SearchTrace | None = None) -> dict:
        trace = trace or SearchTrace()
        run_started = perf_counter()
        trace.add("run_started", "Started citation finder run", metadata={"case_description": case_description})
        trace.add(
            "parallel_mode",
            "Configured concurrent scraping workers",
            metadata={"max_parallel_workers": self.settings.max_parallel_workers},
        )

        # The first line and Court: field drive the deterministic Indian Kanoon
        # query seed, which is usually more reliable than searching the whole note.
        parsed_case_name = self._extract_case_name(case_description)
        parsed_court = self._extract_court(case_description)
        primary_query = self._build_indian_kanoon_query(parsed_case_name, parsed_court)
        trace.add(
            "query_seed",
            "Built deterministic Indian Kanoon query from case name and court",
            query=primary_query,
            metadata={"case_name": parsed_case_name or "", "court": parsed_court or ""},
        )

        try:
            rewrite_started = perf_counter()
            search_queries = self.gemini.suggest_search_queries(case_description)
            if primary_query and primary_query not in search_queries:
                search_queries.insert(0, primary_query)
            trace.add(
                "query_rewrite",
                "Generated search queries with Gemini",
                metadata={
                    "queries": " | ".join(search_queries),
                    "elapsed_seconds": round(perf_counter() - rewrite_started, 2),
                },
            )
        except Exception as exc:
            search_queries = [primary_query] if primary_query else [case_description]
            trace.add(
                "query_rewrite_failed",
                "Falling back to the original case description as the only query",
                metadata={"error": str(exc), "elapsed_seconds": round(perf_counter() - run_started, 2)},
            )

        initial_candidates: list[SearchCandidate] = []
        seen_seed_urls: set[str] = set()
        for query in search_queries:
            raw_candidates = self.search_service.search_indian_kanoon(query, trace=trace)
            if query == primary_query and raw_candidates:
                # The user-provided pattern prioritizes the first filtered result.
                raw_candidates = [raw_candidates[0], *raw_candidates[1:]]

            for candidate in raw_candidates:
                resolved_candidate = self.search_service.resolve_candidate(candidate, trace=trace)
                if resolved_candidate.url in seen_seed_urls:
                    trace.add(
                        "seed_duplicate_skipped",
                        "Skipping duplicate seed candidate",
                        query=query,
                        url=resolved_candidate.url,
                        path=[resolved_candidate.url],
                    )
                    continue
                seen_seed_urls.add(resolved_candidate.url)
                initial_candidates.append(resolved_candidate)

        if not initial_candidates:
            trace.add("run_finished", "No search candidates were returned", metadata={"status": "not_found"})
            return self._result_not_found(trace, [])

        try:
            ranking_started = perf_counter()
            ranked_candidates = self.gemini.rank_candidates(case_description, initial_candidates)
            trace.add(
                "ranking_complete",
                "Ranked initial candidates with Gemini",
                metadata={
                    "candidate_count": len(ranked_candidates),
                    "elapsed_seconds": round(perf_counter() - ranking_started, 2),
                },
            )
        except Exception as exc:
            ranked_candidates = initial_candidates
            trace.add(
                "ranking_failed",
                "Gemini ranking failed; using search order",
                metadata={"error": str(exc), "candidate_count": len(ranked_candidates)},
            )

        queue: deque[QueueNode] = deque(
            QueueNode(candidate=candidate, depth=0, parent_url="", path=[candidate.url])
            for candidate in ranked_candidates
        )
        visited_urls: set[str] = set()
        queued_urls: set[str] = {candidate.url for candidate in ranked_candidates}
        attempts: list[dict] = []
        scheduled_count = 0
        stop_event = Event()
        matched_payload: tuple[str, ScrapedDocument, ValidationResult] | None = None
        executor = ThreadPoolExecutor(max_workers=self.settings.max_parallel_workers)
        in_flight: dict[Future[NodeOutcome], QueueNode] = {}

        try:
            while (queue or in_flight) and not stop_event.is_set():
                while (
                    queue
                    and len(in_flight) < self.settings.max_parallel_workers
                    and scheduled_count < self.settings.max_iterations
                    and not stop_event.is_set()
                ):
                    node = queue.popleft()
                    candidate = node.candidate
                    if candidate.url in visited_urls:
                        trace.add(
                            "visit_skipped",
                            "Skipping already visited URL",
                            url=candidate.url,
                            parent_url=node.parent_url,
                            depth=node.depth,
                            path=node.path,
                        )
                        continue

                    visited_urls.add(candidate.url)
                    scheduled_count += 1
                    trace.add(
                        "visit_started",
                        "Scheduled URL for parallel scrape and validation",
                        url=candidate.url,
                        parent_url=node.parent_url,
                        depth=node.depth,
                        path=node.path,
                        metadata={
                            "source": candidate.source,
                            "title": candidate.title,
                            "iteration": scheduled_count,
                            "in_flight_before_submit": len(in_flight),
                        },
                    )
                    future = executor.submit(self._process_node, case_description, node, trace, stop_event, run_started)
                    in_flight[future] = node

                if not in_flight:
                    break

                completed, _ = wait(in_flight.keys(), return_when=FIRST_COMPLETED)
                for future in completed:
                    node = in_flight.pop(future)
                    outcome = future.result()
                    attempts.append(
                        self._attempt(
                            outcome.node.candidate,
                            outcome.node,
                            outcome.document,
                            outcome.validation,
                            error=outcome.error,
                            cancelled=outcome.cancelled,
                        )
                    )

                    if outcome.cancelled:
                        trace.add(
                            "visit_cancelled",
                            "Worker stopped because another thread already found a confirmed match",
                            url=outcome.node.candidate.url,
                            parent_url=outcome.node.parent_url,
                            depth=outcome.node.depth,
                            path=outcome.node.path,
                        )
                        continue

                    if outcome.error:
                        continue

                    assert outcome.document is not None
                    assert outcome.validation is not None

                    if outcome.validation.is_match:
                        if self._is_valid_final_url(outcome.node.candidate.url):
                            stop_event.set()
                            matched_payload = (
                                outcome.node.candidate.url,
                                outcome.document,
                                outcome.validation,
                            )
                            trace.add(
                                "final_match_accepted",
                                "Accepted validated URL as final result and signalled other workers to stop",
                                url=outcome.node.candidate.url,
                                parent_url=outcome.node.parent_url,
                                depth=outcome.node.depth,
                                path=outcome.node.path,
                                metadata={
                                    "final_type": self._final_url_type(outcome.node.candidate.url),
                                    "run_elapsed_seconds": round(perf_counter() - run_started, 2),
                                },
                            )
                            for pending_future, pending_node in list(in_flight.items()):
                                if pending_future.cancel():
                                    trace.add(
                                        "visit_cancelled",
                                        "Cancelled queued worker after a confirmed match was found",
                                        url=pending_node.candidate.url,
                                        parent_url=pending_node.parent_url,
                                        depth=pending_node.depth,
                                        path=pending_node.path,
                                    )
                                    in_flight.pop(pending_future, None)
                            queue.clear()
                            break

                        trace.add(
                            "final_match_rejected",
                            "Validation succeeded but URL was rejected because it does not match the allowed final-link format",
                            url=outcome.node.candidate.url,
                            parent_url=outcome.node.parent_url,
                            depth=outcome.node.depth,
                            path=outcome.node.path,
                            metadata={"allowed_formats": "indiankanoon doc/<id>/ or main.sci.gov.in/*.pdf"},
                        )

                    for discovered in outcome.document.discovered_links:
                        if discovered.url in visited_urls or discovered.url in queued_urls:
                            trace.add(
                                "queue_duplicate_skipped",
                                "Skipped discovered link because it was already queued or visited",
                                url=discovered.url,
                                parent_url=outcome.node.candidate.url,
                                depth=outcome.node.depth + 1,
                                path=[*outcome.node.path, discovered.url],
                            )
                            continue

                        queued_urls.add(discovered.url)
                        next_depth = outcome.node.depth + 1
                        next_path = [*outcome.node.path, discovered.url]
                        trace.add(
                            "queue_add",
                            "Queued discovered link for later processing",
                            url=discovered.url,
                            parent_url=outcome.node.candidate.url,
                            depth=next_depth,
                            path=next_path,
                            metadata={"source": discovered.source, "title": discovered.title},
                        )
                        queue.append(
                            QueueNode(
                                candidate=discovered,
                                depth=next_depth,
                                parent_url=outcome.node.candidate.url,
                                path=next_path,
                            )
                        )
        finally:
            # Pending tasks are cancelled immediately; running requests will finish
            # in the background if the interpreter cannot interrupt them mid-IO.
            executor.shutdown(wait=False, cancel_futures=True)

        if matched_payload is not None:
            matched_url, document, validation = matched_payload
            trace.add(
                "run_finished",
                "Run completed with a validated final result",
                metadata={"status": "matched", "elapsed_seconds": round(perf_counter() - run_started, 2)},
            )
            return self._result_matched(matched_url, document, validation, attempts, trace)

        trace.add(
            "run_finished",
            "Run ended without a validated final link",
            metadata={
                "status": "not_found",
                "attempt_count": len(attempts),
                "visited_count": len(visited_urls),
                "elapsed_seconds": round(perf_counter() - run_started, 2),
            },
        )
        return self._result_not_found(trace, attempts)

    def _process_node(
        self,
        case_description: str,
        node: QueueNode,
        trace: SearchTrace,
        stop_event: Event,
        run_started: float,
    ) -> NodeOutcome:
        candidate = node.candidate
        if stop_event.is_set():
            return NodeOutcome(node=node, document=None, validation=None, cancelled=True)

        try:
            scrape_started = perf_counter()
            document = self.scraper.scrape(candidate.url, trace=trace)
            if stop_event.is_set():
                return NodeOutcome(node=node, document=document, validation=None, cancelled=True)
            trace.add(
                "scrape_complete",
                "Finished scraping document",
                url=candidate.url,
                depth=node.depth,
                path=node.path,
                metadata={
                    "content_type": document.content_type,
                    "title": document.title,
                    "discovered_links": len(document.discovered_links),
                    "elapsed_seconds": round(perf_counter() - scrape_started, 2),
                },
            )
            if stop_event.is_set():
                return NodeOutcome(node=node, document=document, validation=None, cancelled=True)

            validation_started = perf_counter()
            validation = self.gemini.validate_case_match(case_description, document)
            if validation.is_match and self._is_valid_final_url(candidate.url):
                # Let workers stop each other immediately instead of waiting for
                # the coordinator thread to observe the completed future.
                stop_event.set()
            trace.add(
                "validation_complete",
                "Validated scraped document against case description",
                url=candidate.url,
                depth=node.depth,
                path=node.path,
                metadata={
                    "is_match": validation.is_match,
                    "confidence": validation.confidence,
                    "case_name": validation.extracted_case_name or "unknown",
                    "elapsed_seconds": round(perf_counter() - validation_started, 2),
                },
            )
            if stop_event.is_set() and not (validation.is_match and self._is_valid_final_url(candidate.url)):
                return NodeOutcome(node=node, document=document, validation=None, cancelled=True)
            return NodeOutcome(node=node, document=document, validation=validation)
        except Exception as exc:
            trace.add(
                "visit_failed",
                "Failed while scraping or validating URL",
                url=candidate.url,
                parent_url=node.parent_url,
                depth=node.depth,
                path=node.path,
                metadata={"error": str(exc), "elapsed_seconds": round(perf_counter() - run_started, 2)},
            )
            return NodeOutcome(node=node, document=None, validation=None, error=str(exc))

    def _result_matched(
        self,
        matched_url: str,
        document: ScrapedDocument,
        validation: ValidationResult,
        attempts: list[dict],
        trace: SearchTrace,
    ) -> dict:
        return {
            "status": "matched",
            "matched_url": matched_url,
            "title": document.title,
            "validation": validation.__dict__,
            "indiankanoon_link": matched_url if self._is_indian_kanoon_final(matched_url) else None,
            "indian_court_link": matched_url if self._is_supreme_court_pdf_final(matched_url) else None,
            "attempts": attempts,
            "trace_events": trace.to_dict(),
            "trace_text": trace.to_pretty_text(),
        }

    def _result_not_found(self, trace: SearchTrace, attempts: list[dict]) -> dict:
        return {
            "status": "not_found",
            "matched_url": None,
            "indiankanoon_link": None,
            "indian_court_link": None,
            "attempts": attempts,
            "trace_events": trace.to_dict(),
            "trace_text": trace.to_pretty_text(),
            "message": "No validated case link was found within the configured search depth.",
        }

    def _attempt(
        self,
        candidate: SearchCandidate,
        node: QueueNode,
        document: ScrapedDocument | None,
        validation: ValidationResult | None,
        error: str | None = None,
        cancelled: bool = False,
    ) -> dict:
        return {
            "candidate_title": candidate.title,
            "candidate_url": candidate.url,
            "source": candidate.source,
            "depth": node.depth,
            "parent_url": node.parent_url,
            "path": node.path,
            "scraped_title": document.title if document else None,
            "content_type": document.content_type if document else None,
            "validation": validation.__dict__ if validation else None,
            "error": error,
            "cancelled": cancelled,
        }

    def _is_valid_final_url(self, url: str) -> bool:
        return self._is_indian_kanoon_final(url) or self._is_supreme_court_pdf_final(url)

    def _is_indian_kanoon_final(self, url: str) -> bool:
        return bool(INDIAN_KANOON_FINAL_PATTERN.match(url))

    def _is_supreme_court_pdf_final(self, url: str) -> bool:
        return bool(SUPREME_COURT_PDF_FINAL_PATTERN.match(url))

    def _final_url_type(self, url: str) -> str:
        if self._is_indian_kanoon_final(url):
            return "indiankanoon_doc"
        if self._is_supreme_court_pdf_final(url):
            return "supreme_court_pdf"
        return "invalid"

    def _extract_case_name(self, case_description: str) -> str:
        lines = [line.strip() for line in case_description.splitlines() if line.strip()]
        if lines:
            return lines[0]
        return case_description.strip()

    def _extract_court(self, case_description: str) -> str:
        match = re.search(r"Court:\s*(.+)", case_description, re.IGNORECASE)
        return match.group(1).strip() if match else ""

    def _build_indian_kanoon_query(self, case_name: str, court: str) -> str:
        case_name = case_name.strip()
        court_filter = self._court_to_doctype(court)
        if case_name and court_filter:
            return f"{case_name} doctypes: {court_filter}"
        return case_name

    def _court_to_doctype(self, court: str) -> str:
        # This maps human court names to the doctypes token Indian Kanoon expects.
        normalized = court.strip().lower()
        mapping = {
            "supreme court of india": "supremecourt",
            "supreme court": "supremecourt",
            "delhi high court": "delhihc",
            "allahabad high court": "allahabadhc",
            "bombay high court": "bombayhc",
            "calcutta high court": "calcuttahc",
            "madras high court": "madrashc",
            "punjab and haryana high court": "punjabharyana",
            "punjab & haryana high court": "punjabharyana",
        }
        return mapping.get(normalized, "")
