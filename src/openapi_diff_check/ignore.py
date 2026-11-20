"""Ignore file: accept known changes so they no longer fail the build."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import yaml

from openapi_diff_check.diff import Finding

DEFAULT_IGNORE_FILE = ".openapi-diff-ignore.yaml"
ENTRY_KEYS = {"rule", "path", "method", "location", "fingerprint", "reason", "expires"}


class IgnoreFileError(Exception):
    pass


@dataclass
class IgnoreEntry:
    reason: str
    rule: str | None = None
    path: str | None = None
    method: str | None = None
    location: str | None = None
    fingerprint: str | None = None
    expires: dt.date | None = None
    index: int = 0
    used: bool = False

    def describe(self) -> str:
        parts = [f"{k}={v}" for k in ("rule", "method", "path", "location", "fingerprint") if (v := getattr(self, k))]
        return f"ignore[{self.index}] ({', '.join(parts)})"

    def matches(self, finding: Finding) -> bool:
        if self.fingerprint is not None and self.fingerprint != finding.fingerprint:
            return False
        if self.rule is not None and not fnmatchcase(finding.rule, self.rule):
            return False
        if self.path is not None and not fnmatchcase(finding.path, self.path):
            return False
        if self.method is not None and self.method.upper() != finding.method.upper():
            return False
        return self.location is None or self.location in finding.location


def parse_ignore(data: Any, source: str = "<memory>") -> list[IgnoreEntry]:
    if data is None:
        return []
    if isinstance(data, dict):
        unknown = set(data) - {"ignore"}
        if unknown:
            raise IgnoreFileError(f"{source}: unknown top-level keys: {', '.join(sorted(map(str, unknown)))}")
        data = data.get("ignore") or []
    if not isinstance(data, list):
        raise IgnoreFileError(f"{source}: expected a list under 'ignore'")
    entries = []
    for index, item in enumerate(data):
        where = f"{source}: ignore[{index}]"
        if not isinstance(item, dict):
            raise IgnoreFileError(f"{where}: must be a mapping")
        unknown = set(item) - ENTRY_KEYS
        if unknown:
            raise IgnoreFileError(f"{where}: unknown keys: {', '.join(sorted(map(str, unknown)))}")
        if not any(item.get(k) for k in ("rule", "path", "fingerprint")):
            raise IgnoreFileError(f"{where}: needs at least one of rule, path or fingerprint")
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise IgnoreFileError(f"{where}: 'reason' is required (say why the change is acceptable)")
        expires = item.get("expires")
        if isinstance(expires, str):
            try:
                expires = dt.date.fromisoformat(expires)
            except ValueError as exc:
                raise IgnoreFileError(f"{where}: expires must be a date (YYYY-MM-DD)") from exc
        elif expires is not None and not isinstance(expires, dt.date):
            raise IgnoreFileError(f"{where}: expires must be a date (YYYY-MM-DD)")
        entries.append(
            IgnoreEntry(
                reason=reason.strip(),
                rule=_opt(item, "rule"),
                path=_opt(item, "path"),
                method=_opt(item, "method"),
                location=_opt(item, "location"),
                fingerprint=_opt(item, "fingerprint"),
                expires=expires,
                index=index,
            )
        )
    return entries


def _opt(item: dict[str, Any], key: str) -> str | None:
    value = item.get(key)
    return None if value is None else str(value)


def load_ignore(path: str | Path) -> list[IgnoreEntry]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise IgnoreFileError(f"cannot read {path}: {exc.strerror or exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise IgnoreFileError(f"{path}: invalid YAML: {exc}") from exc
    return parse_ignore(data, str(path))


def apply_ignores(findings: list[Finding], entries: list[IgnoreEntry], today: dt.date | None = None) -> list[str]:
    """Mark matching findings as ignored. Returns warnings (expired or unused entries)."""
    today = today or dt.date.today()
    warnings = []
    active = []
    for entry in entries:
        if entry.expires is not None and entry.expires < today:
            warnings.append(f"{entry.describe()} expired on {entry.expires.isoformat()} and no longer applies")
        else:
            active.append(entry)
    for finding in findings:
        for entry in active:
            if entry.matches(finding):
                finding.ignored = True
                finding.ignore_reason = entry.reason
                entry.used = True
                break
    for entry in active:
        if not entry.used:
            warnings.append(f"{entry.describe()} matched nothing; remove it if the change has shipped")
    return warnings
