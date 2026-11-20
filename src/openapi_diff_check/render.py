"""Text, Markdown (pull request comment) and JSON reports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from openapi_diff_check._version import __version__
from openapi_diff_check.diff import BREAKING, INFO, NON_BREAKING, SEVERITIES, Finding

MARKER = "<!-- openapi-diff-check -->"
TITLES = {BREAKING: "Breaking changes", NON_BREAKING: "Non-breaking changes", INFO: "Info"}
COLORS = {BREAKING: "31", NON_BREAKING: "33", INFO: "36", "dim": "2", "bold": "1"}


@dataclass
class Report:
    old: str
    new: str
    findings: list[Finding]
    warnings: list[str] = field(default_factory=list)

    def active(self, severity: str | None = None) -> list[Finding]:
        return [f for f in self.findings if not f.ignored and (severity is None or f.severity == severity)]

    @property
    def ignored(self) -> list[Finding]:
        return [f for f in self.findings if f.ignored]

    def summary(self) -> dict[str, int]:
        out = {s: len(self.active(s)) for s in SEVERITIES}
        out["ignored"] = len(self.ignored)
        return out


def _paint(text: str, kind: str, color: bool) -> str:
    return f"\033[{COLORS[kind]}m{text}\033[0m" if color else text


def summary_text(report: Report) -> str:
    s = report.summary()
    return f"{s[BREAKING]} breaking, {s[NON_BREAKING]} non-breaking, {s[INFO]} info, {s['ignored']} ignored"


def _where(f: Finding) -> str:
    parts = [p for p in (f.operation, f.location) if p]
    return "  ".join(parts) if parts else "(document)"


def render_text(report: Report, color: bool = False, min_severity: str = INFO) -> str:
    lines = [_paint(f"Comparing {report.old} -> {report.new}", "bold", color), ""]
    shown = SEVERITIES[: SEVERITIES.index(min_severity) + 1]
    for severity in shown:
        items = report.active(severity)
        if not items:
            continue
        lines.append(_paint(f"{TITLES[severity]} ({len(items)})", severity, color))
        for f in items:
            lines.append(f"  {_paint(_where(f), 'bold', color)}")
            lines.append(f"      {f.message}  {_paint('[' + f.rule + ']', 'dim', color)}")
        lines.append("")
    if report.ignored:
        lines.append(_paint(f"Ignored ({len(report.ignored)})", "dim", color))
        for f in report.ignored:
            lines.append(_paint(f"  {_where(f)}: {f.message} [{f.rule}] - {f.ignore_reason}", "dim", color))
        lines.append("")
    for warning in report.warnings:
        lines.append(_paint(f"warning: {warning}", NON_BREAKING, color))
    if not report.findings:
        lines.append("No differences found.")
    lines.append(_paint(f"Summary: {summary_text(report)}", "bold", color))
    return "\n".join(lines) + "\n"


def _md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")


def _code(text: str) -> str:
    """Content of an inline code span inside a table cell."""
    return text.replace("|", "\\|").replace("`", "'").replace("\n", " ")


def _md_table(items: list[Finding], with_reason: bool = False) -> list[str]:
    head = "| Operation | Location | Change | Rule |" + (" Reason |" if with_reason else "")
    sep = "| --- | --- | --- | --- |" + (" --- |" if with_reason else "")
    rows = [head, sep]
    for f in items:
        op = f"`{_code(f.operation)}`" if f.operation else "-"
        loc = f"`{_code(f.location)}`" if f.location else "-"
        row = f"| {op} | {loc} | {_md(f.message)} | `{f.rule}` |"
        if with_reason:
            row += f" {_md(f.ignore_reason)} |"
        rows.append(row)
    return rows


def render_markdown(report: Report) -> str:
    s = report.summary()
    if s[BREAKING]:
        title = f"### OpenAPI diff: {s[BREAKING]} breaking change{'s' if s[BREAKING] != 1 else ''}"
    elif report.active():
        title = "### OpenAPI diff: no breaking changes"
    else:
        title = "### OpenAPI diff: no changes"
    lines = [MARKER, title, "", f"**{summary_text(report)}**", ""]
    breaking = report.active(BREAKING)
    if breaking:
        lines.extend(_md_table(breaking))
        lines.append("")
        lines.append(
            "If a breaking change is intended, add it to `.openapi-diff-ignore.yaml` with a reason, "
            "or bump the API's major version."
        )
        lines.append("")
    for severity in (NON_BREAKING, INFO):
        items = report.active(severity)
        if items:
            lines.append(f"<details><summary>{TITLES[severity]} ({len(items)})</summary>")
            lines.append("")
            lines.extend(_md_table(items))
            lines.append("")
            lines.append("</details>")
            lines.append("")
    if report.ignored:
        lines.append(f"<details><summary>Ignored ({len(report.ignored)})</summary>")
        lines.append("")
        lines.extend(_md_table(report.ignored, with_reason=True))
        lines.append("")
        lines.append("</details>")
        lines.append("")
    for warning in report.warnings:
        lines.append(f"> [!WARNING]\n> {_md(warning)}\n")
    lines.append(f"<sub>openapi-diff-check {__version__}: `{_code(report.old)}` → `{_code(report.new)}`</sub>")
    return "\n".join(lines) + "\n"


def report_to_dict(report: Report) -> dict[str, Any]:
    return {
        "format_version": 1,
        "tool": f"openapi-diff-check {__version__}",
        "old": report.old,
        "new": report.new,
        "summary": report.summary(),
        "has_breaking": bool(report.active(BREAKING)),
        "findings": [f.to_dict() for f in report.findings],
        "warnings": report.warnings,
    }


def render_json(report: Report) -> str:
    return json.dumps(report_to_dict(report), indent=2, ensure_ascii=False) + "\n"
