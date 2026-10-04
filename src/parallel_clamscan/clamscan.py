"""Build clamscan command lines and parse their output."""

from __future__ import annotations

from dataclasses import dataclass, field

from parallel_clamscan.models import Detection, ScanError

# Per-file statuses that mean "scanned, nothing found".
_CLEAN_STATUSES = {"OK", "Empty file"}
# Per-file statuses that mean "deliberately not scanned" (not an error).
_SKIPPED_STATUSES = {"Symbolic link", "Excluded"}
_WARNING_PREFIX = "WARNING: "


@dataclass
class ParsedOutput:
    """Per-file results extracted from clamscan output."""

    clean: list[str] = field(default_factory=list)
    detections: list[Detection] = field(default_factory=list)
    errors: list[ScanError] = field(default_factory=list)

    @property
    def scanned(self) -> int:
        """Number of files actually scanned (clean or infected)."""
        return len(self.clean) + len(self.detections)


def build_command(clamscan: str, file_list: str, extra_args: list[str]) -> list[str]:
    """Return the clamscan argv scanning every path listed in ``file_list``."""
    return [clamscan, "--no-summary", "--stdout", f"--file-list={file_list}", *extra_args]


def _split_line(line: str) -> tuple[str, str] | None:
    """Split ``<path>: <status>`` on the last ': ' (paths may contain colons)."""
    path, sep, status = line.rpartition(": ")
    if not sep or not path:
        return None
    return path, status.strip()


def _classify(parsed: ParsedOutput, path: str, status: str, seen_errors: set[str]) -> None:
    """Record one ``path: status`` pair into ``parsed``."""
    if status in _CLEAN_STATUSES:
        parsed.clean.append(path)
    elif status.endswith(" FOUND"):
        parsed.detections.append(Detection(path, status.removesuffix(" FOUND")))
    elif status in _SKIPPED_STATUSES:
        return
    elif path not in seen_errors:
        seen_errors.add(path)
        parsed.errors.append(ScanError(path, status.removesuffix(" ERROR")))


def parse_output(output: str) -> ParsedOutput:
    """Parse clamscan ``--no-summary --stdout`` output into per-file results.

    Lines look like ``/p: OK``, ``/p: Eicar-Test-Signature FOUND``,
    ``/p: Access denied`` or ``WARNING: /p: Can't access file``. A path that
    fails is often reported twice (status line + WARNING); it is kept once.
    """
    parsed = ParsedOutput()
    seen_errors: set[str] = set()
    for raw in output.splitlines():
        line = raw.removeprefix(_WARNING_PREFIX)
        split = _split_line(line)
        if split is None:
            continue
        path, status = split
        if raw.startswith(_WARNING_PREFIX) and status in _CLEAN_STATUSES:
            continue
        _classify(parsed, path, status, seen_errors)
    return parsed
