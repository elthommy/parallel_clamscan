"""Shared fixtures: a fake clamscan executable for fast, deterministic tests."""

import stat
import sys
import textwrap

import pytest

FAKE_CLAMSCAN = textwrap.dedent(
    """\
    #!{python}
    # Fake clamscan: files containing VIRUS are infected, unreadable ones error.
    import sys, time
    args = sys.argv[1:]
    if "--sleep" in args:
        time.sleep(float(args[args.index("--sleep") + 1]))
    if "--crash" in args:
        print("boom", file=sys.stderr)
        sys.exit(40)
    def opt(name):
        return next((a.split("=", 1)[1] for a in args if a.startswith(name + "=")), None)
    sys.stdout.reconfigure(errors="surrogateescape")
    file_list = opt("--file-list")
    rc = 0
    with open(file_list, encoding="utf-8", errors="surrogateescape") as fh:
        paths = [p for p in fh.read().split("\\n") if p]
    for path in paths:
        try:
            data = open(path, "rb").read()
        except OSError:
            print(f"{{path}}: Access denied")
            rc = max(rc, 2)
            continue
        if b"VIRUS" in data:
            print(f"{{path}}: Fake.Virus FOUND")
            rc = 1
        elif "--drop-ok" not in args:
            print(f"{{path}}: OK")
    if opt("--extra-path"):
        print(f"{{opt('--extra-path')}}: OK")
    sys.exit(int(opt("--force-rc") or rc))
    """
)


@pytest.fixture
def fake_clamscan(tmp_path):
    """Return the path of an executable fake clamscan script."""
    script = tmp_path / "fake-clamscan"
    script.write_text(FAKE_CLAMSCAN.format(python=sys.executable))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


@pytest.fixture
def sample_tree(tmp_path):
    """Create a small tree with 5 clean files and 1 infected file."""
    root = tmp_path / "tree"
    (root / "a" / "b").mkdir(parents=True)
    (root / "c").mkdir()
    for i, rel in enumerate(["f1", "a/f2", "a/b/f3", "a/b/f4", "c/f5"]):
        (root / rel).write_text(f"clean {i}")
    (root / "c" / "bad:file").write_text("this has a VIRUS inside")
    return root
