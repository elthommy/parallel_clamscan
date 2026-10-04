"""Data models shared by the producer, the workers and the aggregator."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

EXIT_CLEAN = 0
EXIT_INFECTED = 1
EXIT_ERRORS = 2
EXIT_INTERRUPTED = 130


@dataclass(frozen=True)
class Batch:
    """A group of files scanned by a single clamscan invocation."""

    id: int
    paths: tuple[str, ...]
    total_bytes: int


@dataclass(frozen=True)
class Detection:
    """An infected file and the signature that matched it."""

    path: str
    signature: str


@dataclass(frozen=True)
class ScanError:
    """A file, directory or batch that could not be scanned."""

    path: str
    message: str


@dataclass
class BatchResult:
    """Outcome of scanning one batch."""

    batch_id: int
    files: int
    total_bytes: int
    scanned: int
    detections: list[Detection]
    errors: list[ScanError]
    duration: float
    returncode: int


@dataclass
class ProducerStats:
    """Live counters written by the producer thread, read for progress display."""

    files: int = 0
    total_bytes: int = 0
    done: bool = False


def _iso(timestamp: float) -> str:
    """Format a POSIX timestamp as an ISO-8601 UTC string."""
    return datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="seconds")


@dataclass
class Report:
    """Running aggregate of every batch result, turned into the final report."""

    folders: list[str]
    workers: int
    started: float = field(default_factory=time.time)
    finished: float | None = None
    files_scanned: int = 0
    bytes_scanned: int = 0
    batches_done: int = 0
    infected: list[Detection] = field(default_factory=list)
    errors: list[ScanError] = field(default_factory=list)
    batches: list[dict] = field(default_factory=list)
    interrupted: bool = False

    def add(self, result: BatchResult) -> None:
        """Merge one batch result into the totals."""
        self.files_scanned += result.scanned
        self.bytes_scanned += result.total_bytes
        self.batches_done += 1
        self.infected.extend(result.detections)
        self.errors.extend(result.errors)
        self.batches.append(
            {
                "id": result.batch_id,
                "files": result.files,
                "duration_s": round(result.duration, 3),
                "returncode": result.returncode,
            }
        )

    def add_error(self, error: ScanError) -> None:
        """Record an error that happened outside of a batch (e.g. unreadable dir)."""
        self.errors.append(error)

    def finish(self) -> None:
        """Mark the scan as finished."""
        self.finished = time.time()

    @property
    def duration(self) -> float:
        """Elapsed seconds since the scan started (until finish, if finished)."""
        end = self.finished if self.finished is not None else time.time()
        return end - self.started

    @property
    def exit_code(self) -> int:
        """Process exit code: interrupted > infected > errors > clean."""
        if self.interrupted:
            return EXIT_INTERRUPTED
        if self.infected:
            return EXIT_INFECTED
        if self.errors:
            return EXIT_ERRORS
        return EXIT_CLEAN

    def to_dict(self) -> dict:
        """Return a JSON-serializable view of the report."""
        return {
            "started": _iso(self.started),
            "finished": _iso(self.finished) if self.finished is not None else None,
            "duration_s": round(self.duration, 3),
            "interrupted": self.interrupted,
            "workers": self.workers,
            "folders": self.folders,
            "files_scanned": self.files_scanned,
            "bytes_scanned": self.bytes_scanned,
            "infected": [{"path": d.path, "signature": d.signature} for d in self.infected],
            "errors": [{"path": e.path, "message": e.message} for e in self.errors],
            "batches": sorted(self.batches, key=lambda b: b["id"]),
        }
