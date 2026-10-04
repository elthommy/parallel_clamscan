from parallel_clamscan.clamscan import build_command, parse_output
from parallel_clamscan.models import Detection, ScanError

# Captured from ClamAV 1.5.4 with --no-summary --stdout (plus the stderr WARNING).
REAL_OUTPUT = """\
/t/clean.txt: OK
/t/empty.txt: Empty file
/t/ei:car.com: Eicar-Test-Signature FOUND
/t/link: Symbolic link
/t/noperm: Access denied
/t/missing: No such file or directory
WARNING: /t/missing: Can't access file
"""


def test_build_command():
    assert build_command("clamscan", "/tmp/l", ["--max-filesize=1M"]) == [
        "clamscan",
        "--no-summary",
        "--stdout",
        "--file-list=/tmp/l",
        "--max-filesize=1M",
    ]


def test_parse_real_output():
    parsed = parse_output(REAL_OUTPUT)
    assert parsed.clean == ["/t/clean.txt", "/t/empty.txt"]
    assert parsed.detections == [Detection("/t/ei:car.com", "Eicar-Test-Signature")]
    assert parsed.errors == [
        ScanError("/t/noperm", "Access denied"),
        ScanError("/t/missing", "No such file or directory"),
    ]
    assert parsed.scanned == 3


def test_parse_path_with_colon_space():
    parsed = parse_output("/x/weird: name.txt: OK\n/x/a: b: Sig.X FOUND\n")
    assert parsed.clean == ["/x/weird: name.txt"]
    assert parsed.detections == [Detection("/x/a: b", "Sig.X")]


def test_parse_legacy_error_suffix_and_noise():
    parsed = parse_output("\n/p: Can't open file ERROR\nsome noise line\n")
    assert parsed.errors == [ScanError("/p", "Can't open file")]
    assert parsed.scanned == 0
