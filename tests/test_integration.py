"""End-to-end test against the real clamscan (skipped if not installed)."""

import os
import shutil
import threading

import pytest

from parallel_clamscan.cli import main
from parallel_clamscan.models import Batch
from parallel_clamscan.worker import scan_batch

pytestmark = pytest.mark.skipif(shutil.which("clamscan") is None, reason="clamscan not installed")

# The standard, harmless EICAR antivirus test string. It is split in two so that
# antivirus software does not flag this source file; it is only assembled at runtime.
EICAR = r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD" + r"-ANTIVIRUS-TEST-FILE!$H+H*"


def test_real_clamscan_detects_eicar(tmp_path, capsys):
    (tmp_path / "sub").mkdir()
    (tmp_path / "clean.txt").write_text("hello")
    (tmp_path / "sub" / "eicar.com").write_text(EICAR)
    rc = main([str(tmp_path), "-j", "2", "--batch-files", "1"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "Scanned files: 2" in out
    assert f"{tmp_path / 'sub' / 'eicar.com'}: Eicar-Test-Signature" in out


def test_real_clamscan_control_character_name_is_not_silently_missed(tmp_path, capsys):
    # Regression: clamscan's result line for this file used to be split in two
    # by the parser, hiding the detection (exit 0, "Infected files: 0").
    (tmp_path / "payload\x1c").write_text(EICAR)
    rc = main([str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 2
    assert f"{tmp_path}/payload\\x1c: File name contains a control character" in out


def test_real_clamscan_too_long_path_is_not_redirected(tmp_path, capsys):
    # Regression: clamscan's --file-list reader cut this path at 1023 bytes and
    # scanned the tail ("/outside/clean") instead of the infected file.
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "clean").write_text("hello")
    prefix = str(tmp_path / "tree")
    while 1023 - len(prefix) > 250:
        prefix += "/" + "d" * 200
    prefix += "/" + "p" * (1023 - len(prefix) - 1)
    hidden = prefix + str(tmp_path / "outside" / "clean")
    os.makedirs(os.path.dirname(hidden))
    with open(hidden, "w") as fh:
        fh.write(EICAR)
    rc = main([str(tmp_path / "tree")])
    out = capsys.readouterr().out
    assert rc == 2
    assert "Scanned files: 0" in out
    assert "Path longer than 1022 bytes" in out


def test_real_clamscan_does_not_follow_swapped_symlink(tmp_path):
    # A listed file replaced by a symlink after the walk is skipped, not followed.
    (tmp_path / "target").write_text(EICAR)
    (tmp_path / "listed").symlink_to(tmp_path / "target")
    batch = Batch(0, (str(tmp_path / "listed"),), 1)
    result = scan_batch(batch, shutil.which("clamscan"), [], threading.Event())
    assert (result.scanned, result.detections, result.errors) == (0, [], [])
