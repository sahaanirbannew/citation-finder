"""
agentic_app/adk_agents.py
Program Purpose: Factory for creating the core ADK Citation Agent. Defines model, tools, and the behavior instruction.
Input: None directly, reads environment configuration during parsing.
Output: Returns an initialized `google.adk.Agent` instance ready for execution.
"""
from google.adk import Agent
from agentic_app.config import Settings
from agentic_app.adk_tools import get_all_tools
import pydantic
import logging

logger = logging.getLogger(__name__)

try:
    settings = Settings.from_env()
except Exception as e:
    logger.error(f"Failed to load settings in adk_agents: {e}")
    raise

class CitationResult(pydantic.BaseModel):
    is_success: bool
    final_url: str = ""
    title: str = ""
    rationale: str = ""
    search_path_taken: str = ""

INSTRUCTION = """You are an expert legal citation finder for Indian case law.
Your goal is to find the exact official judgment link containing the case described by the user.

Workflow:
1. The user provides a case description.
2. Formulate 1-2 search queries. Try `search_indian_kanoon` first. If results are poor, fallback to `search_google`.
3. Extract the URLs from the search results and pass ALL of them simultaneously into `bulk_scrape_and_validate(case_description, urls)`. This executes in parallel and is much faster.
4. Review the bulk validation results. If any result has `is_match=True`, YOU MUST STOP and return the CitationResult with is_success=True, and the final_url (use the `scraped_url`).
5. If no matches are found, try another query and repeat.
6. If after a few tries you find no match, return CitationResult with is_success=False.

Return ONLY the structured output schema once you have a result.
"""

def create_citation_agent() -> Agent:
    """
    Creates and returns the citation tracking ADK Agent.
    """
    try:
        return Agent(
            name="citation_agent",
            model=settings.gemini_model,
            instruction=INSTRUCTION,
            tools=get_all_tools(),
            output_schema=CitationResult
        )
    except Exception as e:
        logger.error(f"Error creating citation agent: {e}")
        raise
