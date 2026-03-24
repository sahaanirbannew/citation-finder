# Technical Documentation

## Overview

This project is a FastAPI-based legal citation finder for Indian case law.

The system is designed to:

1. identify the likely judgment from a descriptive case note
2. retrieve the actual judgment link
3. scrape the source content
4. validate the match against the user input
5. stop quickly once a valid final match is found

## High-Level Flow

1. The browser submits a case description to `POST /api/find`.
2. The server creates a background job and returns immediately with a `job_id`.
3. The browser polls `GET /api/find/{job_id}` once per second.
4. The background job runs the citation-finding agent.
5. The UI shows elapsed time, activity state, final links, and scrape-only logs.

## Retrieval Strategy

### Input parsing

The orchestrator extracts:

- case name from the first non-empty line
- court from a `Court:` field if present

Example:

```text
State of Haryana v. Bhajan Lal
Court: Supreme Court of India
Description: ...
```

becomes a seeded Indian Kanoon query like:

```text
State of Haryana v. Bhajan Lal doctypes: supremecourt
```

### Indian Kanoon search

The search layer calls:

```text
https://indiankanoon.org/search/?formInput=<query>
```

When the court is known, it adds the appropriate `doctypes:` token.

### Fragment resolution

Indian Kanoon often returns `docfragment` pages in search results.

Those fragment pages are not treated as final results directly. Instead, the search layer opens the fragment page and finds the linked full judgment URL:

```text
https://indiankanoon.org/doc/<id>/
```

This mirrors the intended workflow:

1. search
2. open the first result fragment
3. resolve the full judgment link
4. scrape the full judgment
5. validate it

## Final Link Enforcement

The system accepts only two final URL shapes:

### Indian Kanoon

```text
https://indiankanoon.org/doc/<unique_id>/
```

### Supreme Court PDF

```text
https://main.sci.gov.in/<folder/page/...>.pdf
```

If validation succeeds but the URL does not match one of these patterns, the result is rejected.

## Scraping

### HTML

For HTML pages, the scraper tries several likely legal-document selectors and falls back to `body`.

### PDF

For `main.sci.gov.in` PDF links, the scraper uses `pypdf` to extract text before validation.

### Hyperlink discovery

While scraping HTML pages, the system discovers additional legal-domain links and queues them as follow-up candidates.

## Parallel Processing

The orchestrator uses a thread pool for concurrent scraping and validation.

### Why

Court sites and Indian Kanoon can be slow. Sequential fetching wastes time when multiple promising links are available.

### How it works

- A bounded number of workers process candidate URLs in parallel.
- Each worker scrapes and validates one URL.
- The shared trace continues recording progress across all workers.
- The queue grows as workers discover additional links.

### Early stop

As soon as a worker confirms a valid final link:

- a shared stop signal is set
- pending worker tasks are cancelled if they have not started yet
- the coordinator stops scheduling new work
- the run returns the confirmed result as soon as possible

Important limitation:

Requests already in active network I/O cannot be forcibly terminated safely in Python. Those may finish in the background, but their results are ignored once a winner is chosen.

## Logging Model

The backend keeps a full structured trace using `SearchTrace`.

Each event records:

- index
- timestamp
- event type
- message
- URL
- query
- parent URL
- depth
- path
- metadata

Examples of event types:

- `run_started`
- `query_seed`
- `query_rewrite`
- `search_request`
- `search_result_found`
- `fragment_open`
- `fragment_resolved`
- `visit_started`
- `scrape_request`
- `scrape_complete`
- `validation_complete`
- `final_match_accepted`
- `visit_failed`
- `run_finished`

### What the UI shows

The browser does not show the full trace.

The visible log panel shows only scrape URLs, derived from `scrape_request` events.

This keeps the live log readable while preserving richer debugging data on the backend.

## Job System

The job manager runs each citation search in a background daemon thread.

Each job tracks:

- `job_id`
- `status`
- `created_at`
- `updated_at`
- `elapsed_seconds`
- `result`
- `error`
- `trace`

This design lets the API stay responsive while the crawl runs.

## Timing

Timing is tracked at several levels:

- total job elapsed time
- query rewrite duration
- ranking duration
- scrape duration
- validation duration
- total run duration

The UI displays the live job elapsed time.

## Retry Behavior

HTTP requests use a shared retry policy with:

- `max_request_retries = 2`

This applies to fetches against Indian Kanoon and court websites.

## Main Files

- `main.py`: FastAPI app and API routes
- `agentic_app/job_manager.py`: background job lifecycle
- `agentic_app/orchestrator.py`: crawl orchestration, concurrency, early-stop behavior
- `agentic_app/search.py`: Indian Kanoon querying and fragment resolution
- `agentic_app/scraper.py`: HTML/PDF scraping and link discovery
- `agentic_app/gemini_client.py`: Gemini query rewrite, ranking, and validation
- `agentic_app/models.py`: trace and result data structures
- `templates/index.html`: UI markup
- `static/script.js`: polling logic and live updates
- `static/style.css`: UI styling

## Local Verification

Useful local checks:

```bash
PYTHONPYCACHEPREFIX=.pycache python3 -m py_compile main.py agentic_app/*.py
```

Run the app with:

```bash
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

## Known Limitations

- Search quality still depends on Indian Kanoon’s result quality.
- Court name to `doctypes:` mapping is incomplete and currently heuristic.
- Some court pages may change structure without warning.
- Extremely slow network requests cannot be killed instantly once already in progress.

## Suggested Next Improvements

1. Expand court-to-doctype coverage for more High Courts.
2. Add persistent job history storage.
3. Add fixture-based tests for fragment resolution and early-stop behavior.
4. Add a direct official-court fallback search path when Indian Kanoon misses the case.
