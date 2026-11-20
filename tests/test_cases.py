"""Table-driven tests: every file in tests/fixtures/cases/ is one small old/new spec pair.

Each case lists exactly the findings (rule + severity) that the diff must produce, and
optionally the ``location`` of the first finding. Add a case by dropping in a new file.
"""

from pathlib import Path

import pytest
import yaml

from openapi_diff_check.diff import compare
from openapi_diff_check.loader import spec_from_dict

CASES = sorted((Path(__file__).parent / "fixtures" / "cases").glob("*.yaml"))


def load_case(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_there_are_many_cases():
    assert len(CASES) >= 60


@pytest.mark.parametrize("path", CASES, ids=[p.stem for p in CASES])
def test_case(path):
    case = load_case(path)
    assert case.get("description"), "every case needs a description"
    findings = compare(spec_from_dict(case["old"], "memory://old"), spec_from_dict(case["new"], "memory://new"))
    got = sorted((f.rule, f.severity) for f in findings)
    want = sorted((e["rule"], e["severity"]) for e in case["expect"])
    assert got == want, "\n".join(f"{f.severity} {f.rule} {f.operation} {f.location}: {f.message}" for f in findings)
    if "location" in case:
        assert findings[0].location == case["location"]


@pytest.mark.parametrize("path", CASES, ids=[p.stem for p in CASES])
def test_case_is_reflexive(path):
    """Comparing a spec with itself never reports anything."""
    case = load_case(path)
    for side in ("old", "new"):
        assert compare(spec_from_dict(case[side]), spec_from_dict(case[side])) == []
