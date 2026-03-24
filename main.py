"""
main.py
Program Purpose: FastAPI application entry point. Initializes the Google ADK Runner and exposes API endpoints for finding legal citations.
Input: HTTP GET and POST requests from the browser, containing case descriptions.
Output: HTML pages and JSON responses containing background job status and final scraped links.
"""
import os
import asyncio
from pathlib import Path

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google.genai import types

from agentic_app.config import Settings
from agentic_app.adk_agents import create_citation_agent
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService

os.environ["GEMINI_API_KEY"] = Settings.from_env().gemini_api_key

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Citation Finder")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Set up ADK Runner
session_service = InMemorySessionService()
agent = create_citation_agent()
runner = Runner(
    app_name="citation_finder",
    agent=agent,
    session_service=session_service
)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/gsearch", response_class=HTMLResponse)
async def gsearch_page(request: Request) -> HTMLResponse:
    # GSearch is now seamlessly integrated into the main flow, 
    # but we can keep the template returning fine.
    return templates.TemplateResponse("gsearch.html", {"request": request})

async def run_agent_in_background(session_id: str, case_description: str):
    try:
        await session_service.create_session(
            app_name="citation_finder",
            user_id="default_user",
            session_id=session_id
        )
        async for _ in runner.run_async(
            user_id="default_user",
            session_id=session_id,
            new_message=types.Content(role="user", parts=[types.Part(text=case_description)])
        ):
            pass
    except Exception as e:
        print(f"Error executing agent in background: {e}")

@app.post("/api/find")
async def start_citation_job(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    import uuid
    payload = await request.json()
    case_description = str(payload.get("case_description", "")).strip()
    if not case_description:
        return JSONResponse(status_code=400, content={"status": "error", "message": "case_description is required."})
    
    session_id = str(uuid.uuid4())
    background_tasks.add_task(run_agent_in_background, session_id, case_description)
    
    return JSONResponse(content={
        "status": "accepted",
        "job_id": session_id,
        "case_description": case_description,
    })

@app.get("/api/find/{job_id}")
async def get_citation_job(job_id: str) -> JSONResponse:
    import json
    try:
        session = await session_service.get_session(app_name="citation_finder", user_id="default_user", session_id=job_id)
        if not session:
            return JSONResponse(status_code=404, content={"status": "error", "message": "job not found."})
            
        status = "running"
        scrape_log_text = ""
        result_data = None
        
        events = session.events
        logs = []
        
        for event in events:
            author = event.author or 'unknown'
            if event.content and event.content.parts:
                # Format logs for the UI
                for part in event.content.parts:
                    if part.text:
                        text_display = part.text.replace("\n", " ")
                        if len(text_display) > 250:
                            text_display = text_display[:250] + "..."
                        logs.append(f"[{author.upper()}] TEXT: {text_display}")
                    elif getattr(part, "function_call", None):
                        args = getattr(part.function_call, "args", {})
                        logs.append(f"[{author.upper()}] TOOL CALL: {part.function_call.name}({args})")
                    elif getattr(part, "function_response", None):
                        resp = getattr(part.function_response, "response", "")
                        resp_str = str(resp).replace("\n", " ")
                        if len(resp_str) > 250:
                            resp_str = resp_str[:250] + "..."
                        logs.append(f"[{author.upper()}] TOOL RESPONSE ({part.function_response.name}): {resp_str}")
            
            # Check result from model
            if event.author == "citation_agent" and event.content and event.content.parts:
                text = "".join(p.text for p in event.content.parts if p.text)
                if "is_success" in text:
                    try:
                        # Clean up JSON
                        cleaned = text.strip()
                        if cleaned.startswith("```"):
                            lines = cleaned.splitlines()
                            if len(lines) >= 3:
                                cleaned = "\n".join(lines[1:-1]).strip()
                        data = json.loads(cleaned)
                        if "is_success" in data:
                            status = "completed"
                            indian_kanoon_link = data.get("final_url", "")
                            indian_court_link = ""
                            if "sci.gov.in" in indian_kanoon_link:
                                indian_court_link = indian_kanoon_link
                                indian_kanoon_link = ""
                            
                            result_data = {
                                "status": "matched" if data["is_success"] else "unmatched",
                                "indiankanoon_link": indian_kanoon_link,
                                "indian_court_link": indian_court_link,
                                "message": data.get("rationale", "")
                            }
                    except json.JSONDecodeError:
                        pass

            if getattr(event, 'actions', None) and getattr(event.actions, 'end_of_agent', False):
                if status == "running":
                    status = "completed"

        import time
        elapsed_seconds = 0
        if events:
            start_time = events[0].timestamp
            end_time = events[-1].timestamp if status == "completed" else time.time()
            elapsed_seconds = max(0, round(end_time - start_time, 1))

        return JSONResponse(content={
            "status": status,
            "elapsed_seconds": elapsed_seconds,
            "result": result_data,
            "scrape_log_text": "\n".join(logs) or "Waiting for logs...",
            "trace_events": [{"idx": i} for i in range(len(events))]
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.post("/api/gsearch")
async def google_search(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    # Fallback to normal ADK search since it has google_search tool
    return await start_citation_job(request, background_tasks)
