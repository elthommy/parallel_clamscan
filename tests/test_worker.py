import queue
import threading
import time

from parallel_clamscan.models import Batch, BatchResult, ScanError
from parallel_clamscan.worker import run_worker, scan_batch


def _batch(*paths):
    return Batch(7, tuple(str(p) for p in paths), 42)


def test_scan_batch_detects_infection(fake_clamscan, sample_tree):
    batch = _batch(sample_tree / "f1", sample_tree / "c" / "bad:file")
    result = scan_batch(batch, fake_clamscan, [], threading.Event())
    assert result.returncode == 1
    assert result.scanned == 2
    assert [d.path for d in result.detections] == [str(sample_tree / "c" / "bad:file")]
    assert result.errors == []
    assert (result.batch_id, result.files, result.total_bytes) == (7, 2, 42)


def test_scan_batch_reports_unreadable_file(fake_clamscan, tmp_path):
    result = scan_batch(_batch(tmp_path / "missing"), fake_clamscan, [], threading.Event())
    assert result.returncode == 2
    assert result.errors == [ScanError(str(tmp_path / "missing"), "Access denied")]


def test_scan_batch_unexpected_exit_code_is_batch_error(fake_clamscan, sample_tree):
    result = scan_batch(_batch(sample_tree / "f1"), fake_clamscan, ["--crash"], threading.Event())
    assert result.returncode == 40
    assert len(result.errors) == 1 and "boom" in result.errors[0].message


def test_scan_batch_missing_executable(sample_tree):
    result = scan_batch(_batch(sample_tree / "f1"), "/nonexistent/clamscan", [], threading.Event())
    assert result.returncode == -1
    assert "Cannot run" in result.errors[0].message


def test_scan_batch_stop_terminates_child(fake_clamscan, sample_tree):
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    start = time.monotonic()
    result = scan_batch(_batch(sample_tree / "f1"), fake_clamscan, ["--sleep", "30"], stop)
    assert result is None
    assert time.monotonic() - start < 5


def test_run_worker_processes_until_sentinel(fake_clamscan, sample_tree):
    tasks, results = queue.Queue(), queue.Queue()
    tasks.put(Batch(0, (str(sample_tree / "f1"),), 1))
    tasks.put(Batch(1, (str(sample_tree / "c" / "bad:file"),), 1))
    tasks.put(None)
    run_worker(tasks, results, fake_clamscan, [], threading.Event())
    items = [results.get_nowait() for _ in range(results.qsize())]
    assert all(isinstance(i, BatchResult) for i in items[:2])
    assert items[2] is None


def test_run_worker_skips_batches_once_stopped(fake_clamscan, sample_tree):
    tasks, results = queue.Queue(), queue.Queue()
    tasks.put(Batch(0, (str(sample_tree / "f1"),), 1))
    tasks.put(None)
    stop = threading.Event()
    stop.set()
    run_worker(tasks, results, fake_clamscan, [], stop)
    assert results.get_nowait() is None
    assert results.empty()
