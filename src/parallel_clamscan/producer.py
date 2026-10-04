"""Walk the input folders and push batches of files onto the task queue."""

from __future__ import annotations

import os
import queue
import threading
from collections.abc import Callable, Iterable, Iterator

from parallel_clamscan.models import Batch, ProducerStats, ScanError

ErrorSink = Callable[[ScanError], None]
_PUT_TIMEOUT_S = 0.2


def _scan_dir(directory: str, on_error: ErrorSink) -> list[os.DirEntry]:
    """List a directory, reporting it as an error if it cannot be read."""
    try:
        with os.scandir(directory) as it:
            return list(it)
    except OSError as exc:
        on_error(ScanError(directory, exc.strerror or str(exc)))
        return []


def _classify_entry(entry: os.DirEntry, on_error: ErrorSink) -> tuple[str, int] | str | None:
    """Return ``(path, size)`` for a file, the path for a directory, else None."""
    try:
        if entry.is_dir(follow_symlinks=False):
            return entry.path
        if entry.is_file(follow_symlinks=False):
            if "\n" in entry.path:
                on_error(ScanError(entry.path, "File name contains a newline, not scanned"))
                return None
            return entry.path, entry.stat(follow_symlinks=False).st_size
    except OSError as exc:
        on_error(ScanError(entry.path, exc.strerror or str(exc)))
    return None


def iter_files(
    folders: Iterable[str], on_error: ErrorSink, stop: threading.Event | None = None
) -> Iterator[tuple[str, int]]:
    """Yield ``(path, size)`` for every regular file under ``folders``.

    Symlinks are not followed, matching clamscan's default behaviour.
    """
    stack = list(reversed([os.path.abspath(f) for f in folders]))
    while stack:
        if stop is not None and stop.is_set():
            return
        current = stack.pop()
        if os.path.isfile(current) and not os.path.islink(current):
            yield current, os.path.getsize(current)
            continue
        subdirs = []
        for entry in _scan_dir(current, on_error):
            item = _classify_entry(entry, on_error)
            if isinstance(item, str):
                subdirs.append(item)
            elif item is not None:
                yield item
        stack.extend(reversed(subdirs))


def make_batches(
    files: Iterable[tuple[str, int]], max_files: int, max_bytes: int
) -> Iterator[Batch]:
    """Group files into batches capped by file count and cumulated size."""
    paths: list[str] = []
    size = 0
    batch_id = 0
    for path, file_size in files:
        paths.append(path)
        size += file_size
        if len(paths) >= max_files or size >= max_bytes:
            yield Batch(batch_id, tuple(paths), size)
            batch_id += 1
            paths, size = [], 0
    if paths:
        yield Batch(batch_id, tuple(paths), size)


def _put(task_queue: queue.Queue, item: object, stop: threading.Event) -> bool:
    """Put ``item`` on the queue, giving up (False) if ``stop`` gets set."""
    while not stop.is_set():
        try:
            task_queue.put(item, timeout=_PUT_TIMEOUT_S)
            return True
        except queue.Full:
            continue
    return False


def _counted(files: Iterable[tuple[str, int]], stats: ProducerStats) -> Iterator[tuple[str, int]]:
    """Pass files through while updating the discovery counters."""
    for path, size in files:
        stats.files += 1
        stats.total_bytes += size
        yield path, size


def run_producer(
    folders: list[str],
    task_queue: queue.Queue,
    result_queue: queue.Queue,
    n_workers: int,
    stop: threading.Event,
    max_files: int,
    max_bytes: int,
    stats: ProducerStats,
) -> None:
    """Producer thread body: enqueue batches, then one ``None`` sentinel per worker.

    Walk errors are sent straight to ``result_queue`` as ``ScanError`` items.
    """
    try:
        files = _counted(iter_files(folders, result_queue.put, stop), stats)
        for batch in make_batches(files, max_files, max_bytes):
            if not _put(task_queue, batch, stop):
                break
    except Exception as exc:  # noqa: BLE001 - surface any crash in the report
        result_queue.put(ScanError("<producer>", f"Producer crashed: {exc!r}"))
    finally:
        stats.done = True
        for _ in range(n_workers):
            task_queue.put(None)
