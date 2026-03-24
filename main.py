from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from agentic_app.config import Settings
from agentic_app.job_manager import JobManager
from agentic_app.orchestrator import CitationFinderAgent


BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Citation Finder")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

settings = Settings.from_env()
agent = CitationFinderAgent(settings)
# Jobs run in the background so the browser can poll for live logs.
job_manager = JobManager(agent)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/find")
async def start_citation_job(request: Request) -> JSONResponse:
    payload = await request.json()
    case_description = str(payload.get("case_description", "")).strip()
    if not case_description:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "case_description is required."},
        )

    # Return immediately with a job id instead of blocking on the crawl.
    job = job_manager.start_job(case_description)
    return JSONResponse(
        content={
            "status": "accepted",
            "job_id": job.job_id,
            "case_description": job.case_description,
        }
    )


@app.get("/api/find/{job_id}")
async def get_citation_job(job_id: str) -> JSONResponse:
    # The UI polls this endpoint to render live progress and logs.
    snapshot = job_manager.snapshot(job_id)
    if not snapshot:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "job not found."},
        )
    return JSONResponse(content=snapshot)
