# openapi-diff-check

[![CI](https://github.com/saizul/openapi-diff-check/actions/workflows/ci.yml/badge.svg)](https://github.com/saizul/openapi-diff-check/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/saizul/openapi-diff-check?sort=semver)](https://github.com/saizul/openapi-diff-check/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Container image](https://img.shields.io/badge/ghcr.io-saizul%2Fopenapi--diff--check-2496ED?logo=docker&logoColor=white)](https://github.com/saizul/openapi-diff-check/pkgs/container/openapi-diff-check)
![Python](https://img.shields.io/badge/python-3.11%E2%80%933.13-blue)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

**Catch breaking API changes before your users do.** openapi-diff-check compares two
OpenAPI 3.0 or 3.1 specs (YAML or JSON, files or URLs, `$ref`s followed), classifies every
difference as **breaking**, **non-breaking** or **info**, prints it as text, a Markdown
pull request comment or JSON, and exits `1` when something breaks.

```text
$ openapi-diff-check main/openapi.yaml openapi.yaml
Breaking changes (3)
  GET /pets  parameter query.limit
      accepted values narrowed: maximum 100 -> 50  [request-constraint-narrowed]
  POST /pets  request body application/json owner
      new required property 'owner'  [request-property-required-added]
  GET /pets/{petId}  response 200 application/json status
      new enum value(s) may be returned: 'adopted'; clients with exhaustive handling may break  [response-enum-value-added]

Non-breaking changes (1)
  GET /pets  parameter query.cursor
      new optional query parameter 'cursor'  [parameter-added]

Summary: 3 breaking, 1 non-breaking, 0 info, 0 ignored
```

## Contents

- [Features](#features)
- [Quick start](#quick-start)
- [GitHub Action](#github-action)
- [What is checked](#what-is-checked)
- [Ignore file](#ignore-file)
- [CLI reference](#cli-reference)
- [Output formats](#output-formats)
- [$ref resolution](#ref-resolution)
- [FAQ](#faq)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

## Features

- **OpenAPI 3.0 and 3.1**: `nullable` and `type: [x, "null"]`, boolean and numeric
  `exclusiveMinimum`/`exclusiveMaximum`, `const`
- **Direction aware**: a change is judged by who is affected. Narrowing what a request
  accepts is breaking, narrowing what a response returns is not, and vice versa
- **50+ rules**: removed paths and operations, removed or renamed parameters, new required
  parameters and fields, type changes, enum values, response codes, media types, response
  headers, narrowed constraints (`maxLength`, `maximum`, `pattern`, `minItems`, ...),
  `additionalProperties`, `oneOf`/`anyOf` options, formats and security (new auth,
  removed schemes, added scopes, moved API keys)
- **`$ref` resolution** across local files, with **remote references off by default**;
  `allOf` is merged, recursive schemas are handled
- **Readable reports**: colored text, a **Markdown PR comment** (with a marker so it can be
  updated in place) and **JSON** with stable fingerprints
- **Ignore file** for accepted changes, with mandatory reasons, globs and expiry dates
- **CI friendly**: exit `1` on breaking changes (`--fail-on` to tune), `2` on errors, a
  ready-made GitHub Action and `$GITHUB_STEP_SUMMARY` support
- Small: httpx + PyYAML, container image on `ghcr.io`

## Quick start

```bash
pipx install git+https://github.com/saizul/openapi-diff-check
openapi-diff-check old/openapi.yaml new/openapi.yaml

# compare what is deployed with your working copy
openapi-diff-check https://api.example.com/openapi.json openapi.yaml

# Markdown for a pull request comment, JSON for tooling
openapi-diff-check old.yaml new.yaml --format markdown --output report.md
openapi-diff-check old.yaml new.yaml --format json | jq '.summary'
```

With Docker, mount the directory that contains both specs and the files they reference:

```bash
docker run --rm -v "$PWD:/work" --user "$(id -u):$(id -g)" \
  ghcr.io/saizul/openapi-diff-check:latest old/openapi.yaml new/openapi.yaml
```

Exit codes: `0` nothing at or above `--fail-on`, `1` failing changes, `2` the specs or the
ignore file could not be loaded.

## GitHub Action

```yaml
name: OpenAPI diff
on:
  pull_request:
    paths: ["openapi.yaml", "openapi/**"]
permissions:
  contents: read
  pull-requests: write
jobs:
  diff:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - run: git worktree add "$RUNNER_TEMP/base" "origin/${{ github.base_ref }}"
      - id: diff
        uses: saizul/openapi-diff-check@v0.1.0
        with:
          base: ${{ runner.temp }}/base/openapi.yaml
          head: openapi.yaml
```

The complete workflow, including a step that posts the report as one pull request comment
and updates it on every push, is in
[`examples/github-workflow.yml`](examples/github-workflow.yml). The report is also added to
the job summary.

| Input | Default | Description |
| --- | --- | --- |
| `base` | required | Old spec: path or URL |
| `head` | required | New spec: path or URL |
| `fail-on` | `breaking` | `breaking`, `non-breaking`, `info` or `never` |
| `ignore-file` | `.openapi-diff-ignore.yaml` | Used when the file exists |
| `remote-refs` | `off` | `on` to follow `$ref` to other http(s) documents |
| `markdown-file` | `openapi-diff.md` | Markdown report path |
| `json-file` | `openapi-diff.json` | JSON report path |
| `python-version` | `3.12` | Python used to run the tool |

Outputs: `exit-code`, `breaking` (count, ignored ones excluded) and `markdown-file`.

## What is checked

Each finding has a rule id (used in ignore files) and a severity. *Request* rules apply to
parameters and request bodies, *response* rules to response bodies and headers.

### Paths, operations and parameters

| Rule | Severity |
| --- | --- |
| `path-removed`, `operation-removed` | breaking |
| `path-added`, `operation-added` | non-breaking |
| `operation-deprecated`, `operation-id-changed`, `path-parameter-renamed` | info |
| `parameter-removed`, `parameter-renamed` (same location and schema) | breaking |
| `parameter-required-added`, `parameter-became-required` | breaking |
| `parameter-serialization-changed` (`style`, `explode`) | breaking |
| `parameter-added` (optional), `parameter-became-optional` | non-breaking |
| `parameter-deprecated` | info |

Paths are matched by template, so `/pets/{id}` and `/pets/{petId}` are the same path.
Header parameters are matched case-insensitively.

### Request and response bodies

| Rule | Severity |
| --- | --- |
| `request-body-required-added`, `request-body-became-required` | breaking |
| `request-body-added` (optional), `request-body-became-optional` | non-breaking |
| `request-body-removed` | info |
| `request-media-type-removed`, `response-media-type-removed` | breaking |
| `request-media-type-added`, `response-media-type-added` | non-breaking |
| `response-status-removed`, `response-header-removed` | breaking |
| `response-status-added` | non-breaking |

### Schemas

| Change | Request | Response |
| --- | --- | --- |
| Type changed incompatibly (`*-type-changed`) | breaking | breaking |
| Type widened, e.g. `integer` to `number` (`request-type-widened`) | non-breaking | - |
| Type narrowed, e.g. `number` to `integer` (`response-type-narrowed`) | - | non-breaking |
| Became nullable (`*-nullable-added`) | non-breaking | breaking |
| No longer nullable (`*-nullable-removed`) | breaking | non-breaking |
| Enum value removed (`*-enum-value-removed`) | breaking | non-breaking |
| Enum value added (`*-enum-value-added`) | non-breaking | breaking |
| Enum introduced / removed (`*-enum-added`, `*-enum-removed`) | breaking / non-breaking | non-breaking / breaking |
| New required property (`request-property-required-added`) | breaking | - |
| New optional property (`*-property-added`) | non-breaking | non-breaking |
| Property removed (`*-property-removed`) | info (breaking with `additionalProperties: false`) | breaking |
| Property became required (`*-property-became-required`) | breaking | non-breaking |
| Property became optional (`*-property-became-optional`) | non-breaking | breaking |
| Constraint narrowed: `maxLength`, `minLength`, `maximum`, `minimum`, exclusive bounds, `maxItems`, `minItems`, `maxProperties`, `minProperties`, `uniqueItems`, `pattern`, `multipleOf` (`*-constraint-narrowed`) | breaking | info |
| Constraint widened (`*-constraint-widened`) | non-breaking | non-breaking |
| `additionalProperties: false` added / removed | breaking / non-breaking | - |
| `format` changed (`*-format-changed`) | breaking | breaking |
| `oneOf`/`anyOf` option removed (`*-oneof-option-removed`, `*-anyof-option-removed`) | breaking | non-breaking |
| `oneOf`/`anyOf` option added (`*-oneof-option-added`, `*-anyof-option-added`) | non-breaking | breaking |
| `default` changed (`default-changed`), property deprecated (`property-deprecated`) | info | info |

`readOnly` properties are skipped in requests and `writeOnly` properties in responses.
`allOf` parts are merged before comparing; `oneOf`/`anyOf` options are matched by `$ref`
name, then `title`, then position.

### Security

| Rule | Severity |
| --- | --- |
| `security-added`: a public operation (or one allowing `{}`) now requires auth | breaking |
| `security-requirement-removed`: an accepted scheme is gone | breaking |
| `security-scope-added`: an existing scheme needs more scopes | breaking |
| `security-scheme-changed`: type, `in`, `name`, `scheme`, OAuth flows or URLs changed | breaking |
| `security-requirement-added`, `security-scope-removed` | non-breaking |
| `security-removed`: the operation became public | info |

Operation-level `security` overrides the top-level one, as in the specification.

## Ignore file

Accepted changes go into `.openapi-diff-ignore.yaml` (picked up automatically from the
current directory) or any file passed with `--ignore`. Ignored findings are still shown in
their own section, but no longer fail the build. See
[`examples/.openapi-diff-ignore.yaml`](examples/.openapi-diff-ignore.yaml).

```yaml
ignore:
  - rule: response-enum-value-added      # glob allowed: "response-*"
    path: /pets*                         # glob allowed
    location: status                     # substring of the location
    reason: "SDKs map unknown statuses to UNKNOWN (#412)"
  - rule: operation-removed
    method: delete
    path: /pets/{petId}
    reason: "Removal announced in the v2 changelog"
    expires: 2027-06-30                  # stops applying after this date
  - fingerprint: "request-constraint-narrowed|POST|/pets|request body application/json name"
    reason: "The database column was always 50 characters"
```

Every entry needs a `reason` and at least one of `rule`, `path` or `fingerprint`. Expired
entries and entries that match nothing produce warnings, so the file does not rot.
Fingerprints (`rule|METHOD|path|location`) are listed in the JSON report.

## CLI reference

```text
openapi-diff-check OLD NEW [options]

  -f, --format {text,markdown,json}   output format (default: text)
  -o, --output FILE                   write the report to FILE instead of stdout
  --markdown-out FILE                 also write a Markdown report
  --json-out FILE                     also write a JSON report
  --github-summary                    append the Markdown report to $GITHUB_STEP_SUMMARY
  -i, --ignore FILE                   ignore file (default: .openapi-diff-ignore.yaml if present)
  --fail-on {breaking,non-breaking,info,never}   (default: breaking)
  --min-severity {breaking,non-breaking,info}    lowest severity shown in text output
  --remote-refs {off,on}              follow $ref to other http(s) documents (default: off)
  --color {auto,always,never}         NO_COLOR is respected
  --version
```

The Python API is small too:

```python
from openapi_diff_check.diff import compare
from openapi_diff_check.loader import load_spec

for finding in compare(load_spec("old.yaml"), load_spec("new.yaml")):
    print(finding.severity, finding.rule, finding.operation, finding.location, finding.message)
```

## Output formats

**Markdown** starts with `<!-- openapi-diff-check -->` so a workflow can find and update its
own comment. Breaking changes are listed in a table; non-breaking, info and ignored changes
are in collapsible sections.

**JSON** (`format_version: 1`):

```json
{
  "format_version": 1,
  "tool": "openapi-diff-check 0.1.0",
  "old": "old.yaml",
  "new": "new.yaml",
  "summary": {"breaking": 1, "non-breaking": 0, "info": 0, "ignored": 0},
  "has_breaking": true,
  "findings": [
    {
      "rule": "parameter-became-required",
      "severity": "breaking",
      "message": "parameter became required",
      "path": "/pets",
      "method": "GET",
      "location": "parameter query.limit",
      "fingerprint": "parameter-became-required|GET|/pets|parameter query.limit"
    }
  ],
  "warnings": []
}
```

Ignored findings carry `"ignored": true` and `"ignore_reason"`.

## $ref resolution

- References inside the document (`#/components/schemas/Pet`) always work.
- References to other local files (`./schemas/pet.yaml#/Pet`) work for specs loaded from
  disk, relative to the file that contains the reference.
- References to `http(s)` documents are **not fetched unless you pass `--remote-refs on`**,
  so comparing a spec never makes surprise network requests. Specs given as URLs on the
  command line are always fetched; their relative references count as remote.
- JSON pointers with `~0`/`~1` escapes, cycles between schemas, and `$ref` chains are handled;
  broken or circular reference chains are reported as errors (exit `2`).

## FAQ

**Why is a new enum value in a response breaking?**
Generated clients and `switch` statements often handle only the values they know. If your
clients are built to tolerate unknown values, ignore the rule:
`- {rule: response-enum-value-added, reason: "clients tolerate unknown values"}`.

**Why is removing a request field only info?**
Most servers ignore unknown fields, so clients that still send it keep working. With
`additionalProperties: false` on the schema it is reported as breaking.

**Does it validate my spec?**
No. It assumes both specs are valid and focuses on differences. Run a linter such as
Spectral or Redocly first if you need validation.

**Swagger 2.0?**
Not supported. Convert with a tool such as `swagger2openapi` first.

**How do I compare against the main branch in CI?**
Check out the base branch next to the pull request (`git worktree add`, as in the example
workflow) so relative `$ref` files exist for both versions.

**Does it phone home?**
No. The only network requests are the URLs you pass and, with `--remote-refs on`, the
documents they reference.

## Roadmap

Good first issues are marked below; details are in [CONTRIBUTING.md](CONTRIBUTING.md#good-first-issues).

- [ ] `--severity-override rule=severity` to reclassify rules without an ignore file *(good first issue)*
- [ ] `--header` for authenticated spec URLs *(good first issue)*
- [ ] Webhooks (3.1 `webhooks`) comparison
- [ ] Response `links` and callback comparison
- [ ] Discriminator mapping changes *(good first issue)*
- [ ] A `changelog` format for release notes *(good first issue)*
- [ ] Swagger 2.0 input through automatic conversion

## Contributing

New rules, test cases, documentation and bug reports are very welcome. Each rule is covered
by a tiny old/new spec in [`tests/fixtures/cases/`](tests/fixtures/cases), so adding a case is
a great first contribution. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the setup, the
project layout and a list of beginner issues. Please follow the
[Code of Conduct](CODE_OF_CONDUCT.md) and report security problems privately as described in
[SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © Saizul Amin
