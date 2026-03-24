# Citation Finder

Citation Finder is a FastAPI application that takes a text description of an Indian case, searches for the most likely judgment, scrapes the linked material, validates the match with Gemini, and returns only approved final links.

It is built for Indian Kanoon and Indian court sources, with a debug-oriented UI that shows live progress, elapsed time, and the exact links being scraped.

## What It Does

1. Accepts a free-form case note or citation block.
2. Extracts the case name from the first line.
3. Extracts the court from the `Court:` field when available.
4. Builds an Indian Kanoon query using `doctypes:` filtering when possible.
5. Searches Indian Kanoon.
6. Opens Indian Kanoon `docfragment` results and resolves them to full `/doc/<id>/` judgment links.
7. Scrapes HTML judgments and Supreme Court PDF judgments.
8. Validates the scraped content against the user’s description with Gemini.
9. Returns the first validated final link and stops the remaining search as early as possible.

## Final Link Rules

The app only returns a result if it matches one of these formats:

- Indian Kanoon: `https://indiankanoon.org/doc/<unique_id>/`
- Supreme Court PDF: `https://main.sci.gov.in/<folder/page/...>.pdf`

Anything else may be visited during the crawl, but it will not be returned as the final answer.

## Current Search Logic

The retrieval logic is intentionally opinionated.

If the input looks like:

```text
State of Haryana v. Bhajan Lal
Court: Supreme Court of India
Description: ...
Why cited: ...
```

the app first builds this kind of Indian Kanoon query:

```text
State of Haryana v. Bhajan Lal doctypes: supremecourt
```

Then it:

1. searches Indian Kanoon
2. takes the first filtered result seriously
3. opens a `docfragment` page if needed
4. extracts the linked full `/doc/<id>/` judgment page
5. scrapes and validates that full page

## Live UI Features

The UI includes:

- a large case-description input box
- a result panel with Indian Kanoon and Indian Court links
- a live activity indicator
- an elapsed-time display
- a log panel that shows only the links currently being scraped

## Parallel Processing

The crawler uses parallel workers for scraping and validation.

- Multiple candidate URLs can be processed at the same time.
- As soon as one valid final match is confirmed, the app signals the rest of the crawl to stop.
- Pending work is cancelled where possible.
- Requests already in the middle of network I/O may still finish, because Python cannot instantly terminate an in-flight socket call safely.

## Stack

- FastAPI
- Jinja2 templates
- Vanilla JavaScript
- Requests
- BeautifulSoup
- `pypdf`
- Gemini API

## Project Structure

```text
.
├── .env
├── .gitignore
├── README.md
├── DOCUMENTATION.md
├── main.py
├── requirements.txt
├── static
│   ├── script.js
│   └── style.css
├── templates
│   └── index.html
└── agentic_app
    ├── __init__.py
    ├── config.py
    ├── gemini_client.py
    ├── http.py
    ├── job_manager.py
    ├── models.py
    ├── orchestrator.py
    ├── scraper.py
    └── search.py
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The Gemini API key is stored in `.env`. Keep that file private.

## Run

```bash
cd "/Users/anirbansaha/Documents/citation finder"
source .venv/bin/activate
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## API

### Start a job

`POST /api/find`

Request body:

```json
{
  "case_description": "State of Haryana v. Bhajan Lal\nCourt: Supreme Court of India\nDescription: ..."
}
```

Response:

```json
{
  "status": "accepted",
  "job_id": "uuid",
  "case_description": "..."
}
```

### Poll job status

`GET /api/find/{job_id}`

Important fields in the response:

- `status`
- `elapsed_seconds`
- `result`
- `scrape_log_text`
- `trace_events`

## Notes

- The visible log panel now shows only scrape links, not the entire internal trace.
- The backend still keeps full structured trace events for debugging and future extension.
- Supreme Court PDFs from `main.sci.gov.in` are parsed before validation.
- Retry count for HTTP fetches is capped at `2`.
