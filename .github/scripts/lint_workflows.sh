#!/usr/bin/env bash
# Structural lint of this repository's workflow files, with actionlint.
#
# Called from TWO places, on purpose: the `checks` job of checks.yml, which
# runs on every pull request, and the `plan` job of build.yml, which every
# build layer `needs:`. The second is what makes it a publication gate. A
# lint that only runs in checks.yml gates nothing on a push to main, because
# both workflows fire on `push` and run at the same time, so a red lint there
# does not stop an image reaching GHCR.
#
# It lives in a script rather than being pasted into both workflows because
# the pinned version and its hash are ONE fact. Two copies of one fact can
# disagree, and this repository has already removed one instance of that
# shape (groups.yaml, CHANGELOG.md 2.9 addendum of 2026-09-17).
#
# What actionlint covers: a malformed `uses:` reference, a `needs:` edge to a
# job that does not exist, an expression that cannot resolve, and the shell
# faults shellcheck's static rules catch inside a `run:` block. What it does
# NOT cover: whether a `uses:` repository actually exists (it checks the
# reference format only), anything outside .github/workflows, and any runtime
# behaviour at all. It reads; it never runs.
set -euo pipefail

ACTIONLINT_VERSION=1.7.7
ACTIONLINT_SHA256=023070a287cd8cccd71515fedc843f1985bf96c436b7effaecce67290e7e0757

# actionlint DISABLES its shellcheck rule when the binary is missing, and
# still exits 0. Without this assertion the step would keep passing while
# silently covering less, which reads exactly like a pass. shellcheck itself
# comes from the runner image and stays unpinned, by fleet policy.
if ! command -v shellcheck > /dev/null 2>&1; then
  echo "lint_workflows.sh: shellcheck not found on PATH." >&2
  echo "actionlint would silently skip every shell rule. Refusing to run." >&2
  exit 1
fi
shellcheck --version

# Download outside the working directory: a lint step must not leave files at
# the repository root for a later step, or a future cleanliness check, to
# trip over.
workdir="${RUNNER_TEMP:-$(mktemp -d)}"
url="https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_amd64.tar.gz"
curl -sSfL -o "${workdir}/actionlint.tar.gz" "$url"
echo "${ACTIONLINT_SHA256}  ${workdir}/actionlint.tar.gz" | sha256sum -c -
tar xzf "${workdir}/actionlint.tar.gz" -C "${workdir}" actionlint

"${workdir}/actionlint" -color
