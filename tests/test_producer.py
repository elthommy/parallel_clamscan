import os
import queue
import threading

from parallel_clamscan.models import Batch, ProducerStats
from parallel_clamscan.producer import iter_files, make_batches, run_producer


def test_iter_files_walks_tree_and_reports_sizes(sample_tree):
    files = dict(iter_files([str(sample_tree)], on_error=lambda e: None))
    rel = {os.path.relpath(p, sample_tree) for p in files}
    assert rel == {"f1", "a/f2", "a/b/f3", "a/b/f4", "c/f5", "c/bad:file"}
    assert files[str(sample_tree / "f1")] == len("clean 0")


def test_iter_files_skips_symlinks_and_accepts_plain_file(tmp_path):
    target = tmp_path / "real"
    target.write_text("x")
    (tmp_path / "link").symlink_to(target)
    (tmp_path / "dirlink").symlink_to(tmp_path, target_is_directory=True)
    assert [p for p, _ in iter_files([str(tmp_path)], lambda e: None)] == [str(target)]
    assert [p for p, _ in iter_files([str(target)], lambda e: None)] == [str(target)]


def test_iter_files_reports_unreadable_dir(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "f").write_text("x")
    locked.chmod(0)
    errors = []
    try:
        files = list(iter_files([str(tmp_path)], errors.append))
    finally:
        locked.chmod(0o755)
    if os.geteuid() != 0:
        assert files == []
        assert [e.path for e in errors] == [str(locked)]


def test_iter_files_rejects_newline_names(tmp_path):
    (tmp_path / "bad\nname").write_text("x")
    errors = []
    assert list(iter_files([str(tmp_path)], errors.append)) == []
    assert len(errors) == 1


def test_make_batches_by_count():
    files = [(f"/f{i}", 1) for i in range(5)]
    batches = list(make_batches(files, max_files=2, max_bytes=10**9))
    assert [b.paths for b in batches] == [("/f0", "/f1"), ("/f2", "/f3"), ("/f4",)]
    assert [b.id for b in batches] == [0, 1, 2]


def test_make_batches_by_size():
    files = [("/a", 60), ("/b", 50), ("/c", 200), ("/d", 1)]
    batches = list(make_batches(files, max_files=100, max_bytes=100))
    assert batches == [Batch(0, ("/a", "/b"), 110), Batch(1, ("/c",), 200), Batch(2, ("/d",), 1)]


def test_make_batches_empty():
    assert list(make_batches([], 10, 10)) == []


def test_run_producer_sends_batches_then_sentinels(sample_tree):
    tasks, results = queue.Queue(), queue.Queue()
    stats = ProducerStats()
    run_producer([str(sample_tree)], tasks, results, 3, threading.Event(), 4, 10**9, stats)
    items = [tasks.get_nowait() for _ in range(tasks.qsize())]
    assert [len(b.paths) for b in items[:2]] == [4, 2]
    assert items[2:] == [None, None, None]
    assert stats.files == 6 and stats.done


def test_run_producer_stops_when_queue_full_and_stop_set(sample_tree):
    tasks, results = queue.Queue(maxsize=1), queue.Queue()
    stop = threading.Event()
    stats = ProducerStats()
    t = threading.Thread(
        target=run_producer,
        args=([str(sample_tree)], tasks, results, 1, stop, 1, 10**9, stats),
    )
    t.start()
    tasks.get(timeout=5)  # let one batch through, then the queue fills again
    stop.set()
    while t.is_alive():
        tasks.get(timeout=5)
    t.join(timeout=5)
    assert stats.done
