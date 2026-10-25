import json
import os

import pytest

from parallel_clamscan.cli import main, parse_args, result_hiding_options


def test_parse_args_splits_extra_clamscan_args(fake_clamscan, tmp_path):
    args, extra = parse_args(
        [str(tmp_path), "-j", "3", "--clamscan", fake_clamscan, "--", "--max-filesize=1M"]
    )
    assert args.workers == 3
    assert extra == ["--max-filesize=1M"]


@pytest.mark.parametrize(
    "option",
    ["-i", "--infected", "--infected=yes", "-o", "--suppress-ok-results", "--quiet", "-ri"],
)
def test_parse_args_rejects_result_hiding_options(fake_clamscan, tmp_path, capsys, option):
    with pytest.raises(SystemExit):
        parse_args([str(tmp_path), "--clamscan", fake_clamscan, "--", option])
    assert "not supported" in capsys.readouterr().err


def test_result_hiding_options_ignores_other_args():
    assert result_hiding_options(["-d", "/db/io", "--include=x.io", "--max-filesize=1M"]) == []


def test_main_escapes_unprintable_names_and_still_writes_json(fake_clamscan, tmp_path, capsys):
    tree = tmp_path / "tree"
    tree.mkdir()
    with open(os.path.join(os.fsencode(tree), b"x\xff"), "w") as fh:
        fh.write("VIRUS")
    report_path = tmp_path / "report.json"
    argv = [str(tree), "--clamscan", fake_clamscan, "--json-report", str(report_path)]
    assert main(argv) == 1
    assert f"{tree}/x\\xff: Fake.Virus" in capsys.readouterr().out
    assert json.loads(report_path.read_text())["infected"][0]["signature"] == "Fake.Virus"


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
