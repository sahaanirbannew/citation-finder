from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock, Thread
from time import perf_counter, time
from uuid import uuid4

from agentic_app.models import SearchTrace
from agentic_app.orchestrator import CitationFinderAgent


@dataclass
class SearchJob:
    job_id: str
    case_description: str
    status: str = "queued"
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    started_perf: float | None = None
    finished_perf: float | None = None
    result: dict | None = None
    error: str | None = None
    trace: SearchTrace = field(default_factory=SearchTrace)


class JobManager:
    def __init__(self, agent: CitationFinderAgent) -> None:
        self.agent = agent
        self._jobs: dict[str, SearchJob] = {}
        self._lock = Lock()

    def start_job(self, case_description: str) -> SearchJob:
        job = SearchJob(job_id=str(uuid4()), case_description=case_description)
        with self._lock:
            self._jobs[job.job_id] = job

        # Each crawl runs in its own daemon thread so the API stays responsive.
        thread = Thread(target=self._run_job, args=(job.job_id,), daemon=True)
        thread.start()
        return job

    def get_job(self, job_id: str) -> SearchJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def snapshot(self, job_id: str) -> dict | None:
        job = self.get_job(job_id)
        if not job:
            return None

        return {
            "job_id": job.job_id,
            "status": job.status,
            "case_description": job.case_description,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "elapsed_seconds": self._elapsed_seconds(job),
            "error": job.error,
            "result": job.result,
            "trace_events": job.trace.to_dict(),
            "trace_text": job.trace.to_pretty_text(),
            "scrape_log_text": job.trace.to_scrape_log_text(),
        }

    def _run_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if not job:
            return

        # Perf counters back the live elapsed-time display in the UI.
        job.status = "running"
        job.updated_at = time()
        job.started_perf = perf_counter()
        job.trace.add("job_started", "Background job started", metadata={"job_id": job.job_id})

        try:
            result = self.agent.run(job.case_description, trace=job.trace)
            job.result = result
            job.status = "completed"
            job.updated_at = time()
            job.finished_perf = perf_counter()
            job.trace.add(
                "job_completed",
                "Background job completed",
                metadata={"job_id": job.job_id, "elapsed_seconds": self._elapsed_seconds(job)},
            )
        except Exception as exc:
            job.error = str(exc)
            job.status = "failed"
            job.updated_at = time()
            job.finished_perf = perf_counter()
            job.trace.add(
                "job_failed",
                "Background job failed",
                metadata={
                    "job_id": job.job_id,
                    "error": str(exc),
                    "elapsed_seconds": self._elapsed_seconds(job),
                },
            )

    def _elapsed_seconds(self, job: SearchJob) -> float:
        if job.started_perf is None:
            return 0.0
        end = job.finished_perf if job.finished_perf is not None else perf_counter()
        return round(max(0.0, end - job.started_perf), 2)
