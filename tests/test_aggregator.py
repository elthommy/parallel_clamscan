import io
import json
import queue

from parallel_clamscan.aggregator import Aggregator, format_summary, write_json
from parallel_clamscan.models import BatchResult, Detection, ProducerStats, Report, ScanError


def _result(batch_id, scanned, detections=(), errors=()):
    return BatchResult(batch_id, scanned, 100, scanned, list(detections), list(errors), 1.5, 0)


def _run(items, n_workers, progress=None):
    q = queue.Queue()
    for item in items:
        q.put(item)
    report = Report(folders=["/data"], workers=n_workers)
    return Aggregator(q, n_workers, report, ProducerStats(files=5, done=True), progress).run()


def test_aggregator_merges_until_all_sentinels():
    det = Detection("/data/x", "Sig")
    items = [
        _result(1, 3, detections=[det]),
        None,
        ScanError("/data/locked", "Permission denied"),
        _result(0, 2),
        None,
    ]
    report = _run(items, n_workers=2)
    assert report.files_scanned == 5
    assert report.bytes_scanned == 200
    assert report.infected == [det]
    assert report.errors == [ScanError("/data/locked", "Permission denied")]
    assert report.exit_code == 1
    assert [b["id"] for b in report.to_dict()["batches"]] == [0, 1]


def test_aggregator_draws_progress():
    out = io.StringIO()
    _run([_result(0, 5), None], n_workers=1, progress=out)
    assert "scanned 5/5 files" in out.getvalue()


def test_exit_codes():
    report = Report(folders=[], workers=1)
    assert report.exit_code == 0
    report.add_error(ScanError("/p", "x"))
    assert report.exit_code == 2
    report.infected.append(Detection("/p", "s"))
    assert report.exit_code == 1
    report.interrupted = True
    assert report.exit_code == 130


def test_format_summary_truncates_errors():
    report = Report(folders=["/data"], workers=4)
    for i in range(25):
        report.add_error(ScanError(f"/p{i}", "denied"))
    report.finish()
    summary = format_summary(report)
    assert "Errors: 25" in summary
    assert "/p19: denied" in summary and "/p20: denied" not in summary
    assert "and 5 more" in summary


def test_write_json(tmp_path):
    report = Report(folders=["/data"], workers=2)
    report.add(_result(0, 1, detections=[Detection("/data/\udcff", "Sig")]))
    report.finish()
    path = tmp_path / "r.json"
    write_json(report, str(path))
    data = json.loads(path.read_text())
    assert data["files_scanned"] == 1
    assert data["infected"][0]["signature"] == "Sig"
    assert data["finished"] is not None
