## What does this pull request do?

<!-- One or two sentences. Link the issue: "Closes #123". -->

## Type

- [ ] New rule or changed classification
- [ ] Loader, report, CLI or GitHub Action change
- [ ] Bug fix
- [ ] Documentation

## Checklist

- [ ] Case files added in `tests/fixtures/cases/` (every new rule has a breaking and a non-breaking side where it applies)
- [ ] `pytest` passes; no network in tests (use `httpx.MockTransport`)
- [ ] `ruff check . && ruff format --check .` passes
- [ ] README rule tables updated for new or changed rules
- [ ] CHANGELOG.md updated under "Unreleased"
