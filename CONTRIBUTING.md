# Contributing to openapi-diff-check

Thank you for helping! New rules, more test cases, better messages, documentation and bug
reports are all welcome.

- [Ways to contribute](#ways-to-contribute)
- [Good first issues](#good-first-issues)
- [Development setup](#development-setup)
- [Project layout](#project-layout)
- [Add a test case](#add-a-test-case)
- [Add a rule](#add-a-rule)
- [Guidelines](#guidelines)
- [Pull request process](#pull-request-process)

## Ways to contribute

| Size | Idea |
| --- | --- |
| 10 minutes | Fix a typo, clarify a rule in the README, add a FAQ entry |
| 30 minutes | Add a test case for a change you care about (one YAML file) |
| 1-2 hours | Add a rule or one of the good first issues |
| Larger | Webhooks, callbacks, Swagger 2.0 conversion (open an issue first) |

Comment on an issue before you start so nobody else picks the same one.

## Good first issues

1. **`--header "Name: value"` for spec URLs.** Pass headers to `Resolver._get`, allow reading
   the value from an environment variable (`Authorization: env:SPEC_TOKEN`) so tokens stay out
   of logs. (`loader.py`, `cli.py`, tests with `httpx.MockTransport`)
2. **Discriminator changes.** Report `discriminator.propertyName` changes and removed
   `mapping` entries as breaking. (`diff.py`, two case files)
3. **Response header became optional.** A `required: true` response header that becomes
   optional is breaking for clients. (`diff.py`, one case file)
4. **`changelog` output format.** Group non-breaking additions by operation for release notes.
   (`render.py`, `cli.py`, tests)
5. **Servers changed.** Report removed `servers` URLs as info. (`diff.py`, one case file)
6. **Deprecated property in responses.** `property-deprecated` is only reported for requests
   today; report it for responses too. (`diff.py`, one case file)
7. **Query parameter `allowEmptyValue` / `allowReserved`.** Treat turning them off as
   breaking. (`diff.py`, case files)

## Development setup

```bash
git clone https://github.com/saizul/openapi-diff-check
cd openapi-diff-check
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e .[dev]
pytest
ruff check . && ruff format --check .
```

Python 3.11+ is needed. Tests never use the network; URL loading is tested with
`httpx.MockTransport` (see `tests/test_loader.py`).

## Project layout

| Path | Responsibility |
| --- | --- |
| `src/openapi_diff_check/loader.py` | Files and URLs, YAML/JSON parsing, lazy `$ref` resolution, remote ref gate |
| `src/openapi_diff_check/diff.py` | `Differ`: every rule, `Finding`, severities |
| `src/openapi_diff_check/ignore.py` | Ignore file parsing and matching |
| `src/openapi_diff_check/render.py` | Text, Markdown and JSON reports |
| `src/openapi_diff_check/cli.py` | Arguments, exit codes, extra outputs |
| `action.yml` | Composite GitHub Action |
| `tests/fixtures/cases/` | One old/new spec pair per file with the expected findings |
| `tests/fixtures/specs/` | Multi-file specs for loader and CLI tests |

## Add a test case

Create `tests/fixtures/cases/<short-name>.yaml`:

```yaml
description: Removing a query parameter.
old:
  openapi: 3.0.3
  info: {title: Pets, version: 1.0.0}
  paths:
    /pets:
      get:
        parameters:
          - {name: limit, in: query, schema: {type: integer}}
        responses:
          "200": {description: OK}
new:
  openapi: 3.0.3
  info: {title: Pets, version: 1.0.0}
  paths:
    /pets:
      get:
        responses:
          "200": {description: OK}
expect:
  - rule: parameter-removed
    severity: breaking
# location: parameter query.limit   # optional: checks the first finding's location
```

`expect` must list **every** finding (rule and severity), so a case also proves that nothing
else is reported. `tests/test_cases.py` picks the file up automatically and also checks that
comparing each spec with itself yields no findings. Keep cases tiny: one change per file.

## Add a rule

1. Find the comparison in `diff.py` (`_compare_parameters`, `_compare_request_body`,
   `_compare_responses`, `_compare_security`, `_schema_inner` and helpers).
2. Call `self.add(rule_id, SEVERITY, message, location)`. Rule ids are kebab-case and stable:
   they are used in ignore files. Request/response variants are prefixed with the direction.
3. Think about direction: what breaks a client *sending* data is often fine for a client
   *receiving* it, and the other way round.
4. Add at least one case file for the breaking and one for the non-breaking side.
5. Add the rule to the tables in `README.md` and a line to `CHANGELOG.md`.

## Guidelines

- Keep runtime dependencies to httpx and PyYAML; discuss new ones first.
- Never fetch anything that the user did not ask for: remote `$ref`s stay opt-in.
- Messages are short, lower case, and say what changed (not what to do).
- Type hints everywhere; `ruff check` and `ruff format` clean.

## Pull request process

1. Fork and create a branch (`rule/discriminator`, `fix/nullable-31`).
2. Keep pull requests focused; fill in the checklist in the template.
3. Add an entry to `CHANGELOG.md` under "Unreleased".
4. A maintainer reviews within a few days.

By contributing you agree that your work is released under the MIT License and that you
follow the [Code of Conduct](CODE_OF_CONDUCT.md).
