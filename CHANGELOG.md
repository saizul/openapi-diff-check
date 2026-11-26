# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `--severity-override RULE=SEVERITY` (repeatable, glob patterns, last match wins) to
  reclassify rules before the exit code is computed; unused overrides produce a warning.
- Rules for `readOnly`/`writeOnly` flips on existing properties:
  `request-property-became-read-only` (breaking), `request-property-no-longer-read-only`,
  `response-property-became-write-only` (breaking) and `response-property-no-longer-write-only`.

### Fixed

- A property that became `readOnly` (requests) or `writeOnly` (responses) was skipped
  entirely, so the change was not reported at all.

## [0.1.0] - 2026-11-20

### Added

- Comparison of OpenAPI 3.0 and 3.1 specs from YAML or JSON files and http(s) URLs.
- Lazy `$ref` resolution across local files, JSON pointer escapes, `allOf` merging and
  recursive schemas; references to remote documents are off by default (`--remote-refs on`).
- Direction-aware rules for paths, operations, parameters (removed, renamed, new required,
  serialization), request bodies, media types, response codes and headers, schema types,
  nullability, enums, `const`, constraints, formats, `additionalProperties`, `oneOf`/`anyOf`
  options and security (requirements, scopes, schemes).
- Severities `breaking`, `non-breaking` and `info`; exit code 1 on breaking changes,
  `--fail-on` to tune, exit code 2 on load errors.
- Text (colored), Markdown (pull request comment with marker) and JSON (`format_version: 1`,
  fingerprints) reports; `--markdown-out`, `--json-out`, `--github-summary`.
- Ignore file with globs, mandatory reasons, expiry dates and warnings for unused entries.
- Composite GitHub Action and example workflow that comments on pull requests.
- 79 small fixture cases covering every rule.
- Container image on `ghcr.io/saizul/openapi-diff-check` (non-root).

[Unreleased]: https://github.com/saizul/openapi-diff-check/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/saizul/openapi-diff-check/releases/tag/v0.1.0
