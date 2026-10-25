"""Gather batch results into a report, with live progress and final output."""

from __future__ import annotations

import json
import queue
import sys
import time
from typing import TextIO

from parallel_clamscan.models import BatchResult, ProducerStats, Report, ScanError

_GET_TIMEOUT_S = 0.2
_PROGRESS_INTERVAL_S = 0.5
_MAX_LISTED_ERRORS = 20


def _human_bytes(n: float) -> str:
    """Format a byte count with a binary unit (e.g. ``1.5 GiB``)."""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024
    raise AssertionError("unreachable")


def _human_duration(seconds: float) -> str:
    """Format seconds as ``H:MM:SS``."""
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


class Aggregator:
    """Consume ``result_queue`` until every worker has sent its sentinel.

    State is kept on the instance so ``run`` can be called again after a
    KeyboardInterrupt to drain the remaining results.
    """

    def __init__(
        self,
        result_queue: queue.Queue,
        n_workers: int,
        report: Report,
        stats: ProducerStats | None = None,
        progress: TextIO | None = None,
    ) -> None:
        """Set up an aggregator; ``progress`` is where the live line is drawn."""
        self.result_queue = result_queue
        self.n_workers = n_workers
        self.report = report
        self.stats = stats
        self.progress = progress
        self._sentinels = 0
        self._last_draw = 0.0

    def run(self) -> Report:
        """Process results until all workers are done; return the report."""
        while self._sentinels < self.n_workers:
            try:
                item = self.result_queue.get(timeout=_GET_TIMEOUT_S)
            except queue.Empty:
                self._draw()
                continue
            self._handle(item)
            self._draw()
        self._draw(force=True)
        if self.progress is not None:
            self.progress.write("\n")
        return self.report

    def _handle(self, item: BatchResult | ScanError | None) -> None:
        """Dispatch one queue item."""
        if item is None:
            self._sentinels += 1
        elif isinstance(item, ScanError):
            self.report.add_error(item)
        else:
            self.report.add(item)

    def _draw(self, force: bool = False) -> None:
        """Redraw the progress line, throttled."""
        now = time.monotonic()
        if self.progress is None or (not force and now - self._last_draw < _PROGRESS_INTERVAL_S):
            return
        self._last_draw = now
        self.progress.write("\r\033[K" + progress_line(self.report, self.stats))
        self.progress.flush()


def progress_line(report: Report, stats: ProducerStats | None) -> str:
    """Return a one-line status: files scanned / discovered, infected, errors, elapsed."""
    found = ""
    if stats is not None:
        found = f"/{stats.files}" + ("" if stats.done else "+")
    return (
        f"[pclamscan] scanned {report.files_scanned}{found} files"
        f" ({_human_bytes(report.bytes_scanned)})"
        f" | infected {len(report.infected)} | errors {len(report.errors)}"
        f" | {_human_duration(report.duration)}"
    )


def _printable(text: str) -> str:
    """Escape non-printable characters so file names cannot break the summary.

    Undecodable bytes (lone surrogates from ``surrogateescape``) are shown as
    ``\\xNN``, other non-printable characters with their ``repr`` escape.
    """
    out = []
    for ch in text:
        if ch.isprintable():
            out.append(ch)
        elif 0xDC80 <= ord(ch) <= 0xDCFF:
            out.append(f"\\x{ord(ch) - 0xDC00:02x}")
        else:
            out.append(repr(ch)[1:-1])
    return "".join(out)


def format_summary(report: Report) -> str:
    """Return the human-readable end-of-scan summary."""
    lines = [
        "----------- SCAN SUMMARY -----------",
        f"Folders: {', '.join(_printable(f) for f in report.folders)}",
        f"Workers: {report.workers}",
        f"Scanned files: {report.files_scanned}",
        f"Data scanned: {_human_bytes(report.bytes_scanned)}",
        f"Infected files: {len(report.infected)}",
        f"Errors: {len(report.errors)}",
        f"Time: {report.duration:.1f} s ({_human_duration(report.duration)})",
    ]
    if report.interrupted:
        lines.append("Scan INTERRUPTED: results are partial.")
    if report.infected:
        lines.append("\nInfected files:")
        lines += [f"  {_printable(d.path)}: {_printable(d.signature)}" for d in report.infected]
    if report.errors:
        lines.append("\nErrors:")
        lines += [
            f"  {_printable(e.path)}: {_printable(e.message)}"
            for e in report.errors[:_MAX_LISTED_ERRORS]
        ]
        hidden = len(report.errors) - _MAX_LISTED_ERRORS
        if hidden > 0:
            lines.append(f"  ... and {hidden} more (use --json-report for the full list)")
    return "\n".join(lines)


def write_json(report: Report, path: str) -> None:
    """Write the report as JSON to ``path``."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, indent=2)
        fh.write("\n")


def default_progress_stream() -> TextIO | None:
    """Return stderr when it is a terminal, else None (no progress line)."""
    return sys.stderr if sys.stderr.isatty() else None
