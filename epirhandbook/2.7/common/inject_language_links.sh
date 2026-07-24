#!/bin/bash
# inject_language_links.sh -- thin wrapper around inject_language_links.R,
# matching the shell-entrypoint convention build_one_chapter.sh already
# uses (every other invocation in this image is a plain shell command; this
# keeps the CI call site the same shape rather than a bare `Rscript ...`).
#
# Usage (with the assembled site mounted at the working directory, and the
# handbook's PRISTINE `_quarto.yml` mounted alongside it):
#   docker run --rm -v <site>:/site -v <quarto_yml>:/quarto/_quarto.yml:ro \
#     -w /site epirhandbook-common:2.7 \
#     inject_language_links.sh /site /quarto/_quarto.yml [<base_url>]
set -euo pipefail

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "usage: inject_language_links.sh <site_dir> <quarto_yml> [<base_url>]" >&2
  exit 2
fi
site_dir="$1"
quarto_yml="$2"
base_url="${3:-}"

if [ ! -d "$site_dir" ]; then
  echo "inject_language_links.sh: no such directory: $site_dir" >&2
  exit 2
fi
if [ ! -f "$quarto_yml" ]; then
  echo "inject_language_links.sh: no such file: $quarto_yml" >&2
  exit 2
fi

exec Rscript /usr/local/bin/inject_language_links.R "$site_dir" "$quarto_yml" "$base_url"
