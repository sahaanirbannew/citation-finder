"""
agentic_app/adk_tools.py
Program Purpose: Defines tools that wrap underlying services (Search, Scrape, Gemini) for the ADK LLM agent.
Input: Strings representing queries, URLs, and case descriptions originating from the LLM agent.
Output: JSON-formatted strings containing parsed results, extracted text, or validation statuses to be fed back to the LLM.
"""
import json
from typing import Optional
import logging

from agentic_app.config import Settings
from agentic_app.http import HttpClient
from agentic_app.search import CourtSearchService
from agentic_app.scraper import CourtScraper
from agentic_app.gemini_client import GeminiClient
from agentic_app.models import SearchCandidate

logger = logging.getLogger(__name__)

# Initialize shared services
try:
    settings = Settings.from_env()
    shared_http_client = HttpClient(
        timeout_seconds=settings.request_timeout_seconds,
        max_retries=settings.max_request_retries,
    )
    search_service = CourtSearchService(shared_http_client)
    scraper = CourtScraper(shared_http_client, max_hyperlinks_per_page=settings.max_hyperlinks_per_page)
    gemini = GeminiClient(settings.gemini_api_key, settings.gemini_model, shared_http_client)
except Exception as e:
    logger.error(f"Failed to aggressively initialize shared services: {e}")
    raise


def suggest_search_queries(case_description: str) -> str:
    """Generate search queries for Indian Kanoon based on a user's case description.
    Returns a JSON string containing a list of search queries.
    """
    try:
        queries = gemini.suggest_search_queries(case_description)
        return json.dumps(queries)
    except Exception as e:
        logger.error(f"Error in suggest_search_queries: {e}")
        return json.dumps({"error": str(e)})


def search_indian_kanoon(query: str) -> str:
    """Search Indian Kanoon for legal cases using the provided query.
    Returns a JSON string of candidate URLs, titles, and snippets.
    """
    try:
        candidates = search_service.search_indian_kanoon(query, limit=5)
        return json.dumps([{"title": c.title, "url": c.url, "snippet": c.snippet} for c in candidates])
    except Exception as e:
        logger.error(f"Error in search_indian_kanoon: {e}")
        return json.dumps({"error": str(e)})


def search_google(query: str) -> str:
    """Search Google (via SerpAPI) for legal cases. Use this if Indian Kanoon search fails or if you need broader results.
    Returns a JSON string of candidate URLs, titles, and snippets.
    """
    try:
        response = shared_http_client.get(
            "https://serpapi.com/search",
            params={
                "engine": "google",
                "q": query,
                "num": "5",
                "api_key": settings.serpapi_key,
                "hl": "en",
            },
        )
        body = response.json()
        organic_results = body.get("organic_results", [])
        results = []
        for result in organic_results:
            link = str(result.get("link", "")).strip()
            title = str(result.get("title", "")).strip()
            if not link:
                continue
            results.append({
                "title": title or link,
                "url": link,
                "snippet": str(result.get("snippet", "")).strip()
            })
        return json.dumps(results)
    except Exception as e:
        logger.error(f"Error in search_google: {e}")
        return json.dumps({"error": str(e)})


def resolve_fragment_and_scrape(url: str) -> str:
    """Takes a URL (especially an Indian Kanoon docfragment URL or direct judgment URL) and scrapes the content.
    Returns a JSON string with the page's url, title, and text content (truncated).
    """
    try:
        candidate = SearchCandidate(title="Unknown", url=url, source="LLM Input")
        resolved = search_service.resolve_candidate(candidate)
        document = scraper.scrape(resolved.url)
        return json.dumps({
            "url": document.url,
            "title": document.title,
            "text": document.text[:12000]
        })
    except Exception as e:
        logger.error(f"Error in resolve_fragment_and_scrape: {e}")
        return json.dumps({"error": str(e)})


def validate_match(case_description: str, page_text: str, document_url: str, document_title: str) -> str:
    """Validates whether a scraped judgment text matches the user's requested case description.
    Returns a JSON string indicating if it is a match, confidence, and rationale.
    """
    try:
        from agentic_app.models import ScrapedDocument
        doc = ScrapedDocument(
            url=document_url,
            title=document_title,
            text=page_text,
            source="LLM Provided",
            content_type="text",
            discovered_links=[]
        )
        validation = gemini.validate_case_match(case_description, doc)
        return json.dumps(validation.__dict__)
    except Exception as e:
        logger.error(f"Error in validate_match: {e}")
        return json.dumps({"error": str(e)})


def bulk_scrape_and_validate(case_description: str, urls: list[str]) -> str:
    """Concurrently scrapes and validates a list of URLs against the case description.
    Uses multi-threading to process all URLs in parallel for maximum speed.
    Returns a JSON string containing the validation results mapped to each URL.
    """
    import concurrent.futures
    try:
        def process_url(url: str):
            try:
                candidate = SearchCandidate(title="Unknown", url=url, source="Bulk Tool")
                resolved = search_service.resolve_candidate(candidate)
                doc = scraper.scrape(resolved.url)
                validation = gemini.validate_case_match(case_description, doc)
                result = validation.__dict__.copy()
                result["scraped_url"] = doc.url
                result["original_url"] = url
                return result
            except Exception as e:
                return {"original_url": url, "error": str(e), "is_match": False}

        results = []
        if not urls:
            return "[]"
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(urls))) as executor:
            future_to_url = {executor.submit(process_url, url): url for url in urls}
            for future in concurrent.futures.as_completed(future_to_url):
                results.append(future.result())
        return json.dumps(results)
    except Exception as e:
        logger.error(f"Error in bulk_scrape_and_validate: {e}")
        return json.dumps({"error": str(e)})


def get_all_tools() -> list:
    return [
        suggest_search_queries,
        search_indian_kanoon,
        search_google,
        resolve_fragment_and_scrape,
        validate_match,
        bulk_scrape_and_validate
    ]
