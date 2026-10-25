import os
import queue
import threading

import pytest

from parallel_clamscan.models import Batch, ProducerStats
from parallel_clamscan.producer import iter_files, make_batches, run_producer, unlistable_reason


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


@pytest.mark.parametrize(
    "name", ["bad\nname", "bad\rname", "p\x0b", "p\x0c", "p\x1c", "p\x1e", "p\x85", "p "]
)
def test_iter_files_rejects_names_with_line_breaking_characters(tmp_path, name):
    (tmp_path / name).write_text("x")
    errors = []
    assert list(iter_files([str(tmp_path)], errors.append)) == []
    assert [e.path for e in errors] == [str(tmp_path / name)]
    assert "control character" in errors[0].message


def _nested_file(root, length):
    """Create a file whose absolute path is exactly ``length`` bytes long."""
    path = str(root)
    while length - len(path) > 250:
        path += "/" + "d" * 200
    path += "/" + "f" * (length - len(path) - 1)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("x")
    assert len(path) == length
    return path


def test_iter_files_rejects_paths_too_long_for_file_list(tmp_path):
    ok = _nested_file(tmp_path / "ok", 1022)
    too_long = _nested_file(tmp_path / "long", 1023)
    errors = []
    assert [p for p, _ in iter_files([str(tmp_path)], errors.append)] == [ok]
    assert [e.path for e in errors] == [too_long]
    assert "longer than 1022 bytes" in errors[0].message


def test_iter_files_rejects_unlistable_file_given_directly(tmp_path):
    (tmp_path / "p\x1c").write_text("x")
    errors = []
    assert list(iter_files([str(tmp_path / "p\x1c")], errors.append)) == []
    assert len(errors) == 1


def test_unlistable_reason_accepts_ordinary_names():
    assert unlistable_reason("/data/été: report (1).txt") is None


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
    # Drain until the sentinel, not while the thread is alive: it can still be
    # "alive" for an instant after putting its last item, and get() would then hang.
    drained = []
    while (item := tasks.get(timeout=5)) is not None:
        drained.append(item)
    t.join(timeout=5)
    assert not t.is_alive()
    assert stats.done
    assert len(drained) < 5  # stopped early: not all 6 single-file batches were sent
