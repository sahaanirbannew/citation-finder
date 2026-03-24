# Citation Finder

Citation Finder is a FastAPI application that takes a text description of an Indian case, searches for the most likely judgment, scrapes the linked material, validates the match with Gemini, and returns only approved final links.

It uses the **Google Agent Development Kit (ADK)** to orchestrate a central **Citation Agent** (`LlmAgent`). 
This agent uses various tools (like `search_indian_kanoon`, `search_google`, `resolve_fragment_and_scrape`, and `validate_match`) to dynamically plan and find the most accurate case link.

It is built for Indian legal sources, with a debug-oriented UI that shows live progress, elapsed time, and the exact intermediate steps happening inside the ADK agent.

## What It Does

1. Accepts a free-form case note or citation block.
2. An ADK `LlmAgent` is invoked in an `InMemorySessionService`.
3. The agent formulates search queries.
4. The agent uses tools to query Indian Kanoon or fallback to Google/SerpAPI.
5. The agent uses tools to fetch and scrape html/pdf judgment text.
6. The agent validates the text with a validation tool.
7. Output terminates when a positive signal is given and the agent completes its run.

### Example

**Input:**
```text
State of Haryana v. Bhajan Lal
Court: Supreme Court of India
Description: Laid down illustrative guidelines for quashing of FIR/criminal proceedings under Section 482 Cr.P.C. or Article 226 of the Constitution. Clause 7 states that where a criminal proceeding is manifestly attended with malafide and/or where the proceeding is maliciously instituted with an ulterior motive for wreaking vengeance on the accused, such proceedings can be quashed.
Why cited: To argue that the criminal proceedings are an abuse of the process of law, initiated with an ulterior motive to harass the applicants in a civil land dispute. This supports the claim that the entire prosecution story is 'afterthought, concocted and fabricated'.
```

**Outcome:** 
The Citation Agent dynamically refines this free-form description into search queries. It evaluates candidate results against the text's emphasis on "quashing of FIR", "Article 226", and "Clause 7". Upon retrieving the correct text containing these exact criteria, the agent marks the search completely successful and returns the official Indian Kanoon or Supreme Court judgment link!

## Stack

- FastAPI
- Vanilla JavaScript (for polling)
- Python `google-adk` framework
- Gemini API (`google-genai`)
- SerpAPI (for Google Search)
- `pypdf`, `BeautifulSoup`

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install google-adk
```

Ensure API keys are configured in your `.env` file:

```env
GEMINI_API_KEY="your-gemini-key"
SERPAPI_KEY="your-srpapi-key"
```

## Run

```bash
source .venv/bin/activate
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## API

`POST /api/find`
Starts an asynchronous ADK session for the agent. Returns a `job_id`.

`GET /api/find/{job_id}`
Retrieves session updates from the ADK's `InMemorySessionService`, parsing out logs and checking for the final model `OutputSchema` (`CitationResult`).

### Programmatic Synchronous Search (`POST /search`)

Instead of asynchronous processing, external software or API clients can use this direct, fully synchronous endpoint. It holds the HTTP connection open until the Google ADK LLM finishes fetching and comprehensively evaluating citations.

**Example Request (`POST /search`):**
```json
{
  "input_text": "State of Haryana v. Bhajan Lal, Guidelines for quashing FIR"
}
```

**Example Successful Response (HTTP 200):**
```json
{
  "status": "success",
  "citation_link": "https://indiankanoon.org/doc/1033637/",
  "rationale": "Matches perfectly as it lays down illustrative guidelines for quashing..."
}
```

**Example Unsuccessful Response (HTTP 200):**
_(If the ADK Agent exhausts all options without finding a valid match)_
```json
{
  "status": "not_found",
  "message": "Could not find a matching citation."
}
```

**Example Error Response (HTTP 400 or HTTP 500):**
_(If the input is blank or the backend crashes)_
```json
{
  "error": "input_text is required."
}
```

**Python Usage Example:**
```python
import requests

url = "http://127.0.0.1:8000/search"
payload = {
    "input_text": "State of Haryana v. Bhajan Lal, Guidelines for quashing FIR"
}

response = requests.post(url, json=payload)
print(response.json())
```
