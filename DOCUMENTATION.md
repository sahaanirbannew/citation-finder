# Technical Documentation

## Overview

This project is a FastAPI-based legal citation finder for Indian case law.

It has been completely refactored to use the **Google Agent Development Kit (ADK)** for agentic orchestration. The `Citation Agent` leverages LLM capabilities with a robust set of tools.

The system is designed to:

1. Use an LLM agent to figure out exact queries based on user description.
2. Query Indian Kanoon and Google simultaneously or sequentially via tools.
3. Resolve fragment URLs and scrape final judgments.
4. Validate the match.
5. Stop quickly once a valid final match is found and return the schema.

## High-Level Flow

1. The browser submits a case description to `POST /api/find`.
2. The server initializes a new ADK `session` via `InMemorySessionService`.
3. The server spins up an asyncio background task calling `runner.run_async()`.
4. The server returns a `job_id` (the ADK `session_id`).
5. The browser polls `GET /api/find/{job_id}` once per second.
6. The `GET` endpoint parses `session.events` to stream intermediate logs (tool calls and responses) and checks for the final `CitationResult` schema output from the model.

## Agent Strategy

The entire orchestration happens within the `LlmAgent` defined in `agentic_app/adk_agents.py`.

### Toolset (`agentic_app/adk_tools.py`)
- `suggest_search_queries`: Asks a lightweight LLM call for targeted keywords.
- `search_indian_kanoon`: Queries Indian Kanoon with 5 results limit.
- `search_google`: A SerpApi fallback for Google searches.
- `resolve_fragment_and_scrape`: Reaches the exact document ignoring Kanoon fragments and returns a 12,000-character excerpt.
- `validate_match`: Ensures the scraped text mentions the actual case requested.

### Model Instructions
The model is instructed to sequence these tools effectively:
- Query Kanoon -> Scrape best candidates -> Validate.
- Fallback to Google if needed.
- Halt and return the struct `CitationResult(is_success, final_url, title, rationale)` when finished.

## Main Files

- `main.py`: FastAPI app, API routes, ADK Runner creation
- `agentic_app/config.py`: Configuration strings (Gemini, SerpAPI)
- `agentic_app/adk_agents.py`: ADK Agent initialization and Instruction definition
- `agentic_app/adk_tools.py`: Wrappers bridging pure Python functions as ADK Tools
- `agentic_app/search.py`: Underlying requests to Indian Kanoon
- `agentic_app/scraper.py`: Extracts titles and text (HTML and PDF)
- `agentic_app/gemini_client.py`: Raw Gemini client API logic
- `templates/index.html`: UI markup
- `static/script.js`: UI logic polling `session.events`
- `static/style.css`: UI styling

## Local Verification

Run the app with:

```bash
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

## Known Limitations

- Parallel network I/O optimization from previous version is delegated to the LLM agent now. Speed depends on how sequentially or concurrently the LLM decides to emit tools.
- Indian Kanoon search structure can change, breaking the fragment resolver.
