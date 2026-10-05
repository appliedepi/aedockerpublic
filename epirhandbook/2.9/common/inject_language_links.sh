#!/bin/bash
# inject_language_links.sh: a thin wrapper around inject_language_links.R.
# It follows the convention of build_one_chapter.sh: a shell entrypoint.
# Every other command in this image is a plain shell command. With this
# wrapper, the CI call has the same form, not a bare `Rscript ...`.
#
# Usage, with the assembled site mounted at the working directory and the
# `languages.yml` of the handbook mounted next to it:
#   docker run --rm -v <site>:/site -v <languages_yml>:/quarto/languages.yml:ro \
#     -w /site epirhandbook-common:2.9 \
#     inject_language_links.sh /site /quarto/languages.yml [<base_url>]
set -euo pipefail

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "usage: inject_language_links.sh <site_dir> <languages_yml> [<base_url>]" >&2
  exit 2
fi
site_dir="$1"
languages_yml="$2"
base_url="${3:-}"

if [ ! -d "$site_dir" ]; then
  echo "inject_language_links.sh: no such directory: $site_dir" >&2
  exit 2
fi
if [ ! -f "$languages_yml" ]; then
  echo "inject_language_links.sh: no such file: $languages_yml" >&2
  exit 2
fi

exec Rscript /usr/local/bin/inject_language_links.R "$site_dir" "$languages_yml" "$base_url"
