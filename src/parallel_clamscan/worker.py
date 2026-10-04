"""Worker threads: pull batches, run clamscan on them, push results."""

from __future__ import annotations

import os
import queue
import subprocess
import tempfile
import threading
import time

from parallel_clamscan.clamscan import build_command, parse_output
from parallel_clamscan.models import Batch, BatchResult, ScanError

_POLL_S = 0.5
_STDERR_TAIL = 500


def _write_file_list(paths: tuple[str, ...]) -> str:
    """Write paths (one per line, raw bytes) to a temp file and return its name."""
    fd, name = tempfile.mkstemp(prefix="pclamscan-", suffix=".lst")
    with os.fdopen(fd, "wb") as fh:
        for path in paths:
            fh.write(os.fsencode(path) + b"\n")
    return name


def _run(cmd: list[str], stop: threading.Event) -> tuple[int, str, str] | None:
    """Run ``cmd``; return ``(rc, stdout, stderr)``, or None if stopped meanwhile.

    The child runs in its own session so a terminal Ctrl-C only reaches us,
    and we terminate the child ourselves.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="surrogateescape",
        start_new_session=True,
    )
    while True:
        try:
            out, err = proc.communicate(timeout=_POLL_S)
        except subprocess.TimeoutExpired:
            if stop.is_set():
                proc.terminate()
                proc.communicate()
                return None
            continue
        return proc.returncode, out, err


def _batch_error(batch: Batch, message: str) -> ScanError:
    """Build an error describing a whole failed batch."""
    return ScanError(f"<batch {batch.id}: {len(batch.paths)} files>", message)


def scan_batch(
    batch: Batch, clamscan: str, extra_args: list[str], stop: threading.Event
) -> BatchResult | None:
    """Scan one batch with clamscan; return None if interrupted."""
    start = time.monotonic()
    file_list = _write_file_list(batch.paths)
    try:
        outcome = _run(build_command(clamscan, file_list, extra_args), stop)
    except OSError as exc:
        outcome = (-1, "", f"Cannot run {clamscan}: {exc}")
    finally:
        os.unlink(file_list)
    if outcome is None:
        return None
    returncode, out, err = outcome
    warnings = [line for line in err.splitlines() if line.startswith("WARNING: ")]
    parsed = parse_output("\n".join([out, *warnings]))
    errors = list(parsed.errors)
    if returncode not in (0, 1, 2) or (returncode == 2 and not errors):
        errors.append(_batch_error(batch, f"clamscan exit {returncode}: {err[-_STDERR_TAIL:]}"))
    return BatchResult(
        batch_id=batch.id,
        files=len(batch.paths),
        total_bytes=batch.total_bytes,
        scanned=parsed.scanned,
        detections=parsed.detections,
        errors=errors,
        duration=time.monotonic() - start,
        returncode=returncode,
    )


def run_worker(
    task_queue: queue.Queue,
    result_queue: queue.Queue,
    clamscan: str,
    extra_args: list[str],
    stop: threading.Event,
) -> None:
    """Worker thread body: process batches until a ``None`` sentinel arrives.

    Once ``stop`` is set, remaining batches are drained without scanning.
    Always forwards a ``None`` sentinel to ``result_queue`` on exit.
    """
    try:
        while (batch := task_queue.get()) is not None:
            if stop.is_set():
                continue
            try:
                result = scan_batch(batch, clamscan, extra_args, stop)
            except Exception as exc:  # noqa: BLE001 - never lose a batch silently
                result_queue.put(_batch_error(batch, f"Worker crashed: {exc!r}"))
                continue
            if result is not None:
                result_queue.put(result)
    finally:
        result_queue.put(None)
