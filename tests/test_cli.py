import json

import pytest

from parallel_clamscan.cli import main, parse_args


def test_parse_args_splits_extra_clamscan_args(fake_clamscan, tmp_path):
    args, extra = parse_args(
        [str(tmp_path), "-j", "3", "--clamscan", fake_clamscan, "--", "--max-filesize=1M"]
    )
    assert args.workers == 3
    assert extra == ["--max-filesize=1M"]


def test_parse_args_rejects_missing_folder(fake_clamscan, tmp_path):
    with pytest.raises(SystemExit):
        parse_args([str(tmp_path / "nope"), "--clamscan", fake_clamscan])


def test_parse_args_rejects_missing_clamscan(tmp_path):
    with pytest.raises(SystemExit):
        parse_args([str(tmp_path), "--clamscan", "/nonexistent/clamscan"])


def test_main_end_to_end_with_fake_clamscan(fake_clamscan, sample_tree, tmp_path, capsys):
    report_path = tmp_path / "report.json"
    argv = [str(sample_tree), "-j", "3", "--batch-files", "2", "--clamscan", fake_clamscan]
    rc = main([*argv, "--json-report", str(report_path)])
    assert rc == 1
    assert "Infected files: 1" in capsys.readouterr().out
    data = json.loads(report_path.read_text())
    assert data["files_scanned"] == 6
    assert len(data["batches"]) == 3
    assert data["infected"] == [
        {"path": str(sample_tree / "c" / "bad:file"), "signature": "Fake.Virus"}
    ]


def test_main_clean_tree_exits_zero(fake_clamscan, tmp_path, capsys):
    (tmp_path / "ok.txt").write_text("fine")
    assert main([str(tmp_path / "ok.txt"), "--clamscan", fake_clamscan]) == 0
