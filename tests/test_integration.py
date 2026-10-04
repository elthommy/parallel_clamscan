"""End-to-end test against the real clamscan (skipped if not installed)."""

import shutil

import pytest

from parallel_clamscan.cli import main

pytestmark = pytest.mark.skipif(shutil.which("clamscan") is None, reason="clamscan not installed")

# The standard, harmless EICAR antivirus test string.
EICAR = r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def test_real_clamscan_detects_eicar(tmp_path, capsys):
    (tmp_path / "sub").mkdir()
    (tmp_path / "clean.txt").write_text("hello")
    (tmp_path / "sub" / "eicar.com").write_text(EICAR)
    rc = main([str(tmp_path), "-j", "2", "--batch-files", "1"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "Scanned files: 2" in out
    assert f"{tmp_path / 'sub' / 'eicar.com'}: Eicar-Test-Signature" in out
