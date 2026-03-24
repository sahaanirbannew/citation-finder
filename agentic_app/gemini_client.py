from __future__ import annotations

import json

from tenacity import retry, stop_after_attempt, wait_exponential

from agentic_app.http import HttpClient
from agentic_app.models import SearchCandidate, ScrapedDocument, ValidationResult


class GeminiClient:
    def __init__(self, api_key: str, model: str, http_client: HttpClient) -> None:
        self.api_key = api_key
        self.model = model
        self.http_client = http_client

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3))
    def suggest_search_queries(self, case_description: str) -> list[str]:
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                "You are rewriting a legal case search query for Indian Kanoon.\n"
                                "Return only JSON with key search_queries containing up to 4 concise queries.\n"
                                "Prefer the likely case name, party names, year, court, and a short issue phrase.\n"
                                "Do not invent facts. Include the user's original wording as one option.\n\n"
                                f"Case description:\n{case_description}"
                            )
                        }
                    ]
                }
            ],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        data = self._generate(payload)
        queries = [str(query).strip() for query in data.get("search_queries", []) if str(query).strip()]
        if case_description not in queries:
            queries.insert(0, case_description)
        return queries[:4]

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3))
    def rank_candidates(
        self,
        case_description: str,
        candidates: list[SearchCandidate],
    ) -> list[SearchCandidate]:
        if len(candidates) <= 1:
            return candidates

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                "You are ranking legal search results.\n"
                                "Return only JSON with key ordered_urls as a list of URLs from best to worst.\n\n"
                                "Prefer the primary case directly matching the description. "
                                "Do not prioritize later cases that merely cite, discuss, or apply the target case unless "
                                "the description clearly points to those later cases.\n\n"
                                f"Case description:\n{case_description}\n\n"
                                "Candidates:\n"
                                + "\n".join(
                                    f"- title: {candidate.title}\n  url: {candidate.url}\n  snippet: {candidate.snippet}"
                                    for candidate in candidates
                                )
                            )
                        }
                    ]
                }
            ],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        data = self._generate(payload)
        ordered_urls = data.get("ordered_urls", [])
        ordering = {url: index for index, url in enumerate(ordered_urls)}
        return sorted(candidates, key=lambda item: ordering.get(item.url, len(candidates)))

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3))
    def validate_case_match(
        self,
        case_description: str,
        document: ScrapedDocument,
    ) -> ValidationResult:
        truncated_text = document.text[:12000]
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                "You are validating whether a scraped Indian court judgment matches a user description.\n"
                                "Return only JSON with keys: is_match, confidence, rationale, extracted_case_name, "
                                "extracted_court, extracted_date.\n\n"
                                "Mark is_match as true only when the scraped judgment itself is the target case described "
                                "by the user. A judgment that merely cites, summarizes, distinguishes, or applies the "
                                "target case must be marked false unless the user explicitly asked for that later case.\n\n"
                                f"User description:\n{case_description}\n\n"
                                f"Document title:\n{document.title}\n\n"
                                f"Document URL:\n{document.url}\n\n"
                                f"Document text excerpt:\n{truncated_text}"
                            )
                        }
                    ]
                }
            ],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        data = self._generate(payload)
        return ValidationResult.from_payload(data)

    def _generate(self, payload: dict) -> dict:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            f"?key={self.api_key}"
        )
        response = self.http_client.session.post(url, json=payload, timeout=self.http_client.timeout_seconds)
        response.raise_for_status()
        body = response.json()
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(self._extract_json_text(text))

    def _extract_json_text(self, text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if len(lines) >= 3:
                cleaned = "\n".join(lines[1:-1]).strip()
        return cleaned
