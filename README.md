# parallel_clamscan

Run ClamAV's `clamscan` in parallel over large directory trees.

`clamscan` runs as a single process. On a big tree it can take a long time while
using only one CPU core. `pclamscan` walks the folders and splits the files into
batches. It runs several `clamscan` processes side by side and merges their results
into one report.

On a 16-core machine, scanning `/usr/lib/python3.14` (32.5k files, 760 MB) took
**54 s with `pclamscan`, against 195 s with `clamscan -r`** (about 3.6× faster). See
[Performance & tuning](#performance--tuning).

> Not affiliated with or endorsed by Cisco or the ClamAV project. ClamAV is a
> registered trademark of Cisco Systems, Inc.
>
> The code in this project was written with [Claude](https://claude.com/claude-code)
> (Anthropic's AI assistant) and reviewed and tested by the author.

---

## Table of contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Command-line options](#command-line-options)
- [Output](#output)
- [JSON report](#json-report)
- [Exit codes](#exit-codes)
- [How it works](#how-it-works)
- [Error handling](#error-handling)
- [Interrupting a scan (Ctrl-C)](#interrupting-a-scan-ctrl-c)
- [Performance & tuning](#performance--tuning)
- [Limitations & differences from clamscan](#limitations--differences-from-clamscan)
- [Project layout](#project-layout)
- [Development](#development)
- [Related projects](#related-projects)
- [Credits](#credits)
- [License](#license)

---

## Requirements

- **Linux**, or another POSIX system. This was developed and tested on Arch Linux.
- **Python ≥ 3.12**. There are no runtime dependencies beyond the standard library.
- **ClamAV**: the `clamscan` binary on your `PATH`, with an up-to-date signature
  database. Run `freshclam` to download or update it.
- [**uv**](https://docs.astral.sh/uv/) is recommended for setup. Plain `pip` also works.

## Installation

```bash
git clone https://github.com/elthommy/parallel_clamscan.git && cd parallel_clamscan
uv sync                      # creates .venv, installs the package and dev tools
uv run pclamscan --help
```

Without uv:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .
pclamscan --help
```

## Usage

```bash
# Scan one or more folders (plain files are accepted too)
uv run pclamscan ~/Downloads ~/Documents

# Use 12 workers and also write a full JSON report
uv run pclamscan /data -j 12 --json-report report.json

# Pass options to clamscan itself: everything after `--` goes to every clamscan process
uv run pclamscan /data -- --max-filesize=100M --max-scansize=400M

# Use a specific clamscan binary
uv run pclamscan /data --clamscan /opt/clamav/bin/clamscan
```

> Do not pass `-r`, `--file-list`, `--stdout` or `--no-summary` after `--`. `pclamscan`
> already handles walking the folders and building the file lists. Folder-level
> filters such as `--exclude-dir` also have no effect, because `clamscan` only
> receives individual files. See [Limitations](#limitations--differences-from-clamscan).
>
> Options that hide per-file results (`-i`/`--infected`, `-o`/`--suppress-ok-results`,
> `--quiet`) are rejected. `pclamscan` needs one result line per file to notice files
> that were silently not scanned, and its summary already lists only infected files.

## Command-line options

| Option | Default | Description |
|---|---|---|
| `folders...` | *(required)* | One or more folders or files to scan. Each must exist. |
| `-j`, `--workers N` | `nb_cores / 2` (min 1) | Number of `clamscan` processes run in parallel. Each uses about 1 GB of RAM. |
| `--batch-files N` | `5000` | Maximum number of files in one batch (one `clamscan` run). |
| `--batch-mb N` | `2048` | Maximum total size of one batch, in MiB. A batch is closed as soon as it hits either limit. |
| `--json-report PATH` | – | Also write the full report as JSON to `PATH`. |
| `--clamscan PATH` | `clamscan` | The `clamscan` executable, looked up on `PATH`. |
| `-- ARGS...` | – | Extra arguments passed unchanged to every `clamscan` run. |

## Output

When stderr is a terminal, a progress line is redrawn every 0.5 s:

```
[pclamscan] scanned 12000/32560+ files (231.40 MiB) | infected 0 | errors 0 | 0:00:31
```

The second number is how many files the producer has found so far. A trailing `+`
means it is still walking the folders, so the total can still grow.

At the end, a summary is printed on stdout:

```
----------- SCAN SUMMARY -----------
Folders: /usr/lib/python3.14
Workers: 8
Scanned files: 32560
Data scanned: 680.10 MiB
Infected files: 1
Errors: 2
Time: 54.1 s (0:00:54)

Infected files:
  /usr/lib/python3.14/some/file.bin: Eicar-Test-Signature

Errors:
  /root/secret: Permission denied
  /data/locked.txt: Access denied
```

- `Scanned files` counts files that `clamscan` actually scanned: clean, empty or infected.
- `Data scanned` is the on-disk size of the files in the completed batches.
- At most 20 errors are listed. Use `--json-report` to get all of them.
- If the scan was interrupted, the summary includes `Scan INTERRUPTED: results are partial.`

## JSON report

With `--json-report PATH`, the full report is written as JSON:

```json
{
  "started": "2026-10-04T11:08:34+00:00",
  "finished": "2026-10-04T11:09:28+00:00",
  "duration_s": 54.133,
  "interrupted": false,
  "workers": 8,
  "folders": ["/usr/lib/python3.14"],
  "files_scanned": 32560,
  "bytes_scanned": 713138585,
  "infected": [
    {"path": "/data/eicar.com", "signature": "Eicar-Test-Signature"}
  ],
  "errors": [
    {"path": "/root/secret", "message": "Permission denied"},
    {"path": "<batch 12: 5000 files>", "message": "clamscan exit 40: ..."}
  ],
  "batches": [
    {"id": 0, "files": 5000, "duration_s": 41.2, "returncode": 0}
  ]
}
```

| Field | Meaning |
|---|---|
| `started`, `finished` | ISO-8601 UTC timestamps. |
| `duration_s` | Wall-clock duration in seconds. |
| `interrupted` | `true` if the scan was stopped with Ctrl-C. |
| `workers`, `folders` | The settings used. Folders are absolute paths. |
| `files_scanned`, `bytes_scanned` | Totals over completed batches. |
| `infected` | Every detection: the file path and the ClamAV signature name. |
| `errors` | Every error. `path` is a file or directory, or `<batch N: K files>` / `<producer>` for a failure that affects a whole batch or the folder walk. |
| `batches` | Statistics per batch, sorted by id. `returncode` is the `clamscan` exit code (`-1` means it could not be started). |

Paths that are not valid UTF-8 are kept losslessly as `\udcXX` escapes.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Everything was scanned and nothing was found. |
| `1` | At least one infected file was found. This takes precedence over errors. |
| `2` | Nothing was found, but some files, folders or batches could not be scanned. |
| `130` | Interrupted by Ctrl-C. Results are partial. |

`argparse` also exits with `2` on invalid arguments, a missing folder, or a
`clamscan` that cannot be found.

## How it works

```
                  ┌───────────────┐ Batch  ┌──────────────┐  BatchResult  ┌──────────────┐
  folders ──────► │ Producer      │──────► │ Worker × N   │─────────────► │ Aggregator   │──► summary
                  │ (thread)      │ task   │ (threads)    │ result queue  │ (main thread)│──► JSON report
                  │ walks folders │ queue  │ clamscan     │               │ live progress│
                  │ builds batches│(bounded│ --file-list  │               │              │
                  └──────┬────────┘  2×N)  └──────────────┘               └──────▲───────┘
                         │                ScanError (unreadable dirs…)           │
                         └───────────────────────────────────────────────────────┘
```

1. **Producer** (`producer.py`, one thread)
   - Walks every input folder iteratively with `os.scandir`, without recursion. It
     does not follow symlinks, which matches clamscan's default.
   - Adds regular files to the current batch until it reaches `--batch-files`
     files or `--batch-mb` MiB, then puts the `Batch` on the task queue.
   - The task queue is bounded (`2 × workers` items). If the workers fall behind,
     the producer waits, so memory use stays flat even on huge trees.
   - Directories it cannot read are sent straight to the result queue as `ScanError`s.
   - When it is done, it puts one `None` sentinel per worker on the task queue.

2. **Workers** (`worker.py`, N threads)
   - Each worker takes a batch and writes its paths to a temporary file list,
     using the raw bytes. It then runs:
     `clamscan --no-summary --stdout --follow-file-symlinks=0 --follow-dir-symlinks=0 --file-list=<tmp> [extra args]`.
     The symlink options mean a file swapped for a symlink after the walk is
     skipped, not followed.
   - Each `clamscan` runs in its own session, so a terminal Ctrl-C reaches only
     `pclamscan`, which then stops the children itself.
   - The output is parsed (`clamscan.py`) into a `BatchResult`: clean files,
     detections, errors, duration and exit code. The result goes on the result queue.
   - Every file of the batch must get exactly one result. A listed file with no
     result line, a result for a path that was not listed, or exit code 1 with no
     detection parsed is recorded as an error, so no file can silently drop out of
     the report.
   - When a worker receives a sentinel, it forwards a `None` to the result queue and exits.
   - Workers are threads and not processes because each one spends its time waiting
     on its `clamscan` child. The scanning happens in those child processes, so
     Python's GIL does not slow anything down.

3. **Aggregator** (`aggregator.py`, main thread)
   - Reads the result queue and adds each result into a `Report` as it arrives. It
     stops once it has received one sentinel from every worker.
   - Redraws the progress line. When everything is done, the CLI prints the summary
     and writes the JSON report.

### Parsing clamscan output

`clamscan --no-summary --stdout` prints one line per file. The parser was checked
against ClamAV 1.5.4:

| Line | Interpretation |
|---|---|
| `/p: OK`, `/p: Empty file` | scanned, clean |
| `/p: <Signature> FOUND` | infected |
| `/p: Symbolic link`, `/p: Excluded` | skipped (not an error) |
| `/p: Access denied`, `/p: No such file or directory`, `/p: … ERROR` | error |
| `WARNING: /p: Can't access file` (stderr) | error (kept once per path) |

Lines are split on the **last** `": "`, so paths that contain colons, even `": "`,
are handled correctly. Only `\n` ends a line, so other line-breaking characters
cannot split a result. Other stderr noise, such as `LibClamAV Warning: …`, is ignored.

## Error handling

| Situation | What happens |
|---|---|
| Folder or file cannot be read while walking | Recorded as an error. The walk continues. |
| `clamscan` reports a file it cannot read | Recorded as an error for that file. The rest of the batch is still scanned. |
| `clamscan` exits with an unexpected code (not 0, 1 or 2), or exits with 2 without saying which file failed | One error is recorded for the whole batch, including the end of its stderr. |
| `clamscan` cannot be started | One error for the whole batch, with `returncode: -1`. |
| Unexpected Python exception in the producer or a worker | Recorded as an error (`<producer>` or `<batch N>`). The other threads keep going, and the queues always receive their sentinels, so the program never hangs. |
| Filename containing a control character (newline, `\r`, `\x1c`, …) or a Unicode line separator | Not scanned, because it would break the one-path-per-line `--file-list` and the one-result-per-line output. Reported as an error. |
| Path longer than 1022 bytes | Not scanned, because `clamscan` reads `--file-list` lines into a 1024-byte buffer and would split the path. Reported as an error. |
| A listed file gets no result line, or `clamscan` reports a path that was not listed | Recorded as an error for that path. |

## Interrupting a scan (Ctrl-C)

On Ctrl-C, `pclamscan`:

1. Sets a shared stop flag and prints `Interrupted, stopping workers...`.
2. Stops the producer and terminates every running `clamscan` child. Batches still
   in the queue are dropped without being scanned.
3. Collects the results that are already finished, prints the summary marked
   **INTERRUPTED**, writes the JSON report (`"interrupted": true`), and exits with `130`.

No `clamscan` processes are left running. A second Ctrl-C during this shutdown makes
`pclamscan` quit at once, without a report. Any `clamscan` child still running then
continues until its batch is done, because it runs in its own session.

## Performance & tuning

Each `clamscan` process **loads the full signature database before it scans
anything**: about 6 s and about 1 GB of RAM per process on the reference machine.
This load is the main overhead, so it shapes how you should tune the scan:

- **Batch size (`--batch-files`, `--batch-mb`)**: bigger batches pay the DB load
  less often. Smaller batches spread the work more evenly near the end of the scan.
  A good rule is to give each worker at least a few batches of roughly
  `total_files / workers` or more. The 5000-file default suits large trees. For
  small trees, lower it so every worker gets work.
- **Workers (`-j`)**: the default is half the cores. Raise it on machines with many
  cores and plenty of RAM. Lower it if RAM is short (about 1 GB per worker) or if
  the disks are the bottleneck.

Benchmark: `/usr/lib/python3.14`, 32,560 files, 760 MB, 16 cores, 125 GB RAM,
ClamAV 1.5.4.

| Command | Wall time | Speed-up |
|---|---|---|
| `clamscan -r` | 195 s | 1.0× |
| `pclamscan -j 8 --batch-files 500` | 109 s | 1.8× |
| `pclamscan -j 8 --batch-files 2000` | 69 s | 2.8× |
| `pclamscan -j 8 --batch-files 4000` | 54 s | 3.6× |

**Alternative:** if you run the `clamd` daemon, `clamdscan --multiscan` also scans
in parallel. The daemon loads the database once, which avoids the per-batch DB
load. The cost is having to configure and run the daemon.

## Limitations & differences from clamscan

- **Symlinks are not followed** (clamscan's default), and they are not counted.
- **Folder-level clamscan options do not work**: `-r`, `--exclude-dir`,
  `--include-dir`, `--follow-dir-symlinks`. `clamscan` only receives a list of
  files. File-level options such as `--exclude`, `--max-filesize`, `--max-scansize`
  and `--detect-pua` do work.
- **File counts can differ slightly** from `clamscan -r`'s summary, because
  `pclamscan` counts empty files as scanned.
- **`Data scanned`** is the on-disk size of the batch files, matching clamscan's
  "Data read". It is not clamscan's decompressed "Data scanned".
- **Files that change during the scan** are scanned in whatever state they are in
  when their batch runs, so a batch's byte total is only an estimate.
- **Ordering**: results arrive in completion order. Batches in the JSON report are
  sorted by id.
- **Memory**: about 1 GB per worker for the signature database.

## Project layout

```
pyproject.toml                  # package metadata, `pclamscan` entry point, ruff/pytest config
src/parallel_clamscan/
  cli.py                        # argument parsing, starts threads, Ctrl-C handling, exit code
  producer.py                   # iter_files (walk), make_batches, run_producer (thread)
  worker.py                     # scan_batch (one clamscan run), run_worker (thread)
  clamscan.py                   # build_command, parse_output
  aggregator.py                 # Aggregator (result loop + progress), format_summary, write_json
  models.py                     # Batch, BatchResult, Detection, ScanError, ProducerStats, Report
tests/
  conftest.py                   # fake clamscan script + sample tree fixtures
  test_producer.py              # walking, symlinks, unreadable dirs, batching, sentinels, stop
  test_worker.py                # detection, errors, bad exit codes, missing binary, stop
  test_clamscan_parse.py        # parser vs real ClamAV 1.5.4 output, colons in paths
  test_aggregator.py            # merging, sentinels, progress, exit codes, summary, JSON
  test_cli.py                   # argument handling, end-to-end with fake clamscan
  test_integration.py           # end-to-end with the real clamscan + EICAR
```

## Development

Dev loop, run after every change:

```bash
ruff format .
ruff check --fix .
uv run pytest -x tests/<changed tests>   # fast feedback
uv run pytest                            # full suite before calling it done
```

- Most tests use a **fake `clamscan`**, a small Python script created in `tmp_path`
  that reports files containing `VIRUS` as infected. They run in seconds and do not
  need ClamAV.
- `tests/test_integration.py` runs the **real `clamscan`** against the standard,
  harmless [EICAR](https://www.eicar.org/download-anti-malware-testfile/) test
  string. It takes about 6 s for the DB load and is skipped if `clamscan` is not
  installed. The string is split in two in the source and only put together at
  runtime, so antivirus software should not flag the repository. While the test
  runs, a real EICAR file briefly exists in a pytest temp directory, which an
  on-access scanner may report.
- Conventions: every function has a docstring, functions stay under 50 lines, and
  test functions start with `test_`.

## Related projects

Other tools tackle the same problem, and one of them may suit you better:

- [MultiClam](https://github.com/spacebanana420/multiclam) is a shell script that
  also runs several `clamscan` instances on batches of files.
- [parallel-clamav](https://github.com/HansMoleman/parallel-clamav) is a wrapper
  that adds multi-threading to clamscan scans.
- [clamscanner](https://github.com/esoadamo/clamscanner) is a multi-threaded,
  recursive wrapper around the `clamd` daemon.
- `clamdscan --multiscan`, part of ClamAV itself, scans in parallel through `clamd`.
  The signature database is loaded only once, but the daemon has to be running.

## Credits

- The code was written with [Claude](https://claude.com/claude-code), Anthropic's
  AI assistant, and reviewed and tested by the author.
- [ClamAV](https://www.clamav.net/) does the actual scanning. This project only
  runs the `clamscan` program and does not include or link to any ClamAV code.

Not affiliated with or endorsed by Cisco or the ClamAV project. ClamAV is a
registered trademark of Cisco Systems, Inc.

## License

[MIT](LICENSE) © 2026 Thomas BARBIER
