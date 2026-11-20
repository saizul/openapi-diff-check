# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | yes |

## What counts as a vulnerability

- Network requests to anything other than the specs given on the command line while
  `--remote-refs` is `off`
- Code execution, unbounded memory use or a hang caused by a crafted spec or ignore file
  (for example YAML tags, huge documents or reference cycles)
- Writing files other than the paths passed to `--output`, `--markdown-out`, `--json-out` or
  `$GITHUB_STEP_SUMMARY`
- Script injection through the GitHub Action inputs
- Markdown output that lets a spec author inject active content into a pull request comment

A missed or misclassified change is a bug, not a vulnerability; please open a normal issue.

## Reporting

Please **do not** open a public issue. Use
[GitHub private vulnerability reporting](https://github.com/saizul/openapi-diff-check/security/advisories/new)
with the version, the impact and steps to reproduce.

You will get an answer within 5 working days. Fixes are released as soon as possible and
credited in the changelog unless you prefer otherwise.
