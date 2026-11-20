#!/bin/sh
# Ways to run openapi-diff-check outside GitHub Actions.
set -e

# pipx
pipx install git+https://github.com/saizul/openapi-diff-check
openapi-diff-check old/openapi.yaml new/openapi.yaml

# Docker: mount the directory that contains both specs (and their $ref'd files)
docker run --rm -v "$PWD:/work" --user "$(id -u):$(id -g)" ghcr.io/saizul/openapi-diff-check:latest \
  old/openapi.yaml new/openapi.yaml --format markdown --output report.md

# Compare a deployed spec with your working copy
openapi-diff-check https://api.example.com/openapi.json openapi.yaml

# GitLab CI or any other CI: fail on breaking changes, keep a JSON report as an artifact
openapi-diff-check "$BASE_SPEC" openapi.yaml --json-out openapi-diff.json
