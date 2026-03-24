from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any


@dataclass
class SearchCandidate:
    title: str
    url: str
    source: str
    snippet: str = ""


@dataclass
class ScrapedDocument:
    url: str
    title: str
    text: str
    source: str
    content_type: str = "html"
    discovered_links: list[SearchCandidate] = field(default_factory=list)


@dataclass
class ValidationResult:
    is_match: bool
    confidence: float
    rationale: str
    extracted_case_name: str = ""
    extracted_court: str = ""
    extracted_date: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ValidationResult":
        confidence = float(payload.get("confidence", 0.0))
        confidence = max(0.0, min(confidence, 1.0))
        return cls(
            is_match=bool(payload.get("is_match", False)),
            confidence=confidence,
            rationale=str(payload.get("rationale", "")),
            extracted_case_name=str(payload.get("extracted_case_name", "")),
            extracted_court=str(payload.get("extracted_court", "")),
            extracted_date=str(payload.get("extracted_date", "")),
        )


@dataclass
class TraceEvent:
    index: int
    timestamp: str
    event_type: str
    message: str
    url: str = ""
    query: str = ""
    parent_url: str = ""
    depth: int = 0
    path: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SearchTrace:
    events: list[TraceEvent] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def add(
        self,
        event_type: str,
        message: str,
        *,
        url: str = "",
        query: str = "",
        parent_url: str = "",
        depth: int = 0,
        path: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self.events.append(
                TraceEvent(
                    index=len(self.events) + 1,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    event_type=event_type,
                    message=message,
                    url=url,
                    query=query,
                    parent_url=parent_url,
                    depth=depth,
                    path=path or [],
                    metadata=metadata or {},
                )
            )

    def to_dict(self) -> list[dict[str, Any]]:
        with self._lock:
            snapshot = list(self.events)
        return [event.to_dict() for event in snapshot]

    def to_pretty_text(self) -> str:
        with self._lock:
            snapshot = list(self.events)
        lines: list[str] = []
        for event in snapshot:
            path_text = " -> ".join(event.path) if event.path else "-"
            parts = [
                f"[{event.index:03d}] {event.event_type}",
                event.message,
            ]
            if event.query:
                parts.append(f"query={event.query}")
            if event.url:
                parts.append(f"url={event.url}")
            if event.parent_url:
                parts.append(f"parent={event.parent_url}")
            parts.append(f"depth={event.depth}")
            parts.append(f"path={path_text}")
            if event.metadata:
                metadata_text = ", ".join(f"{key}={value}" for key, value in event.metadata.items())
                parts.append(f"meta={metadata_text}")
            lines.append(" | ".join(parts))
        return "\n".join(lines)

    def to_scrape_log_text(self) -> str:
        with self._lock:
            snapshot = list(self.events)
        lines: list[str] = []
        for event in snapshot:
            if event.event_type != "scrape_request" or not event.url:
                continue
            lines.append(event.url)
        return "\n".join(lines) if lines else "No scrape links yet."
