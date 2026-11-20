import datetime as dt
import io
import json
from pathlib import Path

import pytest

from openapi_diff_check import __version__
from openapi_diff_check.cli import main, run
from openapi_diff_check.diff import Finding
from openapi_diff_check.ignore import IgnoreFileError, apply_ignores, parse_ignore

SPECS = Path(__file__).parent / "fixtures" / "specs"
V1 = str(SPECS / "petstore-v1.yaml")
V2 = str(SPECS / "petstore-v2.json")
EXAMPLE_IGNORE = Path(__file__).resolve().parent.parent / "examples" / ".openapi-diff-ignore.yaml"


def cli(*argv: str, env: dict | None = None):
    out, err = io.StringIO(), io.StringIO()
    code = run(list(argv), stdout=out, stderr=err, environ=env or {})
    return code, out.getvalue(), err.getvalue()


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert __version__ in capsys.readouterr().out


def test_breaking_changes_exit_1():
    code, out, _ = cli(V1, V2)
    assert code == 1
    assert "Breaking changes (9)" in out
    assert "Summary: 9 breaking, 1 non-breaking, 0 info, 0 ignored" in out
    assert "\033[" not in out


def test_same_spec_exit_0():
    code, out, _ = cli(V1, V1)
    assert code == 0 and "No differences found." in out


def test_reverse_direction_has_different_findings():
    code, out, _ = cli(V2, V1)
    assert code == 1
    assert "operation added" in out and "[request-constraint-widened]" in out


def test_fail_on_never_and_non_breaking():
    assert cli(V1, V2, "--fail-on", "never")[0] == 0
    ignore = Path("ignore.yaml")
    ignore.write_text("ignore:\n  - rule: '*'\n    path: '/pets*'\n    reason: test\n", encoding="utf-8")
    assert cli(V1, V2, "--ignore", str(ignore))[0] == 0
    # only the non-breaking cursor parameter is left when the breaking ones are ignored
    ignore.write_text(
        "ignore:\n"
        "  - {path: '/pets/{petId}', reason: v2}\n"
        "  - {path: /pets, method: post, reason: v2}\n"
        "  - {rule: 'response-*', reason: v2}\n"
        "  - {rule: request-constraint-narrowed, reason: v2}\n",
        encoding="utf-8",
    )
    assert cli(V1, V2, "--ignore", str(ignore))[0] == 0
    assert cli(V1, V2, "--ignore", str(ignore), "--fail-on", "non-breaking")[0] == 1


def test_color_always_and_no_color_env():
    assert "\033[31m" in cli(V1, V2, "--color", "always")[1]
    assert "\033[" not in cli(V1, V2, env={"NO_COLOR": "1"})[1]


def test_min_severity_hides_lower_levels():
    _, out, _ = cli(V1, V2, "--min-severity", "breaking")
    assert "Non-breaking changes" not in out and "Breaking changes" in out


def test_json_output():
    code, out, _ = cli(V1, V2, "--format", "json")
    assert code == 1
    data = json.loads(out)
    assert data["format_version"] == 1 and data["has_breaking"] is True
    assert data["summary"] == {"breaking": 9, "non-breaking": 1, "info": 0, "ignored": 0}
    first = data["findings"][0]
    assert set(first) == {"rule", "severity", "message", "path", "method", "location", "fingerprint"}
    assert first["fingerprint"] == "request-constraint-narrowed|GET|/pets|parameter query.limit"


def test_markdown_output_and_extra_files(tmp_path):
    md, js = tmp_path / "r.md", tmp_path / "r.json"
    code, out, _ = cli(V1, V2, "--format", "markdown", "--markdown-out", str(md), "--json-out", str(js))
    assert code == 1
    assert out.startswith("<!-- openapi-diff-check -->\n### OpenAPI diff: 9 breaking changes")
    assert "| `DELETE /pets/{petId}` | - | operation removed | `operation-removed` |" in out
    assert "<details><summary>Non-breaking changes (1)</summary>" in out
    assert md.read_text(encoding="utf-8") == out
    assert json.loads(js.read_text(encoding="utf-8"))["summary"]["breaking"] == 9


def test_markdown_without_changes():
    _, out, _ = cli(V1, V1, "--format", "markdown")
    assert "### OpenAPI diff: no changes" in out


def test_output_file(tmp_path):
    target = tmp_path / "report.txt"
    code, out, _ = cli(V1, V2, "-o", str(target), "--color", "always")
    assert code == 1 and out == ""
    assert "\033[" not in target.read_text(encoding="utf-8")


def test_github_step_summary(tmp_path):
    summary = tmp_path / "summary.md"
    summary.write_text("# Earlier step\n", encoding="utf-8")
    cli(V1, V2, "--github-summary", env={"GITHUB_STEP_SUMMARY": str(summary)})
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("# Earlier step\n<!-- openapi-diff-check -->")
    # without the flag nothing is written
    cli(V1, V1, env={"GITHUB_STEP_SUMMARY": str(summary)})
    assert summary.read_text(encoding="utf-8") == text


def test_default_ignore_file_is_picked_up():
    Path(".openapi-diff-ignore.yaml").write_text(
        "ignore:\n  - rule: response-enum-value-added\n    reason: clients use a default branch\n", encoding="utf-8"
    )
    code, out, _ = cli(V1, V2)
    assert code == 1
    assert "Ignored (2)" in out and "clients use a default branch" in out
    assert "Summary: 7 breaking, 1 non-breaking, 0 info, 2 ignored" in out


def test_ignore_warnings_and_errors(tmp_path):
    code, out, _ = cli(V1, V1, "--ignore", "missing.yaml")
    assert code == 0 and "ignore file missing.yaml not found" in out
    bad = tmp_path / "bad.yaml"
    bad.write_text("ignore:\n  - rule: x\n", encoding="utf-8")
    code, _, err = cli(V1, V1, "--ignore", str(bad))
    assert code == 2 and "'reason' is required" in err


def test_load_errors_exit_2():
    code, _, err = cli(V1, str(SPECS / "swagger2.yaml"))
    assert code == 2 and "Swagger 2.0" in err
    code, _, err = cli(str(SPECS / "remote-ref.yaml"), str(SPECS / "remote-ref.yaml"))
    assert code == 2 and "--remote-refs on" in err


def test_example_ignore_file_parses():
    entries = parse_ignore(__import__("yaml").safe_load(EXAMPLE_IGNORE.read_text(encoding="utf-8")))
    assert entries and all(e.reason for e in entries)


# -- ignore matching -------------------------------------------------------------


def finding(**kw):
    base = {"rule": "parameter-removed", "severity": "breaking", "message": "m", "path": "/pets", "method": "get"}
    return Finding(**{**base, **kw})


def test_ignore_matching_rules():
    entries = parse_ignore(
        {
            "ignore": [
                {"rule": "parameter-*", "path": "/pets", "method": "GET", "reason": "a"},
                {"path": "/admin/*", "reason": "internal"},
                {"rule": "response-property-removed", "location": "legacyId", "reason": "b"},
                {"fingerprint": "operation-removed|DELETE|/pets|", "reason": "c"},
            ]
        }
    )
    items = [
        finding(),
        finding(method="post"),
        finding(rule="path-removed", path="/admin/users", method=""),
        finding(rule="response-property-removed", location="response 200 application/json legacyId"),
        finding(rule="operation-removed", method="delete"),
    ]
    warnings = apply_ignores(items, entries)
    assert [f.ignored for f in items] == [True, False, True, True, True]
    assert items[2].ignore_reason == "internal"
    assert warnings == []


def test_expired_and_unused_entries_warn():
    entries = parse_ignore(
        [
            {"rule": "parameter-removed", "reason": "old", "expires": "2020-01-01"},
            {"rule": "nothing-matches", "reason": "stale", "expires": dt.date(2999, 1, 1)},
        ]
    )
    item = finding()
    warnings = apply_ignores([item], entries, today=dt.date(2026, 1, 1))
    assert item.ignored is False
    assert "expired on 2020-01-01" in warnings[0]
    assert "matched nothing" in warnings[1]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"ignore": [{"reason": "x"}]}, "needs at least one of"),
        ({"ignore": [{"rule": "x", "reason": "x", "colour": 1}]}, "unknown keys"),
        ({"ignore": [{"rule": "x", "reason": "x", "expires": "soon"}]}, "expires must be a date"),
        ({"ignore": ["x"]}, "must be a mapping"),
        ({"ignores": []}, "unknown top-level keys"),
        ({"ignore": "x"}, "expected a list"),
    ],
)
def test_ignore_validation(data, message):
    with pytest.raises(IgnoreFileError, match=message):
        parse_ignore(data)
