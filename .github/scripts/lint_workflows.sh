#!/usr/bin/env bash
# Structural lint of this repository's workflow files, with actionlint.
#
# Two jobs call this script:
#   - the `checks` job of checks.yml, which runs on every pull request
#   - the `plan` job of build.yml, which every build layer `needs:`
# The second call makes the lint a publication gate. On a push to main, both
# workflows start at the same time. So a failed lint in checks.yml alone does
# not stop an image from reaching GHCR.
#
# The lint is a script, not a copy in each workflow, because the pinned
# version and its hash are one fact. Two copies of one fact can disagree. This
# repository already removed one case of that (groups.yaml, CHANGELOG.md 2.9
# addendum of 2026-09-17).
#
# actionlint finds these faults:
#   - a malformed `uses:` reference
#   - a `needs:` edge to a job that does not exist
#   - an expression that cannot resolve
#   - shell faults that shellcheck's static rules find in a `run:` block
# It does not check whether a `uses:` repository exists, only the reference
# format. It does not read files outside .github/workflows. It reads the files
# and never runs them, so it finds no runtime faults.
set -euo pipefail

ACTIONLINT_VERSION=1.7.7
ACTIONLINT_SHA256=023070a287cd8cccd71515fedc843f1985bf96c436b7effaecce67290e7e0757

# When the shellcheck binary is missing, actionlint turns off its shellcheck
# rule and still exits 0. Without this check, the step would pass while it
# covers less, and the log would look the same as a full pass. shellcheck
# comes from the runner image and is not pinned, by fleet policy.
if ! command -v shellcheck > /dev/null 2>&1; then
  echo "lint_workflows.sh: shellcheck not found on PATH." >&2
  echo "actionlint would silently skip every shell rule. Refusing to run." >&2
  exit 1
fi
shellcheck --version

# Download outside the working directory. A lint step must not leave files at
# the repository root, where a later step or a cleanliness check could fail
# on them.
workdir="${RUNNER_TEMP:-$(mktemp -d)}"
url="https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_amd64.tar.gz"
curl -sSfL -o "${workdir}/actionlint.tar.gz" "$url"
echo "${ACTIONLINT_SHA256}  ${workdir}/actionlint.tar.gz" | sha256sum -c -
tar xzf "${workdir}/actionlint.tar.gz" -C "${workdir}" actionlint

"${workdir}/actionlint" -color
