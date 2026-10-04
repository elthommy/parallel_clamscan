"""Command-line entry point: wire producer, workers and aggregator together."""

from __future__ import annotations

import argparse
import os
import queue
import shutil
import sys
import threading
from typing import TextIO

from parallel_clamscan.aggregator import (
    Aggregator,
    default_progress_stream,
    format_summary,
    write_json,
)
from parallel_clamscan.models import ProducerStats, Report
from parallel_clamscan.producer import run_producer
from parallel_clamscan.worker import run_worker

_MIB = 1024 * 1024


def default_workers() -> int:
    """Return half the CPU count, at least 1."""
    return max(1, (os.cpu_count() or 2) // 2)


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="pclamscan",
        description="Run clamscan in parallel over folders. "
        "Arguments after '--' are passed to clamscan as-is.",
        epilog="Exit codes: 0 clean, 1 infected file(s) found, 2 errors only, 130 interrupted.",
    )
    parser.add_argument("folders", nargs="+", help="folders (or files) to scan")
    parser.add_argument(
        "-j",
        "--workers",
        type=int,
        default=default_workers(),
        help="number of parallel clamscan processes (default: %(default)s, ~1 GB RAM each)",
    )
    parser.add_argument(
        "--batch-files", type=int, default=5000, help="max files per batch (default: %(default)s)"
    )
    parser.add_argument(
        "--batch-mb", type=int, default=2048, help="max MiB per batch (default: %(default)s)"
    )
    parser.add_argument("--json-report", metavar="PATH", help="write a JSON report to PATH")
    parser.add_argument(
        "--clamscan", default="clamscan", help="clamscan executable (default: %(default)s)"
    )
    return parser


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    """Parse argv; everything after the first '--' is returned as clamscan args."""
    if "--" in argv:
        idx = argv.index("--")
        argv, extra = argv[:idx], argv[idx + 1 :]
    else:
        extra = []
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.workers < 1 or args.batch_files < 1 or args.batch_mb < 1:
        parser.error("--workers, --batch-files and --batch-mb must be >= 1")
    missing = [f for f in args.folders if not os.path.exists(f)]
    if missing:
        parser.error(f"no such file or directory: {', '.join(missing)}")
    resolved = shutil.which(args.clamscan)
    if resolved is None:
        parser.error(f"clamscan executable not found: {args.clamscan}")
    args.clamscan = resolved
    return args, extra


def _start_threads(
    args: argparse.Namespace,
    extra: list[str],
    task_queue: queue.Queue,
    result_queue: queue.Queue,
    stop: threading.Event,
    stats: ProducerStats,
) -> list[threading.Thread]:
    """Start the producer thread and the worker threads."""
    producer = threading.Thread(
        target=run_producer,
        name="producer",
        args=(args.folders, task_queue, result_queue, args.workers, stop),
        kwargs={"max_files": args.batch_files, "max_bytes": args.batch_mb * _MIB, "stats": stats},
        daemon=True,
    )
    workers = [
        threading.Thread(
            target=run_worker,
            name=f"worker-{i}",
            args=(task_queue, result_queue, args.clamscan, extra, stop),
            daemon=True,
        )
        for i in range(args.workers)
    ]
    threads = [producer, *workers]
    for t in threads:
        t.start()
    return threads


def scan(args: argparse.Namespace, extra: list[str], progress: TextIO | None) -> Report:
    """Run the whole parallel scan and return the final report."""
    task_queue: queue.Queue = queue.Queue(maxsize=2 * args.workers)
    result_queue: queue.Queue = queue.Queue()
    stop = threading.Event()
    stats = ProducerStats()
    report = Report(folders=[os.path.abspath(f) for f in args.folders], workers=args.workers)
    aggregator = Aggregator(result_queue, args.workers, report, stats, progress)
    threads = _start_threads(args, extra, task_queue, result_queue, stop, stats)
    try:
        aggregator.run()
    except KeyboardInterrupt:
        stop.set()
        report.interrupted = True
        print("\nInterrupted, stopping workers...", file=sys.stderr)
        aggregator.run()
    for t in threads:
        t.join()
    report.finish()
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    args, extra = parse_args(sys.argv[1:] if argv is None else argv)
    report = scan(args, extra, default_progress_stream())
    print(format_summary(report))
    if args.json_report:
        write_json(report, args.json_report)
        print(f"\nJSON report written to {args.json_report}")
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
