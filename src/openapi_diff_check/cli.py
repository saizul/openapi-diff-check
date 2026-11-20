"""Command line interface."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TextIO

import httpx

from openapi_diff_check._version import __version__
from openapi_diff_check.diff import BREAKING, INFO, NON_BREAKING, SEVERITIES, compare
from openapi_diff_check.ignore import DEFAULT_IGNORE_FILE, IgnoreFileError, apply_ignores, load_ignore
from openapi_diff_check.loader import Resolver, SpecError, load_spec
from openapi_diff_check.render import Report, render_json, render_markdown, render_text

EXIT_OK = 0
EXIT_BREAKING = 1
EXIT_ERROR = 2

FAIL_ON = {"breaking": (BREAKING,), "non-breaking": (BREAKING, NON_BREAKING), "info": SEVERITIES, "never": ()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openapi-diff-check",
        description="Detect breaking changes between two OpenAPI 3.0/3.1 specs (files or URLs).",
        epilog="Exit codes: 0 no failing changes, 1 failing changes (see --fail-on), 2 error.",
    )
    parser.add_argument("old", help="the base spec: path or http(s) URL (YAML or JSON)")
    parser.add_argument("new", help="the changed spec: path or http(s) URL (YAML or JSON)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "-f", "--format", choices=("text", "markdown", "json"), default="text", help="output format (default: text)"
    )
    parser.add_argument("-o", "--output", metavar="FILE", help="write the report to FILE instead of stdout")
    parser.add_argument("--markdown-out", metavar="FILE", help="also write a Markdown report (for PR comments)")
    parser.add_argument("--json-out", metavar="FILE", help="also write a JSON report")
    parser.add_argument(
        "--github-summary",
        action="store_true",
        help="append the Markdown report to $GITHUB_STEP_SUMMARY when it is set",
    )
    parser.add_argument(
        "-i",
        "--ignore",
        metavar="FILE",
        help=f"ignore file with accepted changes (default: {DEFAULT_IGNORE_FILE} if it exists)",
    )
    parser.add_argument(
        "--fail-on",
        choices=tuple(FAIL_ON),
        default="breaking",
        help="lowest severity that makes the command exit 1 (default: breaking)",
    )
    parser.add_argument(
        "--min-severity",
        choices=SEVERITIES,
        default=INFO,
        help="lowest severity shown in text output (default: info)",
    )
    parser.add_argument(
        "--remote-refs",
        choices=("off", "on"),
        default="off",
        help="follow $ref to http(s) documents other than the specs given (default: off)",
    )
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    return parser


def _use_color(choice: str, stream: TextIO, environ: dict[str, str] | os._Environ[str]) -> bool:
    if choice == "always":
        return True
    if choice == "never" or "NO_COLOR" in environ:
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def run(
    argv: list[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    environ: dict[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    env = environ if environ is not None else dict(os.environ)
    args = build_parser().parse_args(argv)

    try:
        allow_remote = args.remote_refs == "on"
        old = load_spec(args.old, resolver=Resolver(allow_remote=allow_remote, transport=transport))
        new = load_spec(args.new, resolver=Resolver(allow_remote=allow_remote, transport=transport))
        findings = compare(old, new)
    except SpecError as exc:
        print(f"error: {exc}", file=stderr)
        return EXIT_ERROR
    except RecursionError:
        print("error: the specs are nested too deeply to compare", file=stderr)
        return EXIT_ERROR

    warnings: list[str] = []
    ignore_path = args.ignore or (DEFAULT_IGNORE_FILE if Path(DEFAULT_IGNORE_FILE).is_file() else None)
    if ignore_path:
        if not Path(ignore_path).is_file():
            warnings.append(f"ignore file {ignore_path} not found; nothing is ignored")
        else:
            try:
                warnings.extend(apply_ignores(findings, load_ignore(ignore_path)))
            except IgnoreFileError as exc:
                print(f"error: {exc}", file=stderr)
                return EXIT_ERROR

    report = Report(old=args.old, new=args.new, findings=findings, warnings=warnings)
    if args.format == "json":
        text = render_json(report)
    elif args.format == "markdown":
        text = render_markdown(report)
    else:
        color = False if args.output else _use_color(args.color, stdout, env)
        text = render_text(report, color=color, min_severity=args.min_severity)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        stdout.write(text)
    if args.markdown_out:
        Path(args.markdown_out).write_text(render_markdown(report), encoding="utf-8")
    if args.json_out:
        Path(args.json_out).write_text(render_json(report), encoding="utf-8")
    summary_file = env.get("GITHUB_STEP_SUMMARY")
    if args.github_summary and summary_file:
        with open(summary_file, "a", encoding="utf-8") as fh:
            fh.write(render_markdown(report))

    failing = FAIL_ON[args.fail_on]
    if any(f.severity in failing for f in report.active()):
        return EXIT_BREAKING
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    return run(argv)
